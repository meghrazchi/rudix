"""Harness for ingestion golden fixtures and kill-and-redeliver tests (R06-01).

Runs document task bodies synchronously (``run_async`` cannot nest inside an async test)
against a per-test SQLite file, or PostgreSQL when given a URL, with the fakes the worker
tests already use: object storage, embeddings, Qdrant, graph, and OCR. ``snapshot`` returns
everything a scenario changed in a JSON-ready form with UUIDs replaced by stable labels and
timestamps and durations dropped.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

# Strict settings must load when the harness is the first module to import them.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.clients import minio_client as minio_module
from app.core.config import settings
from app.db import session as db_session_module
from app.domains.documents.extraction.extraction_service import ResultExtractionStream
from app.domains.documents.extraction.models import ExtractionResult
from app.models.connector_source import SourceReference
from app.models.document import Document, DocumentChunk
from app.models.organization import Organization
from app.models.pipeline import PipelineEvent, PipelineRun
from app.models.usage import AuditLog, UsageEvent
from app.models.user import User
from app.workers import document_tasks, notification_helper, status_tracking
from app.workers.async_runtime import run_async
from app.workers.ingestion.stages import extract as extract_stage

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "ingestion_golden"
UPDATE_ENV = "INGESTION_GOLDEN_UPDATE"
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# Module attributes the OCR and table scenarios replace. They move with the stage code.
PINNED_SETTINGS: dict[str, Any] = {
    "enterprise_graph_enabled": False,
    "feature_enable_entity_extraction": False,
    "feature_enable_relation_extraction": False,
    "entity_extraction_strict_mode": False,
    "feature_enable_pipeline_explorer": True,
    "feature_enable_advanced_pdf_extraction": True,
    "feature_enable_table_aware_retrieval": True,
    "pdf_extraction_enable_tables": True,
    "ocr_enabled": True,
    # The pdf_ocr golden records the default languages; a local .env may set others.
    "ocr_default_languages": "eng",
    "dlp_enabled": True,
    "dlp_action": "warn",
    "document_index_version": "v1",
    "qdrant_vector_size": 1536,
}
OCR_PATCH_TARGET: tuple[Any, str] = (extract_stage, "run_ocr")
# R06-02: the stage streams pages through ``stream_document``; a fake that returns a whole
# ExtractionResult is wrapped by ``patch_extraction``.
EXTRACT_PATCH_TARGET: tuple[Any, str] = (extract_stage, "stream_document")


def patch_extraction(
    monkeypatch: pytest.MonkeyPatch, extract: Callable[..., ExtractionResult]
) -> None:
    def _stream(source: Any, **kwargs: Any) -> ResultExtractionStream:
        return ResultExtractionStream(extract(source, **kwargs))

    monkeypatch.setattr(*EXTRACT_PATCH_TARGET, _stream)


class _Body:
    """Object body with sized reads (the stage never reads without a size)."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, amt: int | None = None) -> bytes:
        end = len(self._data) if amt is None else self._pos + amt
        chunk = self._data[self._pos : end]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        return None


class FakeMinio:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.reads = 0

    def get_object(self, **_: Any) -> dict[str, Any]:
        self.reads += 1
        return {"Body": _Body(self.data)}


class FakeEmbeddings:
    """Deterministic embeddings; ``before_call`` runs first and may raise."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []
        self.before_call: Callable[[int], None] | None = None

    async def embed_chunks(self, *, chunks: list[Any]) -> Any:
        if self.before_call is not None:
            self.before_call(len(self.batches))
        self.batches.append([str(chunk.id) for chunk in chunks])
        tokens = sum(int(getattr(chunk, "token_count", 0)) for chunk in chunks)
        return type(
            "FakeEmbeddingResult",
            (),
            {
                "model_name": settings.openai_embedding_model,
                "index_version": chunks[0].index_version if chunks else "v1",
                "provider_type": "fake",
                "vector_dimension": settings.qdrant_vector_size,
                "batch_count": 1,
                "retry_count": 0,
                "input_tokens": tokens,
                "total_tokens": tokens,
                "latency_ms": 3,
                "approximate_cost_usd": Decimal("0.000002") * len(chunks),
                "vectors_by_chunk_id": {
                    chunk.id: [0.001] * settings.qdrant_vector_size for chunk in chunks
                },
            },
        )()


class FakeQdrant:
    """Records upserts and deletes; ``points`` is the resulting point set."""

    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.points: set[str] = set()
        self.point_runs: dict[str, str | None] = {}
        self.reuse_lookups: list[int] = []
        self.stale_deleted = 0
        self.before_upsert: Callable[[int], None] | None = None

    @staticmethod
    def build_point_id(*, document_id: UUID, chunk_index: int, index_version: str) -> str:
        return f"{document_id}:{index_version}:{chunk_index}"

    async def upsert_chunks(self, *, chunks: list[Any], **kwargs: Any) -> Any:
        if self.before_upsert is not None:
            self.before_upsert(len(self.upserts))
        point_ids = [str(chunk.qdrant_point_id) for chunk in chunks]
        parents = kwargs.get("parent_text_by_chunk_id") or {}
        self.upserts.append(
            {
                "point_ids": point_ids,
                "vector_count": len(kwargs.get("vectors_by_chunk_id") or {}),
                "chunking_strategy": kwargs.get("chunking_strategy"),
                "chunking_profile_version": kwargs.get("chunking_profile_version"),
                "parent_text_chunks": [str(c.id) for c in chunks if c.id in parents],
                "collection_name": kwargs.get("collection_name"),
            }
        )
        self.points.update(point_ids)
        for point_id in point_ids:
            self.point_runs[point_id] = kwargs.get("ingest_run_id")
        return type("Upsert", (), {"upserted_count": len(chunks), "batch_count": 1})()

    async def find_reusable_vectors(self, **kwargs: Any) -> dict[str, list[float]]:
        self.reuse_lookups.append(len(list(kwargs.get("chunk_hashes") or [])))
        return {}

    async def delete_stale_document_points(self, **kwargs: Any) -> None:
        # R06-06: points of this document version written by another run.
        marker = f"{kwargs['document_id']}:{kwargs['index_version']}:"
        run_id = kwargs["ingest_run_id"]
        stale = {p for p in self.points if p.startswith(marker) and self.point_runs[p] != run_id}
        self.points -= stale
        self.stale_deleted += len(stale)
        self.deletes.append({"index_version": kwargs["index_version"]})

    async def count_document_points(self, **kwargs: Any) -> int:
        marker = f"{kwargs['document_id']}:{kwargs['index_version']}:"
        return sum(1 for point in self.points if point.startswith(marker))

    async def delete_document_points(self, **kwargs: Any) -> Any:
        index_version = kwargs.get("index_version")
        self.deletes.append({"index_version": index_version})
        marker = f":{index_version}:" if index_version else ":"
        self.points = {point for point in self.points if marker not in point}
        return type("Delete", (), {"deleted": True})()


class FakeGraphService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        async def _call(**_: Any) -> dict[str, int]:
            self.calls.append(name)
            return {}

        return _call


class FailingEntityExtraction:
    async def extract_from_chunks(self, **_: Any) -> Any:
        raise RuntimeError("entity extraction provider unavailable")


@dataclass
class Fakes:
    minio: FakeMinio
    embeddings: FakeEmbeddings = field(default_factory=FakeEmbeddings)
    qdrant: FakeQdrant = field(default_factory=FakeQdrant)
    graph: FakeGraphService = field(default_factory=FakeGraphService)
    ocr_calls: list[list[int]] = field(default_factory=list)

    def reset_calls(self) -> None:
        self.minio.reads = 0
        self.embeddings.batches.clear()
        self.qdrant.upserts.clear()
        self.qdrant.deletes.clear()
        self.graph.calls.clear()
        self.ocr_calls.clear()


@dataclass
class Seeded:
    organization_id: UUID
    user_id: UUID
    document_id: UUID


@dataclass
class IngestionEnv:
    factory: async_sessionmaker[AsyncSession]
    engine: AsyncEngine
    fakes: Fakes
    monkeypatch: pytest.MonkeyPatch
    created_orgs: list[UUID] = field(default_factory=list)

    def set_content(self, data: bytes) -> None:
        self.fakes.minio.data = data

    def seed(
        self,
        *,
        filename: str = "golden.txt",
        file_type: str = "txt",
        status: str = "uploaded",
        connector: bool = False,
    ) -> Seeded:
        seeded = run_async(_seed(self.factory, filename, file_type, status, connector))
        self.created_orgs.append(seeded.organization_id)
        return seeded

    def run_task(self, task: Any, document_id: UUID, *, task_id: str, **kwargs: Any) -> Any:
        """Run a task body with ``request.id`` set, the way a worker delivery would."""
        task.push_request(id=task_id)
        try:
            return task.run(str(document_id), **kwargs)
        finally:
            task.pop_request()

    def run_async(self, coro: Any) -> Any:
        return run_async(coro)


def _register_sqlite_functions(dbapi_connection: Any, _: Any = None) -> None:
    dbapi_connection.create_function("to_tsvector", 2, lambda _l, t: t or "", deterministic=True)


@pytest.fixture
def ingestion_env(
    sqlite_template_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[IngestionEnv]:
    db_file = tmp_path / "ingestion.db"
    shutil.copyfile(sqlite_template_db, db_file)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", poolclass=StaticPool)
    event.listen(engine.sync_engine, "connect", _register_sqlite_functions)
    yield from _env(engine, monkeypatch)


@pytest.fixture
def ingestion_env_pg(monkeypatch: pytest.MonkeyPatch) -> Iterator[IngestionEnv]:
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL-backed tests")
    engine = create_async_engine(url, poolclass=NullPool)
    yield from _env(engine, monkeypatch)


def _env(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> Iterator[IngestionEnv]:
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    # Pin what the fixtures depend on so a local .env cannot change them (or reach a provider).
    for name, value in PINNED_SETTINGS.items():
        monkeypatch.setattr(settings, name, value)
    for module in (document_tasks, status_tracking, db_session_module):
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(notification_helper, "emit_notification", lambda **_: None)
    fakes = Fakes(minio=FakeMinio(b""))
    monkeypatch.setattr(minio_module, "minio_client", fakes.minio)
    monkeypatch.setattr(document_tasks, "_embedding_service", fakes.embeddings)
    monkeypatch.setattr(document_tasks, "_qdrant_service", fakes.qdrant)
    monkeypatch.setattr(document_tasks, "_graph_service", fakes.graph)

    def _fake_run_ocr(content: bytes, candidate_pages: list[int], **_: Any) -> Any:
        from app.domains.documents.services.ocr_service import (
            OcrDocumentResult,
            OcrPageResult,
        )

        fakes.ocr_calls.append(list(candidate_pages))
        pages = [
            OcrPageResult(
                page_number=page,
                text=f"Scanned page {page} lists the travel reimbursement rules in detail.",
                languages=["eng"],
                status="completed",
                confidence=88.0,
            )
            for page in candidate_pages
        ]
        return OcrDocumentResult(
            status="completed",
            pages=pages,
            duration_ms=7,
            languages=["eng"],
            avg_confidence=88.0,
        )

    monkeypatch.setattr(*OCR_PATCH_TARGET, _fake_run_ocr)
    env = IngestionEnv(factory=factory, engine=engine, fakes=fakes, monkeypatch=monkeypatch)
    try:
        yield env
    finally:
        if engine.dialect.name == "postgresql":
            for org_id in env.created_orgs:
                run_async(_delete_org(factory, org_id))
        run_async(engine.dispose())


async def _seed(
    factory: async_sessionmaker[AsyncSession],
    filename: str,
    file_type: str,
    status: str,
    connector: bool,
) -> Seeded:
    suffix = uuid4().hex[:10]
    async with factory() as session:
        org = Organization(name=f"Golden {suffix}", slug=f"golden-{suffix}")
        session.add(org)
        await session.flush()
        user = User(
            organization_id=org.id,
            external_auth_id=f"golden-{suffix}",
            email=f"golden-{suffix}@example.com",
            display_name="Golden User",
        )
        session.add(user)
        await session.flush()
        external_item_id = None
        if connector:
            from ingestion_golden_connector import seed_connector_item

            external_item_id = await seed_connector_item(session, org.id, user.id, suffix)
        document = Document(
            organization_id=org.id,
            uploaded_by_user_id=user.id,
            filename=filename,
            file_type=file_type,
            storage_bucket="documents",
            storage_object_key=f"uploads/{org.id}/{uuid4()}.{file_type}",
            status=status,
            connector_external_item_id=external_item_id,
            ingestion_source="connector" if connector else "upload",
        )
        session.add(document)
        await session.flush()
        if connector and external_item_id is not None:
            from ingestion_golden_connector import seed_source_document

            await seed_source_document(session, org.id, external_item_id, document.id)
        await session.commit()
        return Seeded(organization_id=org.id, user_id=user.id, document_id=document.id)


async def _delete_org(factory: async_sessionmaker[AsyncSession], org_id: UUID) -> None:
    async with factory() as session:
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


# ── Snapshot and normalisation ──────────────────────────────────────────────────────────


class Labeler:
    def __init__(self, seeded: Seeded) -> None:
        self._labels: dict[str, str] = {
            str(seeded.organization_id): "org",
            str(seeded.user_id): "user",
            str(seeded.document_id): "document",
        }

    def label(self, value: str) -> str:
        if value not in self._labels:
            self._labels[value] = f"uuid-{len(self._labels) - 2}"
        return self._labels[value]

    def normalize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): self.normalize(item)
                for key, item in value.items()
                if not _is_volatile_key(str(key))
            }
        if isinstance(value, list | tuple):
            return [self.normalize(item) for item in value]
        if isinstance(value, UUID):
            return self.label(str(value))
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, str):
            return _UUID_RE.sub(lambda match: self.label(match.group(0)), value)
        return value


def _is_volatile_key(key: str) -> bool:
    return key.endswith("_at") or "duration" in key


DOCUMENT_FIELDS = (
    "status",
    "error_message",
    "page_count",
    "chunk_count",
    "chunking_strategy",
    "chunking_profile_version",
    "chunking_config_snapshot",
    "language",
    "language_source",
    "language_confidence",
    "dlp_scan_result",
    "extraction_snapshot",
    "ocr_quality_status",
    "ocr_avg_confidence",
    "ocr_quality_snapshot",
    "embedding_provider_type",
    "embedding_vector_dimension",
    "graph_extraction_status",
    "processing_task_id",
)
CHUNK_FIELDS = (
    "index_version",
    "chunk_index",
    "page_number",
    "chunk_hash",
    "chunk_level",
    "parent_chunk_id",
    "chunk_type",
    "qdrant_point_id",
    "token_count",
    "section_path",
    "language",
    "child_count",
)


async def _rows(env: IngestionEnv, seeded: Seeded) -> dict[str, Any]:
    async with env.factory() as session:
        document = (
            await session.execute(select(Document).where(Document.id == seeded.document_id))
        ).scalar_one()
        chunks = (
            await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == seeded.document_id)
                .order_by(DocumentChunk.index_version, DocumentChunk.chunk_index)
            )
        ).scalars()
        chunk_rows = [{name: getattr(chunk, name) for name in CHUNK_FIELDS} for chunk in chunks]
        chunk_ids = [
            str(row[0])
            for row in (
                await session.execute(
                    select(DocumentChunk.id)
                    .where(DocumentChunk.document_id == seeded.document_id)
                    .order_by(DocumentChunk.index_version, DocumentChunk.chunk_index)
                )
            ).all()
        ]
        usage = (
            await session.execute(
                select(UsageEvent)
                .where(UsageEvent.organization_id == seeded.organization_id)
                .order_by(UsageEvent.created_at)
            )
        ).scalars()
        audits = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.organization_id == seeded.organization_id)
                .order_by(AuditLog.created_at, AuditLog.action)
            )
        ).scalars()
        runs = list(
            (
                await session.execute(
                    select(PipelineRun)
                    .where(PipelineRun.document_id == seeded.document_id)
                    .order_by(PipelineRun.started_at)
                )
            ).scalars()
        )
        pipeline = []
        for run in runs:
            events = (
                await session.execute(
                    select(PipelineEvent.node_name, PipelineEvent.status)
                    .where(PipelineEvent.pipeline_run_id == run.id)
                    .order_by(PipelineEvent.sequence)
                )
            ).all()
            pipeline.append(
                {
                    "pipeline_type": run.pipeline_type,
                    "status": run.status,
                    "events": [f"{node}:{status}" for node, status in events],
                }
            )
        references = (
            await session.execute(
                select(SourceReference)
                .where(SourceReference.document_id == seeded.document_id)
                .order_by(SourceReference.created_at)
            )
        ).scalars()
        return {
            "chunk_ids": chunk_ids,
            "document": {name: getattr(document, name) for name in DOCUMENT_FIELDS},
            "chunks": chunk_rows,
            "usage_events": [
                {
                    "event_type": item.event_type,
                    "model_name": item.model_name,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "cost_usd": str(item.cost_usd) if item.cost_usd is not None else None,
                    "metadata": item.metadata_json,
                }
                for item in usage
            ],
            "audit_actions": [{"action": a.action, "metadata": a.metadata_json} for a in audits],
            "pipeline_runs": pipeline,
            "source_references": [
                {
                    "reference_type": ref.reference_type,
                    "chunk_id": ref.chunk_id,
                    "locator": ref.locator_json,
                    "metadata": ref.metadata_json,
                }
                for ref in references
            ],
        }


def snapshot(env: IngestionEnv, seeded: Seeded, *, outcome: Any) -> dict[str, Any]:
    labeler = Labeler(seeded)
    rows = run_async(_rows(env, seeded))
    for chunk_id in rows.pop("chunk_ids"):
        labeler.label(chunk_id)
    fakes = env.fakes
    return labeler.normalize(
        {
            "outcome": outcome,
            **rows,
            "qdrant_upserts": fakes.qdrant.upserts,
            "qdrant_deletes": fakes.qdrant.deletes,
            "embedding_batches": fakes.embeddings.batches,
            "graph_calls": fakes.graph.calls,
            "ocr_calls": fakes.ocr_calls,
            "minio_reads": fakes.minio.reads,
        }
    )


def assert_matches_golden(name: str, actual: dict[str, Any]) -> None:
    path = GOLDEN_DIR / f"{name}.json"
    rendered = json.dumps(actual, indent=2, sort_keys=True, default=str) + "\n"
    if os.environ.get(UPDATE_ENV) == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        return
    assert path.exists(), f"missing golden fixture {path}; run with {UPDATE_ENV}=1"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(rendered) == expected
