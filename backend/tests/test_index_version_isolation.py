"""R02-05: production retrieval only serves active index versions.

Evaluation chunking comparisons re-ingest documents under ``eval-<run hex10>-<n>`` into
the same Qdrant collection and ``document_chunks`` table. These tests prove eval chunks
never reach chat, agent, or keyword retrieval.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue
from sqlalchemy.ext.asyncio import AsyncSession

# Env must be set before any app import.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app",
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

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.clients import qdrant_client as qdrant_module
from app.core.config import AuthProvider, Settings, settings
from app.db.session import get_db_session
from app.domains.agents.services.document_intelligence_tools import (
    DocumentIntelligenceToolService,
)
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievalService
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.services.qdrant_filters import build_organization_filter
from app.interfaces.http import chat as chat_api
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

pytestmark = [pytest.mark.isolation, pytest.mark.both_dialects]

EVAL_VERSION = "eval-abc1234567-1"
CHAT_PY = Path(__file__).resolve().parents[1] / "app" / "interfaces" / "http" / "chat.py"

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeQdrantResult:
    score: float
    payload: dict[str, object]


def _condition_matches(condition: FieldCondition, payload: dict[str, object]) -> bool:
    value = payload.get(condition.key)
    match = condition.match
    if isinstance(match, MatchValue):
        return value == match.value
    if isinstance(match, MatchAny):
        return value in list(match.any)
    raise AssertionError(f"unsupported match type: {type(match).__name__}")


class FilterAwareFakeQdrantClient:
    """Evaluates ``query_filter.must`` FieldConditions against stored payloads."""

    def __init__(self, results: list[FakeQdrantResult]) -> None:
        self._results = results
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> list[FakeQdrantResult]:
        self.calls.append(kwargs)
        query_filter = kwargs.get("query_filter")
        assert isinstance(query_filter, Filter)
        must = [c for c in (query_filter.must or []) if isinstance(c, FieldCondition)]
        return [r for r in self._results if all(_condition_matches(c, r.payload) for c in must)]


class FakeEmbeddingsEndpoint:
    def __init__(self, vector_size: int) -> None:
        self._vector_size = vector_size

    async def create(self, *, model: str, input: list[str]) -> object:
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.01] * self._vector_size)],
            usage=SimpleNamespace(prompt_tokens=5),
        )


class FakeChatCompletionsEndpoint:
    def __init__(self, *, answer: str) -> None:
        self._answer = answer
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._answer))],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
            model=settings.openai_llm_model,
        )


class FakeOpenAIClient:
    def __init__(self, *, answer: str) -> None:
        self.embeddings = FakeEmbeddingsEndpoint(settings.qdrant_vector_size)
        self.chat = SimpleNamespace(completions=FakeChatCompletionsEndpoint(answer=answer))


# ---------------------------------------------------------------------------
# Fixtures and seed helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def isolation_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_embeddings", True)
    monkeypatch.setattr(settings, "feature_enable_llm", True)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
    qdrant_module.qdrant_client = None
    chat_api._openai_client = None


async def _make_org_and_user(db_session: AsyncSession, *, slug_prefix: str) -> tuple[Any, Any]:
    org = Organization(name=f"Org {slug_prefix}", slug=f"{slug_prefix}-{uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"{slug_prefix}-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=OrganizationRole.member.value
        )
    )
    await db_session.commit()
    return org, user


async def _make_document_with_versions(
    db_session: AsyncSession, *, org: Any, user: Any, text: str
) -> tuple[Any, Any, Any]:
    """One indexed document with the same chunk under production and eval versions."""
    repo = DocumentRepository()
    doc = await repo.create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="policy.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"test/policy-{uuid4()}.pdf",
        status="indexed",
    )
    chunks = []
    for version in (settings.document_index_version, EVAL_VERSION):
        chunks.append(
            await repo.create_document_chunk(
                db_session,
                document_id=doc.id,
                page_number=1,
                chunk_index=0,
                text=text,
                token_count=20,
                embedding_model=settings.openai_embedding_model,
                index_version=version,
                qdrant_point_id=f"{doc.id}:{version}:0",
            )
        )
    await db_session.commit()
    return doc, chunks[0], chunks[1]


def _payload(*, org_id: UUID, doc_id: UUID, chunk_id: UUID, version: str, text: str) -> dict:
    return {
        "organization_id": str(org_id),
        "document_id": str(doc_id),
        "chunk_id": str(chunk_id),
        "filename": "policy.pdf",
        "page_number": 1,
        "text": text,
        "index_version": version,
    }


# ---------------------------------------------------------------------------
# (a) Filter
# ---------------------------------------------------------------------------


def _version_condition(query_filter: Filter) -> FieldCondition:
    matches = [c for c in query_filter.must if c.key == "index_version"]
    assert len(matches) == 1
    return matches[0]


def test_filter_single_index_version_uses_match_value() -> None:
    f = build_organization_filter(organization_id="org", index_versions=[" v1 ", "v1", ""])
    cond = _version_condition(f)
    assert isinstance(cond.match, MatchValue)
    assert cond.match.value == "v1"


def test_filter_several_index_versions_use_match_any() -> None:
    f = build_organization_filter(organization_id="org", index_versions=("v1", "v0"))
    cond = _version_condition(f)
    assert isinstance(cond.match, MatchAny)
    assert cond.match.any == ["v1", "v0"]


def test_filter_rejects_both_version_parameters() -> None:
    with pytest.raises(ValueError, match="not both"):
        build_organization_filter(organization_id="org", index_version="v1", index_versions=["v1"])


@pytest.mark.parametrize("versions", [[], ["", "  "]])
def test_filter_empty_index_versions_fail_closed(versions: list[str]) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        build_organization_filter(organization_id="org", index_versions=versions)


def test_retrieve_candidates_forwards_index_versions_to_filter() -> None:
    client = FilterAwareFakeQdrantClient([])
    QueryRetrievalService(qdrant_client=client).retrieve_candidates(
        query_vector=[0.0] * settings.qdrant_vector_size,
        organization_id=uuid4(),
        document_ids=None,
        initial_top_k=3,
        index_versions=("v1", "v0"),
    )
    cond = _version_condition(client.calls[0]["query_filter"])  # type: ignore[arg-type]
    assert isinstance(cond.match, MatchAny)


# ---------------------------------------------------------------------------
# (b) Settings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        ("v0, v1", ["v0", "v1"]),
        ("v0,,v0, ", ["v0"]),
        (["v0", " v2 "], ["v0", "v2"]),
    ],
)
def test_active_index_versions_validator_parses(raw: object, expected: list[str]) -> None:
    assert Settings.validate_document_active_index_versions(raw) == expected


@pytest.mark.parametrize("raw", ["eval-x", "v1,EVAL-abc", "bad version", 5])
def test_active_index_versions_validator_rejects(raw: object) -> None:
    with pytest.raises(ValueError):
        Settings.validate_document_active_index_versions(raw)


def test_active_index_versions_property(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "document_active_index_versions", [])
    assert settings.active_index_versions == (settings.document_index_version,)
    monkeypatch.setattr(
        settings, "document_active_index_versions", [settings.document_index_version, "v0"]
    )
    assert settings.active_index_versions == (settings.document_index_version, "v0")
    snapshot = settings.sanitized_snapshot()
    assert snapshot["document_active_index_versions"] == [settings.document_index_version, "v0"]


# ---------------------------------------------------------------------------
# (c) Chat HTTP path: only production chunks are retrieved and cited
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_only_production_version_chunks(
    isolation_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, user = await _make_org_and_user(db_session, slug_prefix="r0205")
    prod_text = "Employees receive twenty days of annual leave."
    eval_text = "EVAL_ONLY_R0205 employees receive twenty days of annual leave."
    doc, chunk_a, chunk_b = await _make_document_with_versions(
        db_session, org=org, user=user, text=prod_text
    )
    fake_qdrant = FilterAwareFakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.99,
                payload=_payload(
                    org_id=org.id,
                    doc_id=doc.id,
                    chunk_id=chunk_b.id,
                    version=EVAL_VERSION,
                    text=eval_text,
                ),
            ),
            FakeQdrantResult(
                score=0.90,
                payload=_payload(
                    org_id=org.id,
                    doc_id=doc.id,
                    chunk_id=chunk_a.id,
                    version=settings.document_index_version,
                    text=prod_text,
                ),
            ),
        ]
    )
    qdrant_module.qdrant_client = fake_qdrant
    monkeypatch.setattr(
        chat_api,
        "_openai_client",
        FakeOpenAIClient(answer='{"answer":"' + prod_text + '","not_found":false,"citations":[]}'),
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await isolation_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)},
        json={
            "question": "How much annual leave?",
            "document_ids": [str(doc.id)],
            "top_k": 5,
            "rerank": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert fake_qdrant.calls, "chat must query Qdrant"
    cond = _version_condition(fake_qdrant.calls[0]["query_filter"])  # type: ignore[arg-type]
    assert isinstance(cond.match, MatchValue)
    assert cond.match.value == settings.document_index_version
    cited = {c["chunk_id"] for c in payload["citations"]}
    assert cited == {str(chunk_a.id)}
    assert str(chunk_b.id) not in response.text
    assert "EVAL_ONLY_R0205" not in response.text
    assert payload["debug"]["retrieval_count"] == 1


@pytest.mark.asyncio
async def test_inventory_answer_cites_only_production_version_chunks(
    isolation_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org, user = await _make_org_and_user(db_session, slug_prefix="r0205inv")
    repo = DocumentRepository()
    doc = await repo.create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="handbook.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"test/handbook-{uuid4()}.txt",
        status="indexed",
    )
    # The eval chunk is inserted first so it would win the chunk_index tie unfiltered.
    eval_chunk = await repo.create_document_chunk(
        db_session,
        document_id=doc.id,
        page_number=1,
        chunk_index=0,
        text="EVAL_ONLY_INVENTORY handbook text.",
        token_count=5,
        embedding_model=settings.openai_embedding_model,
        index_version=EVAL_VERSION,
        qdrant_point_id=f"{doc.id}:{EVAL_VERSION}:0",
    )
    prod_chunk = await repo.create_document_chunk(
        db_session,
        document_id=doc.id,
        page_number=1,
        chunk_index=0,
        text="Production handbook text.",
        token_count=5,
        embedding_model=settings.openai_embedding_model,
        index_version=settings.document_index_version,
        qdrant_point_id=f"{doc.id}:{settings.document_index_version}:0",
    )
    await db_session.commit()
    qdrant_module.qdrant_client = FilterAwareFakeQdrantClient([])
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await isolation_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)},
        json={"question": "Which files are included?", "scope_mode": "all", "rerank": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "handbook.txt" in payload["answer"]
    assert {c["chunk_id"] for c in payload["citations"]} == {str(prod_chunk.id)}
    assert str(eval_chunk.id) not in response.text
    assert "EVAL_ONLY_INVENTORY" not in response.text


# ---------------------------------------------------------------------------
# (d) AST guard: every chat retrieval call passes index_versions
# ---------------------------------------------------------------------------


def test_every_chat_parallel_retrieval_call_passes_index_versions() -> None:
    tree = ast.parse(CHAT_PY.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_parallel_retrieval_optimizer"
    ]
    assert len(calls) >= 2, "expected the HTTP and WebSocket retrieval calls"
    for call in calls:
        keywords = {kw.arg for kw in call.keywords}
        assert "index_versions" in keywords, f"line {call.lineno} omits index_versions"


# ---------------------------------------------------------------------------
# (e) Agent / MCP answer tool passes the active versions
# ---------------------------------------------------------------------------


class _StopRetrieval(Exception):
    pass


@pytest.mark.asyncio
async def test_answer_from_context_passes_active_index_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "document_active_index_versions", ["v0"])
    recorded: list[dict[str, Any]] = []

    class _RecordingRetrieval:
        embedding_model = "text-embedding-3-small"

        async def embed_and_retrieve(self, **kwargs: Any) -> Any:
            recorded.append(kwargs)
            raise _StopRetrieval

    def _failing_session_factory() -> Any:
        raise RuntimeError("no profile session in this test")

    service = DocumentIntelligenceToolService(
        session_factory=_failing_session_factory,  # type: ignore[arg-type]
        query_retrieval_service=_RecordingRetrieval(),  # type: ignore[arg-type]
    )
    principal = SimpleNamespace(organization_id=str(uuid4()))
    with pytest.raises(_StopRetrieval):
        await service._run_grounded_answer(
            question="What is the policy?",
            principal=principal,  # type: ignore[arg-type]
            document_ids=[uuid4()],
            top_k=3,
            rerank=False,
        )
    assert recorded[0]["index_versions"] == settings.active_index_versions
    assert recorded[0]["index_versions"] == (settings.document_index_version, "v0")


# ---------------------------------------------------------------------------
# (f) Keyword search on PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_keyword_search_filters_index_versions_on_postgres(
    pg_session: AsyncSession,
) -> None:
    org = Organization(name="R02-05 pg", slug=f"r0205-{uuid4().hex[:8]}")
    pg_session.add(org)
    await pg_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"r0205-{uuid4().hex[:8]}",
        email=f"r0205-{uuid4().hex[:8]}@example.com",
    )
    pg_session.add(user)
    await pg_session.flush()
    _doc, chunk_a, chunk_b = await _make_document_with_versions(
        pg_session, org=org, user=user, text="quarterly travel reimbursement policy"
    )
    service = KeywordRetrievalService()

    async def _search(**kwargs: Any) -> set[UUID]:
        result = await service.search_chunks(
            session=pg_session,
            query="travel reimbursement",
            organization_id=org.id,
            document_ids=None,
            top_k=10,
            **kwargs,
        )
        return {candidate.chunk_id for candidate in result.candidates}

    assert await _search() == {chunk_a.id, chunk_b.id}
    assert await _search(index_versions=settings.active_index_versions) == {chunk_a.id}
    assert await _search(index_version=EVAL_VERSION) == {chunk_b.id}
    assert await _search(index_versions=[]) == set()
    with pytest.raises(ValueError, match="not both"):
        await _search(index_version="v1", index_versions=["v1"])
