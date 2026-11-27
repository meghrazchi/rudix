"""Chunk tenant column: writer, backfill task, operator script and NOT NULL SQL (R06-09)."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # noqa: F401  (registers every model)
from app.core.config import settings
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.services import fts_config
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.user import User
from app.workers import celery_app as celery_module
from app.workers import chunk_backfill_tasks as backfill_module
from app.workers.base_task import TransientTaskError
from app.workers.ingestion.stages import chunk as chunk_stage

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEPLOY_SQL_DIR = BACKEND_DIR.parent / "deploy" / "sql"


def _load_script(name: str) -> ModuleType:
    path = BACKEND_DIR / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"script_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Language mapping and the chunk writer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "english"),
        ("de", "german"),
        ("de-AT", "german"),
        ("ES", "spanish"),
        ("fr_FR", "french"),
        (" fr ", "french"),
        ("it", "simple"),
        ("", "simple"),
        (None, "simple"),
    ],
)
def test_fts_config_for_language(language: str | None, expected: str) -> None:
    assert fts_config.fts_config_for_language(language) == expected


def test_fts_vector_expression_rejects_unknown_configuration() -> None:
    with pytest.raises(ValueError, match="unsupported text search configuration"):
        fts_config.fts_vector_expression("english; DROP TABLE x", "t")
    expression = fts_config.fts_vector_expression("german", "t")
    assert "to_tsvector" in str(expression)


def test_case_sql_covers_every_language() -> None:
    sql = fts_config.fts_config_case_sql("d.language")
    for language, config in fts_config.FTS_CONFIG_BY_LANGUAGE.items():
        assert f"WHEN '{language}' THEN '{config}'" in sql
    assert sql.endswith("ELSE 'simple' END")


def test_chunk_row_values_carry_tenant_and_configuration() -> None:
    org_id = uuid4()
    document = SimpleNamespace(organization_id=org_id, language="de")
    ctx = SimpleNamespace(
        deps=SimpleNamespace(qdrant_service=SimpleNamespace(build_point_id=lambda **_: "p-1"))
    )
    chunk = SimpleNamespace(
        document_id=uuid4(),
        page_number=2,
        chunk_index=0,
        text="Die Urlaubstage werden beantragt.",
        token_count=5,
        embedding_model="m",
        index_version="v1",
        section_path=None,
        chunk_level=None,
        child_count=None,
    )
    values = chunk_stage._chunk_row_values(
        ctx,  # type: ignore[arg-type]
        chunk,
        document=document,
        is_hierarchical=False,
    )
    assert values["organization_id"] == org_id
    assert values["fts_config"] == "german"
    assert values["qdrant_point_id"] == "p-1"
    assert values["section_path"] == "page:2"


async def test_repository_writes_tenant_but_no_vector_on_sqlite(db_session: AsyncSession) -> None:
    org, user = await _seed_org(db_session)
    document = await _seed_document(db_session, org, user, language="fr")
    chunk = await DocumentRepository().create_document_chunk(
        db_session,
        document_id=document.id,
        chunk_index=0,
        text="Les congés annuels",
        token_count=3,
        embedding_model="m",
        organization_id=org.id,
        fts_config="french",
    )
    assert chunk.organization_id == org.id
    assert chunk.fts_config == "french"
    row = (
        await db_session.execute(
            select(DocumentChunk.fts_vector).where(DocumentChunk.id == chunk.id)
        )
    ).scalar_one()
    assert row is None  # SQLite has no to_tsvector(regconfig); PostgreSQL writes it


# ---------------------------------------------------------------------------
# Task wiring and the task body (no database)
# ---------------------------------------------------------------------------


def test_backfill_task_is_registered_and_routed_to_the_reindex_queue() -> None:
    assert "app.workers.chunk_backfill_tasks" in celery_module.INCLUDE
    route = celery_module.TASK_ROUTES[backfill_module.TASK_NAME]
    assert route["queue"] == settings.celery_queue_documents_reindex
    assert backfill_module.backfill_chunk_tenant.name == "documents.chunks.backfill_tenant"


def test_backfill_task_re_enqueues_itself_until_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = uuid4()
    enqueued: list[dict[str, Any]] = []

    async def _partial(**kwargs: Any) -> backfill_module.BackfillProgress:
        assert kwargs["cursor"] is None and kwargs["max_batches"] == 3
        return backfill_module.BackfillProgress(cursor=cursor, batches=3, updated=7)

    monkeypatch.setattr(backfill_module, "backfill", _partial)
    monkeypatch.setattr(
        backfill_module.backfill_chunk_tenant,
        "apply_async",
        lambda **kwargs: enqueued.append(kwargs),
    )
    result = backfill_module.backfill_chunk_tenant(max_batches=3, total_updated=5)
    assert result["total_updated"] == 12 and result["finished"] is False
    assert enqueued == [{"kwargs": {"cursor": str(cursor), "max_batches": 3, "total_updated": 12}}]

    async def _finished(**kwargs: Any) -> backfill_module.BackfillProgress:
        assert kwargs["cursor"] == cursor
        return backfill_module.BackfillProgress(cursor=cursor, updated=0, finished=True)

    monkeypatch.setattr(backfill_module, "backfill", _finished)
    enqueued.clear()
    result = backfill_module.backfill_chunk_tenant(cursor=str(cursor))
    assert result["finished"] is True and enqueued == []


def test_backfill_task_retries_the_same_cursor_on_a_database_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _locked(**_: Any) -> backfill_module.BackfillProgress:
        raise DBAPIError("UPDATE", {}, RuntimeError("lock timeout"))

    monkeypatch.setattr(backfill_module, "backfill", _locked)
    with pytest.raises(TransientTaskError):
        backfill_module.backfill_chunk_tenant.run(cursor=str(uuid4()))


# ---------------------------------------------------------------------------
# Operator NOT NULL SQL
# ---------------------------------------------------------------------------


def test_committed_not_null_sql_matches_the_renderer(tmp_path: Path) -> None:
    render = _load_script("render_chunk_not_null_sql")
    for name, content in render.rendered_files().items():
        committed = (DEPLOY_SQL_DIR / name).read_text(encoding="utf-8")
        assert committed == content, f"deploy/sql/{name} is stale; re-render it"
    assert render.main(["--check"]) == 0
    assert render.main(["--check"], directory=tmp_path) == 1
    assert render.main([], directory=tmp_path) == 0
    assert render.main(["--check"], directory=tmp_path) == 0


def test_not_null_sql_orders_the_safe_steps() -> None:
    render = _load_script("render_chunk_not_null_sql")
    apply_sql = render.render_apply_sql()
    order = [
        "organization_id IS NULL) THEN",
        "CHECK (organization_id IS NOT NULL) NOT VALID",
        "VALIDATE CONSTRAINT chk_chunks_org_not_null",
        "ALTER COLUMN organization_id SET NOT NULL",
        "CREATE POLICY tenant_isolation_policy ON document_chunks",
    ]
    positions = [apply_sql.index(fragment) for fragment in order]
    assert positions == sorted(positions)
    assert "app.rls_mode" in apply_sql
    revert_sql = render.render_revert_sql()
    assert "DROP NOT NULL" in revert_sql and "DISABLE ROW LEVEL SECURITY" in revert_sql


# ---------------------------------------------------------------------------
# PostgreSQL: writer vector, batches, idempotency, resume, locks, operator SQL
# ---------------------------------------------------------------------------


async def _seed_org(session: AsyncSession) -> tuple[Organization, User]:
    suffix = uuid4().hex
    org = Organization(name=f"Backfill {suffix}", slug=f"backfill-{suffix}")
    session.add(org)
    await session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"backfill-{suffix}",
        email=f"backfill-{suffix}@example.com",
        display_name="Backfill",
    )
    session.add(user)
    await session.flush()
    return org, user


async def _seed_document(
    session: AsyncSession, org: Organization, user: User, *, language: str | None
) -> Document:
    document = Document(
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename=f"bf-{uuid4().hex[:8]}.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
        status=DocumentStatus.indexed.value,
        language=language,
    )
    session.add(document)
    await session.flush()
    return document


async def _legacy_chunk(session: AsyncSession, document: Document, text_: str, index: int) -> UUID:
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=index,
        text=text_,
        token_count=len(text_.split()),
        embedding_model="m",
    )
    session.add(chunk)
    await session.flush()
    return chunk.id


def _scope_for(session: AsyncSession) -> Any:
    # Each batch opens its own transaction; the rolled-back test session releases its current
    # savepoint first (everything is still rolled back at teardown).
    @asynccontextmanager
    async def _scope() -> AsyncIterator[AsyncSession]:
        await session.commit()
        yield session

    return _scope


async def _seed_legacy_rows(session: AsyncSession) -> dict[UUID, tuple[UUID, str]]:
    """Five pre-0.6.0 chunks over two organisations; returns id -> (org, config)."""
    org_a, user_a = await _seed_org(session)
    org_b, user_b = await _seed_org(session)
    doc_de = await _seed_document(session, org_a, user_a, language="de")
    doc_none = await _seed_document(session, org_a, user_a, language=None)
    doc_es = await _seed_document(session, org_b, user_b, language="es")
    expected: dict[UUID, tuple[UUID, str]] = {}
    for index, sentence in enumerate(["Die Urlaubstage", "Die Reisekosten"]):
        expected[await _legacy_chunk(session, doc_de, sentence, index)] = (org_a.id, "german")
    expected[await _legacy_chunk(session, doc_none, "untagged text", 0)] = (org_a.id, "simple")
    for index, sentence in enumerate(["Las vacaciones", "Los viajes"]):
        expected[await _legacy_chunk(session, doc_es, sentence, index)] = (org_b.id, "spanish")
    return expected


@pytest.mark.requires_postgres
async def test_pg_writer_stores_a_language_aware_vector(pg_session: AsyncSession) -> None:
    org, user = await _seed_org(pg_session)
    document = await _seed_document(pg_session, org, user, language="de")
    chunk = await DocumentRepository().create_document_chunk(
        pg_session,
        document_id=document.id,
        chunk_index=0,
        text="Die Mitarbeiter beantragen ihre Urlaubstage",
        token_count=5,
        embedding_model="m",
        **fts_config.chunk_search_fields(document),
    )
    vector = (
        await pg_session.execute(
            select(DocumentChunk.fts_vector).where(DocumentChunk.id == chunk.id)
        )
    ).scalar_one()
    assert chunk.organization_id == org.id and chunk.fts_config == "german"
    # German stemming and stop words: "Die" is dropped, "Mitarbeiter" is stemmed.
    assert "'mitarbeit'" in str(vector)
    assert "'die'" not in str(vector)


@pytest.mark.requires_postgres
async def test_pg_backfill_fills_batches_and_is_idempotent(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chunk_backfill_lock_timeout_ms", 1234)
    monkeypatch.setattr(settings, "chunk_backfill_statement_timeout_ms", 4321)
    expected = await _seed_legacy_rows(pg_session)
    scope = _scope_for(pg_session)
    seen: list[int] = []

    progress = await backfill_module.backfill(
        batch_size=2, session_scope=scope, on_batch=lambda b, _p: seen.append(b.scanned)
    )

    assert progress.finished is True
    assert progress.updated >= len(expected)
    assert all(size <= 2 for size in seen)
    rows = (
        await pg_session.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.organization_id,
                DocumentChunk.fts_config,
                DocumentChunk.fts_vector,
            ).where(DocumentChunk.id.in_(list(expected)))
        )
    ).all()
    assert {row.id: (row.organization_id, row.fts_config) for row in rows} == expected
    assert all(row.fts_vector is not None for row in rows)
    assert await backfill_module.count_remaining(scope) == 0
    # The per-transaction timeouts were set (SET LOCAL lasts until the outer rollback).
    lock_timeout = (await pg_session.execute(text("SHOW lock_timeout"))).scalar_one()
    assert lock_timeout == "1234ms"
    statement_timeout = (await pg_session.execute(text("SHOW statement_timeout"))).scalar_one()
    assert statement_timeout == "4321ms"

    rerun = await backfill_module.backfill(batch_size=2, session_scope=scope)
    assert rerun.updated == 0 and rerun.batches == 0 and rerun.finished is True


@pytest.mark.requires_postgres
async def test_pg_backfill_resumes_from_its_cursor(pg_session: AsyncSession) -> None:
    expected = await _seed_legacy_rows(pg_session)
    scope = _scope_for(pg_session)

    first = await backfill_module.backfill(batch_size=1, max_batches=2, session_scope=scope)
    assert first.batches == 2 and first.finished is False and first.cursor is not None
    done = (
        await pg_session.execute(
            select(DocumentChunk.id).where(
                DocumentChunk.id.in_(list(expected)), DocumentChunk.organization_id.is_not(None)
            )
        )
    ).scalars()
    assert all(chunk_id <= first.cursor for chunk_id in done)

    rest = await backfill_module.backfill(cursor=first.cursor, session_scope=scope)
    assert rest.finished is True
    assert await backfill_module.count_remaining(scope) == 0


@pytest.mark.requires_postgres
async def test_pg_operator_script_dry_run_and_apply(pg_session: AsyncSession) -> None:
    script = _load_script("backfill_chunk_tenant")
    expected = await _seed_legacy_rows(pg_session)
    scope = _scope_for(pg_session)

    out = io.StringIO()
    assert await script.run(["--dry-run"], session_scope=scope, out=out) == 0
    assert "mode=DRY RUN" in out.getvalue()
    assert await backfill_module.count_remaining(scope) >= len(expected)

    out = io.StringIO()
    assert await script.run(["--batch-size", "2"], session_scope=scope, out=out) == 0
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("remaining=") and "mode=APPLY" in lines[0]
    assert any(line.startswith("batch=1 ") for line in lines)
    assert lines[-1].startswith("done finished=True") and "remaining=0" in lines[-1]

    out = io.StringIO()
    assert await script.run([], session_scope=scope, out=out) == 0
    assert out.getvalue().strip() == "remaining=0 mode=APPLY"


def test_operator_script_rejects_bad_arguments() -> None:
    script = _load_script("backfill_chunk_tenant")
    with pytest.raises(SystemExit):
        script._parse_args(["--batch-size", "0"])
    with pytest.raises(SystemExit):
        script._parse_args(["--max-batches", "0"])


@pytest.mark.requires_postgres
async def test_pg_backfill_batch_fails_fast_on_a_locked_row(
    pg_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A writer holds a lock on a legacy row; the batch gives up after lock_timeout instead of
    # queueing behind it, and the task would retry the same cursor.
    monkeypatch.setattr(settings, "chunk_backfill_lock_timeout_ms", 200)
    async with pg_session_factory() as seed:
        org, user = await _seed_org(seed)
        document = await _seed_document(seed, org, user, language="en")
        chunk_id = await _legacy_chunk(seed, document, "locked legacy row", 0)
        await seed.commit()
    try:
        async with pg_session_factory() as holder:
            await holder.execute(
                text("SELECT id FROM document_chunks WHERE id = :id FOR UPDATE"),
                {"id": chunk_id},
            )

            @asynccontextmanager
            async def _scope() -> AsyncIterator[AsyncSession]:
                async with pg_session_factory() as session:
                    yield session

            with pytest.raises(DBAPIError):
                await asyncio.wait_for(
                    backfill_module.run_backfill_batch(
                        cursor=None, batch_size=100_000, session_scope=_scope
                    ),
                    timeout=10,
                )
            await holder.rollback()
    finally:
        async with pg_session_factory() as cleanup:
            await cleanup.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk_id))
            await cleanup.execute(delete(Document).where(Document.id == document.id))
            await cleanup.execute(delete(User).where(User.id == user.id))
            await cleanup.execute(delete(Organization).where(Organization.id == org.id))
            await cleanup.commit()


async def _run_sql_file(session: AsyncSession, name: str) -> None:
    """Run an operator file inside the test transaction (BEGIN/COMMIT lines dropped)."""
    sql = (DEPLOY_SQL_DIR / name).read_text(encoding="utf-8")
    body = "\n".join(line for line in sql.splitlines() if line not in {"BEGIN;", "COMMIT;"})
    connection = await session.connection()
    raw = await connection.get_raw_connection()
    await raw.driver_connection.execute(body)  # type: ignore[union-attr]


async def _column_nullable(session: AsyncSession) -> bool:
    value = (
        await session.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'document_chunks' AND column_name = 'organization_id'"
            )
        )
    ).scalar_one()
    return value == "YES"


async def _policy_count(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                text("SELECT count(*) FROM pg_policies WHERE tablename = 'document_chunks'")
            )
        ).scalar_one()
    )


@pytest.mark.requires_postgres
async def test_pg_not_null_sql_refuses_then_applies_and_reverts(pg_session: AsyncSession) -> None:
    await _seed_legacy_rows(pg_session)
    await pg_session.execute(text("SAVEPOINT before_refusal"))
    with pytest.raises(Exception, match="organization_id NULL rows remain"):
        await _run_sql_file(pg_session, "document_chunks_not_null.sql")
    await pg_session.execute(text("ROLLBACK TO SAVEPOINT before_refusal"))
    assert await _column_nullable(pg_session) is True

    await backfill_module.backfill(session_scope=_scope_for(pg_session))
    await _run_sql_file(pg_session, "document_chunks_not_null.sql")
    assert await _column_nullable(pg_session) is False
    assert await _policy_count(pg_session) == 1
    # Rerun-safe: the check already exists, NOT NULL is already set.
    await _run_sql_file(pg_session, "document_chunks_not_null.sql")

    await _run_sql_file(pg_session, "document_chunks_not_null_revert.sql")
    assert await _column_nullable(pg_session) is True
    assert await _policy_count(pg_session) == 0
