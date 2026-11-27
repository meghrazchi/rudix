"""Multilingual keyword search on PostgreSQL (R06-09).

Extends ``tests/test_keyword_retrieval_fts_pg.py``: German, Spanish and French chunks are
written the way the chunk stage writes them (``organization_id``, ``fts_config``,
``fts_vector``) and searched with ``KEYWORD_SEARCH_MULTILINGUAL`` off (the English
generated column) and on (the question's configuration), over both tenant paths.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  # register all mappers
from app.core.config import settings
from app.domains.chat.services import keyword_search_query as ksq
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievalService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.services.fts_config import chunk_search_fields
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.user import User
from app.workers import chunk_backfill_tasks as backfill_module

pytestmark = pytest.mark.requires_postgres

_service = KeywordRetrievalService()
_repository = DocumentRepository()

# (document language, chunk text, question in the same language). Each question matches its
# chunk under the language's own stemming and stop words, and not under English rules.
FIXTURES: tuple[tuple[str, str, str], ...] = (
    (
        "de",
        "Die Mitarbeiter erhalten jedes Jahr dreißig Urlaubstage.",
        "Welche Urlaubstage erhalten die Mitarbeiter?",
    ),
    (
        "es",
        "Los empleados recibirán veinte días de vacaciones pagadas.",
        "¿Reciben vacaciones los empleados?",
    ),
    (
        "fr",
        "Les salariés bénéficient de vingt-cinq jours de congés payés.",
        "Le congé du salarié",
    ),
)


@pytest.fixture(autouse=True)
def _keyword_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    ksq.reset_tenant_column_cache()
    monkeypatch.setattr(settings, "keyword_search_tenant_column", "off")
    monkeypatch.setattr(settings, "keyword_search_multilingual", False)
    monkeypatch.setattr(settings, "keyword_search_candidate_limit", 1000)
    yield
    ksq.reset_tenant_column_cache()


async def _org(session: AsyncSession) -> tuple[Organization, User]:
    suffix = uuid4().hex
    org = Organization(name=f"ML {suffix}", slug=f"ml-{suffix}")
    session.add(org)
    await session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"ml-{suffix}",
        email=f"ml-{suffix}@example.com",
        display_name="ML",
    )
    session.add(user)
    await session.flush()
    return org, user


async def _document(
    session: AsyncSession, org: Organization, user: User, *, language: str | None
) -> Document:
    document = Document(
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename=f"ml-{uuid4().hex[:8]}.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
        status=DocumentStatus.indexed.value,
        language=language,
    )
    session.add(document)
    await session.flush()
    return document


async def _chunk(
    session: AsyncSession, document: Document, text_: str, *, index: int = 0
) -> DocumentChunk:
    """Write a chunk the way the 0.6.0 chunk stage does."""
    return await _repository.create_document_chunk(
        session,
        document_id=document.id,
        chunk_index=index,
        page_number=1,
        text=text_,
        token_count=len(text_.split()),
        embedding_model="test-embedding",
        language=document.language,
        **chunk_search_fields(document),
    )


async def _legacy_chunk(session: AsyncSession, document: Document, text_: str) -> DocumentChunk:
    """A pre-0.6.0 row: no tenant column, no fts_vector."""
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=99,
        page_number=1,
        text=text_,
        token_count=len(text_.split()),
        embedding_model="test-embedding",
    )
    session.add(chunk)
    await session.flush()
    return chunk


async def _search(
    session: AsyncSession, query: str, org_id: UUID, *, language: str | None = None, **kw: Any
) -> list[UUID]:
    result = await _service.search_chunks(
        session=session,
        query=query,
        organization_id=org_id,
        document_ids=kw.pop("document_ids", None),
        top_k=kw.pop("top_k", 10),
        index_versions=kw.pop("index_versions", None),
        query_language=language,
    )
    return [candidate.chunk_id for candidate in result.candidates]


async def _seed_fixtures(session: AsyncSession) -> tuple[Organization, dict[str, UUID]]:
    org, user = await _org(session)
    chunk_ids: dict[str, UUID] = {}
    for language, sentence, _question in FIXTURES:
        document = await _document(session, org, user, language=language)
        chunk_ids[language] = (await _chunk(session, document, sentence)).id
    return org, chunk_ids


async def test_multilingual_recall_improves_for_german_spanish_and_french(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, chunk_ids = await _seed_fixtures(pg_session)

    # English stemming (the default, multilingual off) finds none of them.
    english_hits = {
        language: await _search(pg_session, question, org.id, language=language)
        for language, _sentence, question in FIXTURES
    }
    assert english_hits == {"de": [], "es": [], "fr": []}

    monkeypatch.setattr(settings, "keyword_search_multilingual", True)
    for language, _sentence, question in FIXTURES:
        # With the pipeline's detected language and with detection from the text.
        assert await _search(pg_session, question, org.id, language=language) == [
            chunk_ids[language]
        ]
        assert await _search(pg_session, question, org.id) == [chunk_ids[language]]


async def test_multilingual_keeps_english_and_unbackfilled_rows(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "keyword_search_multilingual", True)
    org, user = await _org(pg_session)
    english = await _chunk(
        pg_session,
        await _document(pg_session, org, user, language="en"),
        "Employees request reimbursement for travelling expenses.",
    )
    legacy = await _legacy_chunk(
        pg_session,
        await _document(pg_session, org, user, language="en"),
        "Reimbursements of travel expenses need receipts.",
    )
    unknown_language = await _chunk(
        pg_session,
        await _document(pg_session, org, user, language=None),
        "Travel expenses are reimbursed monthly.",
    )
    assert unknown_language.fts_config == "simple"
    found = await _search(pg_session, "travel expense reimbursement", org.id, language="en")
    # Nothing the English column found before is lost with multilingual on.
    assert set(found) == {english.id, legacy.id, unknown_language.id}


async def test_candidate_limit_bounds_the_ranked_rows(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, user = await _org(pg_session)
    document = await _document(pg_session, org, user, language="en")
    token = f"zyxbound{uuid4().hex[:8]}"
    for index in range(5):
        await _chunk(pg_session, document, f"{token} policy number {index}", index=index)

    assert len(await _search(pg_session, token, org.id)) == 5
    monkeypatch.setattr(settings, "keyword_search_candidate_limit", 2)
    assert len(await _search(pg_session, token, org.id)) == 2
    monkeypatch.setattr(settings, "keyword_search_candidate_limit", 0)
    assert len(await _search(pg_session, token, org.id)) == 5


async def test_index_version_filter_applies_on_both_paths(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, chunk_ids = await _seed_fixtures(pg_session)
    monkeypatch.setattr(settings, "keyword_search_multilingual", True)
    question = FIXTURES[0][2]
    for mode in ("off", "on"):
        monkeypatch.setattr(settings, "keyword_search_tenant_column", mode)
        assert await _search(pg_session, question, org.id, index_versions=["v1"]) == [
            chunk_ids["de"]
        ]
        assert await _search(pg_session, question, org.id, index_versions=["eval-x"]) == []


@pytest.mark.isolation
@pytest.mark.parametrize("mode", ["off", "on"])
@pytest.mark.parametrize("multilingual", [False, True])
async def test_other_organisations_are_never_returned(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, mode: str, multilingual: bool
) -> None:
    monkeypatch.setattr(settings, "keyword_search_tenant_column", mode)
    monkeypatch.setattr(settings, "keyword_search_multilingual", multilingual)
    token = f"zyxiso{uuid4().hex[:8]}"
    org_a, user_a = await _org(pg_session)
    org_b, user_b = await _org(pg_session)
    doc_a = await _document(pg_session, org_a, user_a, language="de")
    doc_b = await _document(pg_session, org_b, user_b, language="de")
    chunk_a = await _chunk(pg_session, doc_a, f"{token} Urlaubstage der Mitarbeiter")
    chunk_b = await _chunk(pg_session, doc_b, f"{token} Urlaubstage der Mitarbeiter")

    assert await _search(pg_session, token, org_a.id, language="de") == [chunk_a.id]
    assert await _search(pg_session, token, org_b.id, language="de") == [chunk_b.id]
    # Naming another organisation's document does not leak it either.
    assert await _search(pg_session, token, org_a.id, language="de", document_ids=[doc_b.id]) == []


@pytest.mark.isolation
async def test_tenant_column_path_ignores_a_chunk_whose_column_disagrees(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A chunk row claiming org B under org A's document is never returned to either: the
    # column path filters on the chunk, the per-row check compares it with the document.
    token = f"zyxmix{uuid4().hex[:8]}"
    org_a, user_a = await _org(pg_session)
    org_b, _user_b = await _org(pg_session)
    doc_a = await _document(pg_session, org_a, user_a, language="en")
    chunk = await _chunk(pg_session, doc_a, f"{token} mismatched tenant")
    await pg_session.execute(
        text("UPDATE document_chunks SET organization_id = :org WHERE id = :id"),
        {"org": org_b.id, "id": chunk.id},
    )
    for mode in ("on", "off"):
        monkeypatch.setattr(settings, "keyword_search_tenant_column", mode)
        assert await _search(pg_session, token, org_a.id) == []
        assert await _search(pg_session, token, org_b.id) == []


async def test_auto_mode_follows_the_backfill(pg_session: AsyncSession) -> None:
    settings_mode = settings.keyword_search_tenant_column
    try:
        settings.keyword_search_tenant_column = "auto"
        org, user = await _org(pg_session)
        document = await _document(pg_session, org, user, language="en")
        await _legacy_chunk(pg_session, document, "legacy row")
        assert await ksq.use_tenant_column(pg_session) is False

        @asynccontextmanager
        async def _scope() -> AsyncIterator[AsyncSession]:
            await pg_session.commit()
            yield pg_session

        await backfill_module.backfill(session_scope=_scope)
        assert await ksq.use_tenant_column(pg_session) is False  # cached for the process
        ksq.reset_tenant_column_cache()
        assert await ksq.use_tenant_column(pg_session) is True
    finally:
        settings.keyword_search_tenant_column = settings_mode


@pytest.mark.parametrize("mode", ["off", "on"])
async def test_one_statement_per_search(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(settings, "keyword_search_tenant_column", mode)
    monkeypatch.setattr(settings, "keyword_search_multilingual", True)
    org, _chunk_ids = await _seed_fixtures(pg_session)
    statements: list[str] = []
    connection = await pg_session.connection()

    def _count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(connection.sync_connection, "before_cursor_execute", _count)
    try:
        await _search(pg_session, FIXTURES[1][2], org.id, language="es")
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", _count)
    assert len(statements) == 1


@pytest.mark.parametrize("multilingual", [False, True])
async def test_explain_uses_the_0_6_0_indexes(pg_session: AsyncSession, multilingual: bool) -> None:
    # The tenant-column path reaches chunks through idx_chunks_org_document (or the GIN
    # index on fts_vector) instead of joining documents first.
    org, _chunk_ids = await _seed_fixtures(pg_session)
    # Another tenant with many indexed documents, so reaching chunks through documents is
    # no longer the cheap plan (the tenant path has no organisation filter on documents).
    other, other_user = await _org(pg_session)
    await pg_session.execute(
        insert(Document),
        [
            {
                "organization_id": other.id,
                "uploaded_by_user_id": other_user.id,
                "filename": f"bulk-{n}.txt",
                "file_type": "txt",
                "storage_bucket": "documents",
                "storage_object_key": f"bulk/{other.id}/{n}.txt",
                "status": DocumentStatus.indexed.value,
                "language": "de",
            }
            for n in range(2000)
        ],
    )
    await pg_session.execute(
        text(
            "INSERT INTO document_chunks (id, document_id, chunk_index, text, token_count, "
            "embedding_model, index_version, chunk_type, organization_id, fts_config, "
            "fts_vector, created_at, updated_at) "
            "SELECT gen_random_uuid(), d.id, 0, 'Urlaubstage der Mitarbeiter ' || d.filename, "
            "4, 'test-embedding', 'v1', 'text', d.organization_id, 'german', "
            "to_tsvector('german', 'Urlaubstage der Mitarbeiter ' || d.filename), now(), now() "
            "FROM documents d WHERE d.organization_id = :org"
        ),
        {"org": other.id},
    )
    await pg_session.execute(text("ANALYZE documents"))
    await pg_session.execute(text("ANALYZE document_chunks"))
    # A tiny test table always prefers a sequential scan; disable it to see index choice.
    await pg_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = ksq.KeywordSearchPlan(
        multilingual=multilingual,
        tenant_column=True,
        candidate_limit=1000,
        question_config="german",
    )
    stmt = ksq.build_keyword_search_statement(
        plan=plan,
        query=FIXTURES[0][2],
        organization_id=org.id,
        document_ids=None,
        top_k=10,
        index_version=None,
        index_versions=["v1"],
    )
    connection = await pg_session.connection()
    compiled = stmt.compile(dialect=connection.dialect, compile_kwargs={"render_postcompile": True})
    positional = [compiled.params[name] for name in compiled.positiontup or []]
    raw = await connection.get_raw_connection()
    records = await raw.driver_connection.fetch(  # type: ignore[union-attr]
        f"EXPLAIN {compiled}", *positional
    )
    explain = "\n".join(record[0] for record in records)
    assert "idx_chunks_org_document" in explain or "idx_chunks_fts_vector" in explain, explain
    assert "idx_documents_org" not in explain, explain
