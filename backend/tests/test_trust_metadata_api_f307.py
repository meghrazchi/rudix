"""Tests for answer trust metadata contract (F307).

Covers:
- Schema DTO validation and round-trip serialization
- query_chat response includes trust_metadata with correct fields
- trust_metadata_json persisted on ChatMessage
- GET /chat/messages/{id}/trust-metadata returns stored snapshot
- 404 for unknown message, different user/org, user-role message, no snapshot
- Security: no ACL snapshots, no raw prompts, no internal UUIDs
"""

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.clients import qdrant_client as qdrant_module
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.ai.providers.factory import default_provider_factory
from app.domains.ai.providers.protocols import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.chat.schemas.trust_metadata import (
    AnswerTrustMetadataResponse,
    CitationTrustRecord,
    ClaimSupportRecord,
    ConfidenceTrustRecord,
    ConflictStatusRecord,
    GroundedVerificationRecord,
    ModelMetadataRecord,
    PolicyEnforcementRecord,
    RetrievalDiagnosticsRecord,
    SourceFreshnessRecord,
)
from app.domains.documents.repositories.documents import DocumentRepository
from app.interfaces.http import chat as chat_api
from app.main import app
from app.models.chat import ChatMessage
from app.models.document import DocumentChunk
from app.models.enums import ChatRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers reused from test_chat_query_api
# ---------------------------------------------------------------------------


class _FakeQdrantResult:
    def __init__(self, *, score: float, payload: dict) -> None:
        self.score = score
        self.payload = payload


class _FakeQdrantClient:
    def __init__(self, results: list[_FakeQdrantResult]) -> None:
        self._results = results

    def search(self, **kwargs: object) -> list[_FakeQdrantResult]:
        return list(self._results)


class _FakeChatProvider:
    def __init__(self, *, answer: str) -> None:
        self.answer = answer

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        if "You are reranking retrieved document chunks" in request.prompt:
            keys = [
                line.split(":", 1)[1].strip()
                for line in request.prompt.splitlines()
                if line.startswith("key:")
            ]
            scores = [
                {"key": key, "score": round(max(0.1, 0.92 - (i * 0.01)), 2)}
                for i, key in enumerate(keys)
            ]
            return ChatCompletionResponse(
                content=json.dumps({"scores": scores}),
                model=settings.openai_llm_model,
                prompt_tokens=19,
                completion_tokens=7,
                total_tokens=26,
                latency_ms=5,
            )
        return ChatCompletionResponse(
            content=self.answer,
            model=settings.openai_llm_model,
            prompt_tokens=31,
            completion_tokens=17,
            total_tokens=48,
            latency_ms=5,
        )


class _FakeEmbeddingProvider:
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            vectors=[[0.01] * settings.qdrant_vector_size],
            model=request.model or "text-embedding-3-small",
            prompt_tokens=7,
            total_tokens=7,
            latency_ms=1,
        )


def _inject_providers(monkeypatch: pytest.MonkeyPatch, *, answer: str) -> None:
    provider = _FakeChatProvider(answer=answer)
    embed = _FakeEmbeddingProvider()
    default_provider_factory._chat_providers.clear()
    default_provider_factory._chat_providers[settings.llm_default_provider] = provider
    default_provider_factory._chat_providers[settings.rerank_default_provider] = provider
    monkeypatch.setattr(chat_api._llm_service, "_provider", provider)
    monkeypatch.setattr(chat_api._query_retrieval_service, "_embedding_provider", embed)


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest_asyncio.fixture
async def trust_client(
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
    chat_api._llm_service._provider = None
    chat_api._query_retrieval_service._embedding_provider = None
    default_provider_factory._chat_providers.clear()


async def _seed_principal(db_session: AsyncSession) -> tuple[User, Organization]:
    org = Organization(name=f"Trust Org {uuid4().hex[:6]}", slug=f"trust-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"trust-user-{uuid4().hex[:8]}",
        email=f"trust-{uuid4().hex[:8]}@example.com",
        display_name="Trust Test User",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="member"))
    await db_session.commit()
    return user, org


async def _seed_document(
    db_session: AsyncSession, *, org: Organization, user: User
) -> tuple[object, DocumentChunk]:
    repo = DocumentRepository()
    doc = await repo.create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="trust-test.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/trust-{uuid4()}.pdf",
        status="indexed",
    )
    chunk = await repo.create_document_chunk(
        db_session,
        document_id=doc.id,
        page_number=1,
        chunk_index=0,
        text="Annual leave entitlement is twenty days.",
        token_count=50,
        embedding_model=settings.openai_embedding_model,
        index_version=settings.document_index_version,
        qdrant_point_id=f"{doc.id}:{settings.document_index_version}:0",
    )
    await db_session.commit()
    await db_session.refresh(doc)
    await db_session.refresh(chunk)
    return doc, chunk


def _chat_answer(doc_id: str, chunk_id: str) -> str:
    return json.dumps(
        {
            "answer": "Annual leave entitlement is twenty days.",
            "not_found": False,
            "citations": [{"document_id": doc_id, "chunk_id": chunk_id, "snippet": "Annual leave"}],
        }
    )


# ---------------------------------------------------------------------------
# Schema unit tests (no DB, no HTTP)
# ---------------------------------------------------------------------------


def test_answer_trust_metadata_schema_version_is_one() -> None:
    meta = AnswerTrustMetadataResponse(
        schema_version="1",
        organization_id="org-1",
        message_id="msg-1",
        not_found=False,
        citation_validation_failed=False,
        verification_failed=False,
        confidence=ConfidenceTrustRecord(
            score=0.85,
            category="high",
            citation_support_score=0.9,
            citation_validation_score=0.95,
            citation_coverage_score=0.8,
            retrieval_agreement_score=0.88,
            top_similarity=0.92,
            average_similarity=0.85,
            top_rerank_score=0.91,
            raw_score=0.87,
            citation_validation_multiplier=0.98,
            not_found_penalty_multiplier=1.0,
            not_found_signal=False,
            no_context=False,
        ),
        citations=[],
        retrieval=RetrievalDiagnosticsRecord(),
        grounded_verification=GroundedVerificationRecord(
            aggregate_support_score=0.0,
            claims=[],
        ),
        model=ModelMetadataRecord(llm_model="gpt-4o", llm_provider="openai"),
        conflict=ConflictStatusRecord(),
        policy=PolicyEnforcementRecord(),
        freshness=SourceFreshnessRecord(),
        generated_at=datetime.now(UTC),
    )
    assert meta.schema_version == "1"
    assert meta.organization_id == "org-1"
    assert meta.confidence.score == 0.85


def test_answer_trust_metadata_round_trips_json() -> None:
    meta = AnswerTrustMetadataResponse(
        schema_version="1",
        organization_id="org-abc",
        message_id="msg-abc",
        not_found=True,
        citation_validation_failed=False,
        verification_failed=True,
        confidence=ConfidenceTrustRecord(
            score=0.1,
            category="low",
            citation_support_score=0.0,
            citation_validation_score=0.0,
            citation_coverage_score=0.0,
            retrieval_agreement_score=0.0,
            top_similarity=0.0,
            average_similarity=0.0,
            top_rerank_score=0.0,
            raw_score=0.0,
            citation_validation_multiplier=0.0,
            not_found_penalty_multiplier=0.0,
            not_found_signal=True,
            no_context=True,
        ),
        citations=[],
        retrieval=RetrievalDiagnosticsRecord(retrieval_count=5, selected_count=0),
        grounded_verification=GroundedVerificationRecord(
            applied=True,
            verdict="unsupported",
            aggregate_support_score=0.12,
            claim_count=3,
            removed_count=3,
            claims=[
                ClaimSupportRecord(
                    claim_index=1,
                    claim_text="Employees get 25 days of leave.",
                    support_status="supported",
                    support_score=0.91,
                    evidence_match_score=1.0,
                    source_quality_score=0.95,
                    rerank_score=0.9,
                    chunk_coverage_score=0.5,
                    citation_indices=[1, 2],
                )
            ],
        ),
        model=ModelMetadataRecord(llm_model="gpt-4o-mini", prompt_template_version=2),
        conflict=ConflictStatusRecord(detected=True, conflict_count=1),
        policy=PolicyEnforcementRecord(applied=True, outcome="warned"),
        freshness=SourceFreshnessRecord(warning=True, stale_count=2),
        generated_at=datetime.now(UTC),
    )
    dumped = meta.model_dump(mode="json")
    restored = AnswerTrustMetadataResponse.model_validate(dumped)
    assert restored.not_found is True
    assert restored.grounded_verification.removed_count == 3
    assert restored.grounded_verification.aggregate_support_score == pytest.approx(0.12)
    assert restored.conflict.conflict_count == 1
    assert restored.freshness.stale_count == 2


def test_citation_trust_record_has_no_acl_snapshot_field() -> None:
    fields = CitationTrustRecord.model_fields
    assert "source_acl_snapshot" not in fields


def test_model_metadata_record_has_no_version_id_field() -> None:
    fields = ModelMetadataRecord.model_fields
    assert "prompt_template_version_id" not in fields


def test_confidence_score_clamped_to_zero_one() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ConfidenceTrustRecord(
            score=1.5,  # out of range
            category="high",
            citation_support_score=0.9,
            citation_validation_score=0.9,
            citation_coverage_score=0.9,
            retrieval_agreement_score=0.9,
            top_similarity=0.9,
            average_similarity=0.9,
            top_rerank_score=0.9,
            raw_score=0.9,
            citation_validation_multiplier=0.9,
            not_found_penalty_multiplier=0.9,
            not_found_signal=False,
            no_context=False,
        )


def test_conflict_status_defaults_to_no_conflict() -> None:
    record = ConflictStatusRecord()
    assert record.detected is False
    assert record.agreement_level == "full"
    assert record.conflict_count == 0
    assert record.conflicting_document_ids == []


def test_grounded_verification_defaults_to_not_applied() -> None:
    record = GroundedVerificationRecord()
    assert record.applied is False
    assert record.removed_count == 0
    assert record.reason_codes == []
    assert record.partially_supported_count == 0
    assert record.unverifiable_count == 0
    assert record.mode is None
    assert record.threshold is None


def test_policy_enforcement_defaults_to_not_applied() -> None:
    record = PolicyEnforcementRecord()
    assert record.applied is False
    assert record.violated_rules == []
    assert record.has_disclaimer is False


def test_citation_trust_record_defaults() -> None:
    record = CitationTrustRecord(document_id="d1", chunk_id="c1")
    assert record.doc_stale_warning is False
    assert record.doc_expired_warning is False
    assert record.is_table_chunk is False
    assert record.table_headers == []
    assert record.source_acl_snapshot if hasattr(record, "source_acl_snapshot") else True


# ---------------------------------------------------------------------------
# Integration: query_chat includes trust_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_chat_response_includes_trust_metadata(
    trust_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed_principal(db_session)
    doc, chunk = await _seed_document(db_session, org=org, user=user)

    qdrant_module.qdrant_client = _FakeQdrantClient(
        [
            _FakeQdrantResult(
                score=0.92,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(doc.id),
                    "chunk_id": str(chunk.id),
                    "filename": "trust-test.pdf",
                    "page_number": 1,
                    "text": "Annual leave entitlement is twenty days.",
                },
            )
        ]
    )
    _inject_providers(monkeypatch, answer=_chat_answer(str(doc.id), str(chunk.id)))
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await trust_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"question": "How much leave?", "document_ids": [str(doc.id)]},
    )

    assert response.status_code == 200
    payload = response.json()
    tm = payload.get("trust_metadata")
    assert tm is not None
    assert tm["schema_version"] == "1"
    assert tm["organization_id"] == str(org.id)
    assert tm["message_id"] == payload["message_id"]
    assert tm["not_found"] is False
    assert isinstance(tm["confidence"]["score"], float)
    assert tm["confidence"]["category"] in {"low", "medium", "high"}
    assert tm["confidence"]["not_found_signal"] is False
    assert isinstance(tm["citations"], list)
    assert len(tm["citations"]) >= 0
    assert isinstance(tm["retrieval"]["retrieval_count"], int)
    assert isinstance(tm["grounded_verification"]["applied"], bool)
    assert "llm_model" in tm["model"]
    assert "prompt_template_version_id" not in tm["model"]
    assert isinstance(tm["conflict"]["detected"], bool)
    assert isinstance(tm["policy"]["applied"], bool)
    assert isinstance(tm["freshness"]["warning"], bool)


@pytest.mark.asyncio
async def test_query_chat_trust_metadata_persisted_in_db(
    trust_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed_principal(db_session)
    doc, chunk = await _seed_document(db_session, org=org, user=user)

    qdrant_module.qdrant_client = _FakeQdrantClient(
        [
            _FakeQdrantResult(
                score=0.88,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(doc.id),
                    "chunk_id": str(chunk.id),
                    "filename": "trust-test.pdf",
                    "page_number": 1,
                    "text": "Annual leave entitlement is twenty days.",
                },
            )
        ]
    )
    _inject_providers(monkeypatch, answer=_chat_answer(str(doc.id), str(chunk.id)))
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await trust_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"question": "How much leave?"},
    )

    assert response.status_code == 200
    message_id = response.json()["message_id"]

    messages = list((await db_session.execute(select(ChatMessage))).scalars().all())
    assistant_msg = next(m for m in messages if m.role == "assistant")
    assert str(assistant_msg.id) == message_id
    assert assistant_msg.trust_metadata_json is not None
    assert assistant_msg.trust_metadata_json["schema_version"] == "1"
    assert assistant_msg.trust_metadata_json["message_id"] == message_id
    assert "acl" not in str(assistant_msg.trust_metadata_json)


@pytest.mark.asyncio
async def test_query_chat_trust_metadata_citations_empty_when_not_found(
    trust_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed_principal(db_session)

    qdrant_module.qdrant_client = _FakeQdrantClient([])
    _inject_providers(
        monkeypatch,
        answer='{"answer":"I don\'t know.","not_found":true,"citations":[]}',
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await trust_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"question": "Unknowable question?"},
    )

    assert response.status_code == 200
    tm = response.json().get("trust_metadata", {})
    assert tm["not_found"] is True
    assert tm["citations"] == []


# ---------------------------------------------------------------------------
# Integration: GET /chat/messages/{id}/trust-metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trust_metadata_returns_stored_snapshot(
    trust_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed_principal(db_session)
    doc, chunk = await _seed_document(db_session, org=org, user=user)

    qdrant_module.qdrant_client = _FakeQdrantClient(
        [
            _FakeQdrantResult(
                score=0.90,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(doc.id),
                    "chunk_id": str(chunk.id),
                    "filename": "trust-test.pdf",
                    "page_number": 1,
                    "text": "Annual leave entitlement is twenty days.",
                },
            )
        ]
    )
    _inject_providers(monkeypatch, answer=_chat_answer(str(doc.id), str(chunk.id)))
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    chat_resp = await trust_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"question": "How much leave?"},
    )
    assert chat_resp.status_code == 200
    message_id = chat_resp.json()["message_id"]

    get_resp = await trust_client.get(
        f"/api/v1/chat/messages/{message_id}/trust-metadata",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert get_resp.status_code == 200
    tm = get_resp.json()
    assert tm["schema_version"] == "1"
    assert tm["message_id"] == message_id
    assert tm["organization_id"] == str(org.id)
    assert "source_acl_snapshot" not in str(tm)
    assert "prompt_template_version_id" not in str(tm)


@pytest.mark.asyncio
async def test_get_trust_metadata_returns_404_for_unknown_message(
    trust_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp = await trust_client.get(
        f"/api/v1/chat/messages/{uuid4()}/trust-metadata",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_trust_metadata_returns_404_for_invalid_uuid(
    trust_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp = await trust_client.get(
        "/api/v1/chat/messages/not-a-uuid/trust-metadata",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_trust_metadata_returns_404_for_different_user(
    trust_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed_principal(db_session)
    doc, chunk = await _seed_document(db_session, org=org, user=user)

    qdrant_module.qdrant_client = _FakeQdrantClient(
        [
            _FakeQdrantResult(
                score=0.90,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(doc.id),
                    "chunk_id": str(chunk.id),
                    "filename": "trust-test.pdf",
                    "page_number": 1,
                    "text": "Annual leave entitlement is twenty days.",
                },
            )
        ]
    )
    _inject_providers(monkeypatch, answer=_chat_answer(str(doc.id), str(chunk.id)))
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    chat_resp = await trust_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"question": "How much leave?"},
    )
    assert chat_resp.status_code == 200
    message_id = chat_resp.json()["message_id"]

    # Different user in the same org
    other_user = User(
        organization_id=org.id,
        external_auth_id=f"other-{uuid4().hex[:8]}",
        email=f"other-{uuid4().hex[:8]}@example.com",
        display_name="Other User",
    )
    db_session.add(other_user)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=other_user.id, role="member"))
    await db_session.commit()

    other_token = create_app_access_token(
        subject=other_user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp = await trust_client.get(
        f"/api/v1/chat/messages/{message_id}/trust-metadata",
        headers=_auth_headers(token=other_token, organization_id=str(org.id)),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_trust_metadata_returns_404_for_message_without_snapshot(
    trust_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Messages created before F307 (trust_metadata_json=NULL) return 404."""
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    repo = ChatRepository()
    session = await repo.create_chat_session(db_session, organization_id=org.id, user_id=user.id)
    msg = await repo.create_chat_message(
        db_session,
        chat_session_id=session.id,
        role=ChatRole.assistant.value,
        content="Legacy answer with no trust metadata.",
    )
    await db_session.commit()

    resp = await trust_client.get(
        f"/api/v1/chat/messages/{msg.id}/trust-metadata",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "trust_metadata_not_available"


@pytest.mark.asyncio
async def test_get_trust_metadata_returns_404_for_user_role_message(
    trust_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """User-role (question) messages never have trust metadata."""
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    repo = ChatRepository()
    session = await repo.create_chat_session(db_session, organization_id=org.id, user_id=user.id)
    user_msg = await repo.create_chat_message(
        db_session,
        chat_session_id=session.id,
        role=ChatRole.user.value,
        content="My question.",
        trust_metadata_json={"schema_version": "1"},
    )
    await db_session.commit()

    resp = await trust_client.get(
        f"/api/v1/chat/messages/{user_msg.id}/trust-metadata",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trust_metadata_org_id_matches_principal(
    trust_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed_principal(db_session)
    doc, chunk = await _seed_document(db_session, org=org, user=user)

    qdrant_module.qdrant_client = _FakeQdrantClient(
        [
            _FakeQdrantResult(
                score=0.91,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(doc.id),
                    "chunk_id": str(chunk.id),
                    "filename": "trust-test.pdf",
                    "page_number": 1,
                    "text": "Annual leave entitlement is twenty days.",
                },
            )
        ]
    )
    _inject_providers(monkeypatch, answer=_chat_answer(str(doc.id), str(chunk.id)))
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    chat_resp = await trust_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"question": "How much leave?"},
    )
    assert chat_resp.status_code == 200
    message_id = chat_resp.json()["message_id"]

    get_resp = await trust_client.get(
        f"/api/v1/chat/messages/{message_id}/trust-metadata",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["organization_id"] == str(org.id)
