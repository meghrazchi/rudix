"""Keyword search statement: bounded ranking, tenant column, multilingual config (R06-09).

These checks compile the statement for PostgreSQL and drive the service with a counting
fake session; ``tests/test_keyword_multilingual_pg.py`` runs it against a real database.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.domains.chat.services import keyword_search_query as ksq
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievalService


@pytest.fixture(autouse=True)
def _fresh_tenant_cache() -> Iterator[None]:
    ksq.reset_tenant_column_cache()
    yield
    ksq.reset_tenant_column_cache()


def _plan(**overrides: Any) -> ksq.KeywordSearchPlan:
    values: dict[str, Any] = {
        "multilingual": False,
        "tenant_column": False,
        "candidate_limit": 1000,
        "question_config": "english",
    }
    values.update(overrides)
    return ksq.KeywordSearchPlan(**values)


def _compile(plan: ksq.KeywordSearchPlan, **kwargs: Any) -> tuple[str, dict[str, Any]]:
    stmt = ksq.build_keyword_search_statement(
        plan=plan,
        query="annual leave",
        organization_id=kwargs.pop("organization_id", uuid4()),
        document_ids=kwargs.pop("document_ids", None),
        top_k=kwargs.pop("top_k", 5),
        index_version=kwargs.pop("index_version", None),
        index_versions=kwargs.pop("index_versions", None),
    )
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


def _candidate_sql(sql: str) -> str:
    start = sql.index("FROM (SELECT")
    return sql[start : sql.index(") AS keyword_candidates")]


def test_candidate_limit_bounds_the_ranked_subquery() -> None:
    sql, params = _compile(_plan(candidate_limit=1000), top_k=7)
    inner = _candidate_sql(sql)
    assert "LIMIT" in inner and "ts_rank" not in inner and "ORDER BY" not in inner
    assert 1000 in params.values() and 7 in params.values()
    outer = sql[sql.index(") AS keyword_candidates") :]
    assert "ts_rank" in sql[: sql.index("FROM (SELECT")]
    assert "ORDER BY" in outer and "LIMIT" in outer


def test_zero_candidate_limit_ranks_every_match() -> None:
    sql, params = _compile(_plan(candidate_limit=0))
    assert "LIMIT" not in _candidate_sql(sql)
    assert 0 not in params.values()


def test_join_path_scopes_by_the_document_tenant() -> None:
    org_id = uuid4()
    sql, params = _compile(_plan(tenant_column=False), organization_id=org_id)
    inner = _candidate_sql(sql)
    assert "documents.organization_id = " in inner
    assert "document_chunks.organization_id = " not in inner
    assert org_id in params.values()


def test_tenant_column_path_scopes_by_the_chunk_column() -> None:
    org_id = uuid4()
    sql, params = _compile(_plan(tenant_column=True), organization_id=org_id)
    inner = _candidate_sql(sql)
    assert "document_chunks.organization_id = " in inner
    assert "documents.organization_id = " not in inner
    # documents is still joined for status (and filename in the outer query).
    assert "documents.status = " in inner
    assert org_id in params.values()


def test_index_version_filters_stay_in_the_candidate_query() -> None:
    sql, _params = _compile(_plan(), index_version="v1")
    assert "document_chunks.index_version = " in _candidate_sql(sql)
    sql, _params = _compile(_plan(), index_versions=["v1", "v2"], document_ids=[uuid4()])
    inner = _candidate_sql(sql)
    assert "document_chunks.index_version IN" in inner
    assert "document_chunks.document_id IN" in inner


def test_english_column_when_multilingual_is_off() -> None:
    sql, params = _compile(_plan(multilingual=False, question_config="german"))
    assert "text_search_vector" in sql and "fts_vector" not in sql
    assert "english" in params.values() and "german" not in params.values()


def test_question_configuration_when_multilingual_is_on() -> None:
    sql, params = _compile(_plan(multilingual=True, question_config="german"))
    assert "document_chunks.fts_vector @@ plainto_tsquery(CAST(" in sql
    assert "AS REGCONFIG)" in sql
    assert "german" in params.values()
    # Additive: the English column stays a second arm (rows not backfilled yet, unknown
    # languages), and the rank is the better of the two.
    inner = _candidate_sql(sql)
    assert " OR (document_chunks.text_search_vector @@ plainto_tsquery(" in inner
    assert "english" in params.values()
    assert "greatest(ts_rank(document_chunks.fts_vector" in sql


@pytest.mark.parametrize(
    ("language", "query", "expected"),
    [
        ("de", "anything", "german"),
        ("es", "anything", "spanish"),
        ("fr", "anything", "french"),
        ("pt", "anything", "simple"),
        (None, "Wie viele Urlaubstage gibt es?", "german"),
        (None, "How many vacation days?", "english"),
        (None, "", "simple"),
    ],
)
def test_question_configuration(language: str | None, query: str, expected: str) -> None:
    assert ksq.question_fts_config(query, language) == expected


def test_row_check_rejects_other_organisations() -> None:
    org_id = uuid4()
    assert ksq.row_belongs_to({"document_organization_id": org_id}, org_id)
    assert ksq.row_belongs_to(
        {"document_organization_id": org_id, "chunk_organization_id": org_id}, org_id
    )
    assert not ksq.row_belongs_to({"document_organization_id": uuid4()}, org_id)
    assert not ksq.row_belongs_to(
        {"document_organization_id": org_id, "chunk_organization_id": uuid4()}, org_id
    )
    assert not ksq.row_belongs_to({}, org_id)


class _CountingSession:
    """Fake AsyncSession: counts statements; answers the NULL check, then the search."""

    def __init__(self, *, rows: list[dict[str, Any]], null_rows_exist: bool) -> None:
        self.rows = rows
        self.null_rows_exist = null_rows_exist
        self.statements: list[str] = []

    async def execute(self, stmt: Any) -> Any:
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        self.statements.append(sql)
        result = MagicMock()
        result.scalar.return_value = self.null_rows_exist
        result.mappings.return_value.all.return_value = self.rows
        return result


def _row(org_id: UUID, *, chunk_org: UUID | None = None) -> dict[str, Any]:
    return {
        "chunk_id": uuid4(),
        "document_id": uuid4(),
        "text": "annual leave policy",
        "page_number": 1,
        "section_path": None,
        "chunk_level": 0,
        "parent_chunk_id": None,
        "parent_text": None,
        "filename": "leave.txt",
        "rank_score": 0.4,
        "document_organization_id": org_id,
        "chunk_organization_id": chunk_org,
    }


async def _search(session: _CountingSession, org_id: UUID, **kwargs: Any) -> list[UUID]:
    result = await KeywordRetrievalService().search_chunks(
        session=session,  # type: ignore[arg-type]
        query="annual leave",
        organization_id=org_id,
        document_ids=None,
        top_k=5,
        **kwargs,
    )
    return [candidate.document_id for candidate in result.candidates]


async def test_auto_mode_checks_once_then_keeps_one_statement_per_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "keyword_search_tenant_column", "auto")
    org_id = uuid4()
    session = _CountingSession(rows=[_row(org_id)], null_rows_exist=False)

    await _search(session, org_id)
    assert len(session.statements) == 2  # the cached backfill check, then the search
    assert "organization_id IS NULL" in session.statements[0]
    assert "document_chunks.organization_id = " in _candidate_sql(session.statements[1])

    await _search(session, org_id)
    await _search(session, org_id)
    assert len(session.statements) == 4  # one statement per search afterwards


async def test_auto_mode_uses_the_join_while_rows_are_unbackfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "keyword_search_tenant_column", "auto")
    org_id = uuid4()
    session = _CountingSession(rows=[_row(org_id)], null_rows_exist=True)
    await _search(session, org_id)
    assert "documents.organization_id = " in _candidate_sql(session.statements[-1])


@pytest.mark.parametrize(("mode", "column"), [("on", True), ("off", False)])
async def test_explicit_modes_issue_no_check(
    monkeypatch: pytest.MonkeyPatch, mode: str, column: bool
) -> None:
    monkeypatch.setattr(settings, "keyword_search_tenant_column", mode)
    org_id = uuid4()
    session = _CountingSession(rows=[_row(org_id)], null_rows_exist=True)
    assert len(await _search(session, org_id)) == 1
    assert len(session.statements) == 1
    inner = _candidate_sql(session.statements[0])
    assert ("document_chunks.organization_id = " in inner) is column


async def test_service_reads_multilingual_and_limit_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "keyword_search_tenant_column", "off")
    monkeypatch.setattr(settings, "keyword_search_multilingual", True)
    monkeypatch.setattr(settings, "keyword_search_candidate_limit", 37)
    org_id = uuid4()
    session = _CountingSession(rows=[_row(org_id)], null_rows_exist=False)
    await _search(session, org_id, query_language="fr")
    sql = session.statements[0]
    assert "fts_vector @@" in sql and "LIMIT" in _candidate_sql(sql)


@pytest.mark.isolation
async def test_service_drops_rows_of_another_organisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "keyword_search_tenant_column", "on")
    org_id = uuid4()
    other = uuid4()
    rows = [
        _row(org_id),
        _row(other),
        _row(org_id, chunk_org=other),
        _row(org_id, chunk_org=org_id),
    ]
    session = _CountingSession(rows=rows, null_rows_exist=False)
    found = await _search(session, org_id)
    assert found == [rows[0]["document_id"], rows[3]["document_id"]]
