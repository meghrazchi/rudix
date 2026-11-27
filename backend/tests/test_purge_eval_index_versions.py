"""R02-05: purge legacy eval- index versions; report inactive non-eval versions."""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
from qdrant_client.http.models import PointIdsList
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

from app.core.config import settings
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.evaluations.services.eval_index_purge_service import (
    EXIT_INACTIVE_VERSIONS,
    EXIT_OK,
    EvalIndexPurgeService,
    classify_index_version,
)
from app.models.document import DocumentChunk
from app.models.enums import DocumentStatus, EvaluationRunStatus
from app.models.organization import Organization
from app.models.user import User

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "purge_eval_index_versions.py"


@dataclass
class _Point:
    id: str
    payload: dict[str, Any]


@dataclass
class FakeQdrantClient:
    points: list[_Point] = field(default_factory=list)
    scroll_calls: list[dict[str, Any]] = field(default_factory=list)
    delete_calls: list[dict[str, Any]] = field(default_factory=list)

    def scroll(self, **kwargs: Any) -> tuple[list[_Point], Any]:
        self.scroll_calls.append(kwargs)
        start = int(kwargs.get("offset") or 0)
        limit = int(kwargs["limit"])
        page = self.points[start : start + limit]
        next_offset = start + limit if start + limit < len(self.points) else None
        return page, next_offset

    def delete(self, **kwargs: Any) -> None:
        self.delete_calls.append(kwargs)
        selector = kwargs["points_selector"]
        assert isinstance(selector, PointIdsList)
        doomed = set(selector.points)
        self.points = [p for p in self.points if p.id not in doomed]


async def _seed(db_session: AsyncSession) -> dict[str, Any]:
    """Org A: v1, two eval versions (one owned by a running run) and legacy v0.

    Org B: v1 and one eval version.
    """
    repo = DocumentRepository()
    eval_repo = EvaluationRepository()
    seeded: dict[str, Any] = {}
    for key in ("a", "b"):
        org = Organization(name=f"Purge {key}", slug=f"purge-{key}-{uuid4().hex[:8]}")
        db_session.add(org)
        await db_session.flush()
        user = User(
            organization_id=org.id,
            external_auth_id=f"purge-{uuid4().hex[:8]}",
            email=f"purge-{uuid4().hex[:8]}@example.com",
        )
        db_session.add(user)
        await db_session.flush()
        document = await repo.create_document(
            db_session,
            organization_id=org.id,
            uploaded_by_user_id=user.id,
            filename="p.pdf",
            file_type="pdf",
            storage_bucket="documents",
            storage_object_key=f"seed/{uuid4().hex}.pdf",
            status=DocumentStatus.indexed.value,
        )
        seeded[f"org_{key}"] = org.id
        seeded[f"doc_{key}"] = document.id

    evaluation_set = await eval_repo.create_evaluation_set(
        db_session, organization_id=seeded["org_a"], name="Purge set"
    )
    running = await eval_repo.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.running.value,
        config={},
    )
    finished = await eval_repo.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.completed.value,
        config={},
    )
    seeded["running_version"] = f"eval-{running.id.hex[:10]}-1"
    seeded["stale_version"] = f"eval-{finished.id.hex[:10]}-1"
    seeded["orphan_version"] = "eval-ffffffffff-3"

    layout = {
        "a": [
            (settings.document_index_version, 2),
            (seeded["stale_version"], 3),
            (seeded["running_version"], 2),
            ("v0", 1),
        ],
        "b": [(settings.document_index_version, 1), (seeded["orphan_version"], 2)],
    }
    points: list[_Point] = []
    for key, versions in layout.items():
        for version, count in versions:
            for index in range(count):
                await repo.create_document_chunk(
                    db_session,
                    document_id=seeded[f"doc_{key}"],
                    page_number=1,
                    chunk_index=index,
                    text="private document text",
                    token_count=4,
                    embedding_model=settings.openai_embedding_model,
                    index_version=version,
                    qdrant_point_id=f"{key}:{version}:{index}",
                )
                points.append(
                    _Point(
                        id=f"{key}:{version}:{index}",
                        payload={
                            "organization_id": str(seeded[f"org_{key}"]),
                            "document_id": str(seeded[f"doc_{key}"]),
                            "index_version": version,
                        },
                    )
                )
    points.append(_Point(id="no-version", payload={"organization_id": str(seeded["org_a"])}))
    await db_session.commit()
    seeded["qdrant"] = FakeQdrantClient(points=points)
    return seeded


def _by_key(report: Any) -> dict[tuple[str, str], Any]:
    return {(item.organization_id, item.index_version): item for item in report.versions}


async def _chunk_versions(db_session: AsyncSession) -> list[str]:
    rows = await db_session.execute(select(DocumentChunk.index_version))
    return sorted(rows.scalars())


def test_classify_index_version() -> None:
    active = ("v1",)
    assert classify_index_version("v1", active_versions=active, protected_prefixes=[]) == "active"
    assert classify_index_version("v0", active_versions=active, protected_prefixes=[]) == (
        "inactive"
    )
    assert classify_index_version("eval-a-1", active_versions=active, protected_prefixes=[]) == (
        "eval"
    )
    assert (
        classify_index_version("eval-a-1", active_versions=active, protected_prefixes=["eval-a-"])
        == "eval_in_progress"
    )


def test_service_rejects_bad_batch_size() -> None:
    with pytest.raises(ValueError):
        EvalIndexPurgeService(qdrant_client=None, batch_size=0)


@pytest.mark.asyncio
async def test_dry_run_reports_counts_and_deletes_nothing(db_session: AsyncSession) -> None:
    seeded = await _seed(db_session)
    qdrant: FakeQdrantClient = seeded["qdrant"]
    total_points = len(qdrant.points)
    before = await _chunk_versions(db_session)

    report = await EvalIndexPurgeService(qdrant_client=qdrant, batch_size=3).run(
        db_session, apply=False
    )

    rows = _by_key(report)
    org_a, org_b = str(seeded["org_a"]), str(seeded["org_b"])
    assert rows[(org_a, settings.document_index_version)].classification == "active"
    assert rows[(org_a, settings.document_index_version)].chunk_count == 2
    stale = rows[(org_a, seeded["stale_version"])]
    assert (stale.classification, stale.chunk_count, stale.point_count) == ("eval", 3, 3)
    assert rows[(org_a, seeded["running_version"])].classification == "eval_in_progress"
    assert rows[(org_a, "v0")].classification == "inactive"
    assert rows[(org_b, seeded["orphan_version"])].chunk_count == 2
    assert report.points_without_version == 1
    assert report.chunks_deleted == 0 and report.points_deleted == 0
    assert report.exit_code == EXIT_INACTIVE_VERSIONS
    assert await _chunk_versions(db_session) == before
    assert len(qdrant.points) == total_points
    assert qdrant.delete_calls == []
    assert len(qdrant.scroll_calls) > 1, "scroll must paginate"
    assert qdrant.scroll_calls[0]["with_vectors"] is False
    assert "text" not in qdrant.scroll_calls[0]["with_payload"]


@pytest.mark.asyncio
async def test_apply_deletes_eval_versions_except_in_progress_runs(
    db_session: AsyncSession,
) -> None:
    seeded = await _seed(db_session)
    qdrant: FakeQdrantClient = seeded["qdrant"]

    report = await EvalIndexPurgeService(qdrant_client=qdrant, batch_size=2).run(
        db_session, apply=True
    )

    assert report.chunks_deleted == 5
    assert report.points_deleted == 5
    remaining = await _chunk_versions(db_session)
    assert seeded["stale_version"] not in remaining
    assert seeded["orphan_version"] not in remaining
    assert remaining.count(seeded["running_version"]) == 2
    assert remaining.count("v0") == 1
    assert remaining.count(settings.document_index_version) == 3
    left = {p.payload.get("index_version") for p in qdrant.points}
    assert left == {settings.document_index_version, seeded["running_version"], "v0", None}
    assert all(len(call["points_selector"].points) <= 2 for call in qdrant.delete_calls)
    # Non-eval inactive versions are reported, never deleted, and gate the deploy.
    assert [item.index_version for item in report.inactive_versions] == ["v0"]
    assert report.exit_code == EXIT_INACTIVE_VERSIONS


@pytest.mark.asyncio
async def test_organization_scope_and_clean_exit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed(db_session)
    qdrant: FakeQdrantClient = seeded["qdrant"]

    report = await EvalIndexPurgeService(qdrant_client=qdrant).run(
        db_session, apply=True, organization_id=seeded["org_b"]
    )

    assert {item.organization_id for item in report.versions} == {str(seeded["org_b"])}
    assert report.chunks_deleted == 2 and report.points_deleted == 2
    assert report.points_without_version == 0
    assert report.exit_code == EXIT_OK
    # Org A's eval versions are untouched by an org B scoped purge.
    assert seeded["stale_version"] in await _chunk_versions(db_session)

    # Listing the legacy version as active clears the gate for org A, and the
    # service still works without a Qdrant client.
    monkeypatch.setattr(settings, "document_active_index_versions", ["v0"])
    report_a = await EvalIndexPurgeService(qdrant_client=None).run(
        db_session, apply=False, organization_id=seeded["org_a"]
    )
    assert report_a.exit_code == EXIT_OK
    assert all(item.point_count == 0 for item in report_a.versions)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("purge_eval_index_versions", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
async def test_cli_run_prints_counts_only(
    apply: bool,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeded = await _seed(db_session)
    script = _load_script()
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(script, "SessionLocal", factory)
    monkeypatch.setattr(script, "create_qdrant_client", lambda config: seeded["qdrant"])

    argv = ["--batch-size", "10", "--organization-id", str(seeded["org_b"])]
    exit_code = await script.run(argv + (["--apply"] if apply else []))
    output = capsys.readouterr().out

    assert exit_code == EXIT_OK
    assert ("mode=APPLY" if apply else "mode=DRY RUN") in output
    assert f"chunks_deleted={2 if apply else 0} " in output.splitlines()[-1]
    assert "private document text" not in output


def test_cli_main_returns_run_exit_code_and_validates_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _load_script()
    seen: list[list[str]] = []

    async def fake_run(argv: list[str]) -> int:
        seen.append(argv)
        return EXIT_INACTIVE_VERSIONS

    monkeypatch.setattr(script, "run", fake_run)
    assert script.main(["--apply"]) == EXIT_INACTIVE_VERSIONS
    assert seen == [["--apply"]]
    with pytest.raises(SystemExit):
        script._parse_args(["--batch-size", "0"])
    args = script._parse_args([])
    assert (args.apply, args.organization_id, args.batch_size) == (False, None, 256)


@pytest.mark.asyncio
async def test_cli_report_lists_inactive_versions(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeded = await _seed(db_session)
    script = _load_script()
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(script, "SessionLocal", factory)
    monkeypatch.setattr(script, "create_qdrant_client", lambda config: seeded["qdrant"])

    exit_code = await script.run(["--organization-id", str(seeded["org_a"])])
    output = capsys.readouterr().out

    assert exit_code == EXIT_INACTIVE_VERSIONS
    assert "version=v0" in output and "[inactive: hidden from retrieval]" in output
    assert "[eval: run in progress, skipped]" in output
    assert "[eval: eligible for purge]" in output
    assert "private document text" not in output


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_apply_on_postgres_is_scoped_and_skips_running_runs(
    pg_session: AsyncSession,
) -> None:
    seeded = await _seed(pg_session)
    qdrant: FakeQdrantClient = seeded["qdrant"]

    report = await EvalIndexPurgeService(qdrant_client=qdrant, batch_size=2).run(
        pg_session, apply=True, organization_id=seeded["org_a"]
    )

    assert report.chunks_deleted == 3
    assert report.points_deleted == 3
    rows = await pg_session.execute(
        select(DocumentChunk.index_version).where(DocumentChunk.document_id == seeded["doc_a"])
    )
    remaining = sorted(rows.scalars())
    assert seeded["stale_version"] not in remaining
    assert remaining.count(seeded["running_version"]) == 2
    assert remaining.count("v0") == 1
    assert report.exit_code == EXIT_INACTIVE_VERSIONS
