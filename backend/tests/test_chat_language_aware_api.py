"""Tests for F231: Language-aware RAG answers, retrieval controls, and response language settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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

from app.auth.token_codec import create_app_access_token
from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.chat.services.language_service import detect_language, resolve_answer_language
from app.domains.chat.services.prompt_service import PromptService
from app.interfaces.http import chat as chat_api
from app.main import app
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ---------------------------------------------------------------------------
# Fake infrastructure
# ---------------------------------------------------------------------------


@dataclass
class FakeQdrantResult:
    score: float
    payload: dict[str, object]


class FakeQdrantClient:
    def __init__(self, results: list[FakeQdrantResult]) -> None:
        self._results = results
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> list[FakeQdrantResult]:
        self.calls.append(kwargs)
        return list(self._results)


class FakeEmbeddingsEndpoint:
    def __init__(self, vector_size: int) -> None:
        self.vector_size = vector_size
        self.calls: list[dict] = []

    async def create(self, *, model: str, input: list[str]) -> object:
        self.calls.append({"model": model, "input": input})
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.01] * self.vector_size)],
            usage=SimpleNamespace(prompt_tokens=7),
        )


class FakeChatCompletionsEndpoint:
    def __init__(self, *, answer: str) -> None:
        self.answer = answer
        self.calls: list[dict] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.answer))],
            usage=SimpleNamespace(prompt_tokens=31, completion_tokens=17),
            model=settings.openai_llm_model,
        )


class FakeOpenAIClient:
    def __init__(self, *, answer: str) -> None:
        self.embeddings = FakeEmbeddingsEndpoint(settings.qdrant_vector_size)
        self.chat = SimpleNamespace(completions=FakeChatCompletionsEndpoint(answer=answer))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, org_id: str) -> str:
    return create_app_access_token(
        user_id=user_id,
        organization_id=org_id,
        roles=[OrganizationRole.member.value],
        secret="test-secret",
        issuer="rudix-app",
        audience="rudix-api",
        ttl_seconds=3600,
    )


def _auth_headers(token: str, org_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}


async def _seed(db_session: AsyncSession):
    org = Organization(id=uuid4(), name="Lang Org", slug=f"lang-{uuid4()}")
    user = User(id=uuid4(), email=f"u-{uuid4()}@example.com", hashed_password="x")
    member = OrganizationMember(
        organization_id=org.id, user_id=user.id, role=OrganizationRole.member.value
    )
    db_session.add_all([org, user, member])
    await db_session.flush()
    return user, org


async def _seed_doc_chunk(db_session: AsyncSession, *, org: Organization, user: User, text: str):
    doc = Document(
        id=uuid4(),
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="test.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"test/{uuid4()}.pdf",
        status=DocumentStatus.indexed.value,
    )
    db_session.add(doc)
    await db_session.flush()

    chunk = DocumentChunk(
        id=uuid4(),
        document_id=doc.id,
        chunk_index=0,
        text=text,
        token_count=len(text.split()),
        embedding_model=settings.openai_embedding_model,
        index_version=settings.document_index_version,
    )
    db_session.add(chunk)
    await db_session.flush()
    return doc, chunk


def _qdrant_result(org: Organization, doc: Document, chunk: DocumentChunk, score: float = 0.91):
    return FakeQdrantResult(
        score=score,
        payload={
            "organization_id": str(org.id),
            "document_id": str(doc.id),
            "chunk_id": str(chunk.id),
            "filename": doc.filename,
            "text": chunk.text,
            "page_number": 1,
        },
    )


@pytest_asyncio.fixture
async def lang_client(db_session: AsyncSession):
    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    app.dependency_overrides.pop(get_db_session, None)


# ---------------------------------------------------------------------------
# LanguageService unit tests (fast, no HTTP)
# ---------------------------------------------------------------------------


class TestLanguageServiceDetect:
    def test_detects_german_question(self) -> None:
        result = detect_language("Was ist die Hauptstadt von Deutschland?")
        assert result == "de"

    def test_detects_english_question(self) -> None:
        result = detect_language("What is the annual leave policy?")
        assert result == "en"

    def test_detects_spanish_question(self) -> None:
        result = detect_language("¿Cuál es la política de vacaciones?")
        assert result == "es"

    def test_detects_french_question(self) -> None:
        result = detect_language("Quelle est la politique de congés?")
        assert result == "fr"

    def test_empty_question_returns_none(self) -> None:
        assert detect_language("") is None

    def test_short_question_returns_none(self) -> None:
        assert detect_language("ok") is None


class TestResolveAnswerLanguage:
    def test_auto_mode_returns_none(self) -> None:
        assert (
            resolve_answer_language(mode="auto", detected_language="de", workspace_default="en")
            is None
        )

    def test_none_mode_returns_none(self) -> None:
        assert (
            resolve_answer_language(mode=None, detected_language="de", workspace_default="en")
            is None
        )

    def test_explicit_de_returns_de(self) -> None:
        assert (
            resolve_answer_language(mode="de", detected_language=None, workspace_default="en")
            == "de"
        )

    def test_same_as_question_uses_detected(self) -> None:
        assert (
            resolve_answer_language(
                mode="same_as_question", detected_language="es", workspace_default="en"
            )
            == "es"
        )

    def test_same_as_question_falls_back_to_workspace_default(self) -> None:
        assert (
            resolve_answer_language(
                mode="same_as_question", detected_language=None, workspace_default="fr"
            )
            == "fr"
        )

    def test_workspace_default_returns_configured_lang(self) -> None:
        assert (
            resolve_answer_language(
                mode="workspace_default", detected_language="de", workspace_default="en"
            )
            == "en"
        )

    def test_unsupported_mode_returns_none(self) -> None:
        assert (
            resolve_answer_language(mode="klingon", detected_language=None, workspace_default="en")
            is None
        )


# ---------------------------------------------------------------------------
# PromptService language injection unit tests
# ---------------------------------------------------------------------------


class TestPromptServiceLanguageInjection:
    def setup_method(self) -> None:
        self.svc = PromptService()

    def test_build_prompt_with_german_language_includes_rule(self) -> None:
        prompt = self.svc.build_prompt(
            question="Was ist Urlaub?",
            chunks=[],
            not_found_answer="not found",
            answer_language="de",
        )
        assert "German" in prompt

    def test_build_prompt_without_language_has_no_language_rule(self) -> None:
        prompt = self.svc.build_prompt(
            question="What is leave?",
            chunks=[],
            not_found_answer="not found",
            answer_language=None,
        )
        assert "Write the answer in" not in prompt

    def test_build_guidance_prompt_with_french_language_includes_rule(self) -> None:
        prompt = self.svc.build_guidance_prompt(
            question="Quelle est la politique?",
            answer_language="fr",
        )
        assert "French" in prompt

    def test_build_guidance_prompt_without_language_has_no_language_rule(self) -> None:
        prompt = self.svc.build_guidance_prompt(
            question="What is the policy?",
            answer_language=None,
        )
        assert "Write the answer in" not in prompt
        assert "Rudix product guidance assistant" in prompt

    def test_citation_integrity_rule_always_present_with_language(self) -> None:
        prompt = self.svc.build_prompt(
            question="Was?",
            chunks=[],
            not_found_answer="not found",
            answer_language="es",
        )
        assert "Citations must reference original source text" in prompt

    def test_language_instruction_does_not_remove_injection_defense_rules(self) -> None:
        prompt = self.svc.build_prompt(
            question="Was?",
            chunks=[],
            not_found_answer="not found",
            answer_language="de",
        )
        assert "untrusted data" in prompt
        assert "untrusted input" in prompt


# ---------------------------------------------------------------------------
# HTTP API integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_language_en_passes_english_instruction_to_llm(
    lang_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed(db_session)
    doc, chunk = await _seed_doc_chunk(
        db_session, org=org, user=user, text="Annual leave is thirty days."
    )
    token = _make_token(str(user.id), str(org.id))

    qdrant_module.qdrant_client = FakeQdrantClient([_qdrant_result(org, doc, chunk)])
    answer_json = (
        '{"answer":"Annual leave is thirty days.","not_found":false,'
        f'"citations":[{{"document_id":"{doc.id}","chunk_id":"{chunk.id}",'
        '"filename":"test.pdf","page_number":1,"text_snippet":"Annual leave is thirty days."}'
        "]}"
    )
    fake_openai = FakeOpenAIClient(answer=answer_json)
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await lang_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token, str(org.id)),
        json={
            "question": "How many days of annual leave?",
            "document_ids": [str(doc.id)],
            "answer_language": "en",
            "rerank": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["not_found"] is False
    # Prompt sent to LLM must contain the English language instruction.
    llm_call = fake_openai.chat.completions.calls[0]
    messages = llm_call["messages"]
    system_content = next(m["content"] for m in messages if m["role"] == "system")
    assert "English" in system_content
    # Debug response must reflect language metadata.
    assert data["debug"]["answer_language_used"] == "en"


@pytest.mark.asyncio
async def test_answer_language_de_passes_german_instruction_to_llm(
    lang_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed(db_session)
    doc, chunk = await _seed_doc_chunk(
        db_session, org=org, user=user, text="Der Jahresurlaub beträgt 30 Tage."
    )
    token = _make_token(str(user.id), str(org.id))

    qdrant_module.qdrant_client = FakeQdrantClient([_qdrant_result(org, doc, chunk)])
    answer_json = (
        '{"answer":"Der Jahresurlaub beträgt 30 Tage.","not_found":false,'
        f'"citations":[{{"document_id":"{doc.id}","chunk_id":"{chunk.id}",'
        '"filename":"test.pdf","page_number":1,"text_snippet":"Der Jahresurlaub beträgt 30 Tage."}'
        "]}"
    )
    fake_openai = FakeOpenAIClient(answer=answer_json)
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await lang_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token, str(org.id)),
        json={
            "question": "Wie viele Urlaubstage gibt es?",
            "document_ids": [str(doc.id)],
            "answer_language": "de",
            "rerank": False,
        },
    )

    assert response.status_code == 200
    llm_call = fake_openai.chat.completions.calls[0]
    messages = llm_call["messages"]
    system_content = next(m["content"] for m in messages if m["role"] == "system")
    assert "German" in system_content
    assert response.json()["debug"]["answer_language_used"] == "de"


@pytest.mark.asyncio
async def test_answer_language_auto_omits_language_instruction(
    lang_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed(db_session)
    doc, chunk = await _seed_doc_chunk(db_session, org=org, user=user, text="Leave is 30 days.")
    token = _make_token(str(user.id), str(org.id))

    qdrant_module.qdrant_client = FakeQdrantClient([_qdrant_result(org, doc, chunk)])
    answer_json = (
        '{"answer":"Leave is 30 days.","not_found":false,'
        f'"citations":[{{"document_id":"{doc.id}","chunk_id":"{chunk.id}",'
        '"filename":"test.pdf","page_number":1,"text_snippet":"Leave is 30 days."}'
        "]}"
    )
    fake_openai = FakeOpenAIClient(answer=answer_json)
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await lang_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token, str(org.id)),
        json={
            "question": "How many leave days?",
            "document_ids": [str(doc.id)],
            "answer_language": "auto",
            "rerank": False,
        },
    )

    assert response.status_code == 200
    llm_call = fake_openai.chat.completions.calls[0]
    messages = llm_call["messages"]
    system_content = next(m["content"] for m in messages if m["role"] == "system")
    assert "Write the answer in" not in system_content
    assert response.json()["debug"]["answer_language_used"] is None


@pytest.mark.asyncio
async def test_same_as_question_detects_german_and_instructs_german(
    lang_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed(db_session)
    doc, chunk = await _seed_doc_chunk(
        db_session, org=org, user=user, text="Urlaub beträgt 30 Tage."
    )
    token = _make_token(str(user.id), str(org.id))

    qdrant_module.qdrant_client = FakeQdrantClient([_qdrant_result(org, doc, chunk)])
    answer_json = (
        '{"answer":"Der Urlaub beträgt 30 Tage.","not_found":false,'
        f'"citations":[{{"document_id":"{doc.id}","chunk_id":"{chunk.id}",'
        '"filename":"test.pdf","page_number":1,"text_snippet":"Urlaub beträgt 30 Tage."}'
        "]}"
    )
    fake_openai = FakeOpenAIClient(answer=answer_json)
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await lang_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token, str(org.id)),
        json={
            "question": "Wie viele Urlaubstage gibt es laut den Richtlinien?",
            "document_ids": [str(doc.id)],
            "answer_language": "same_as_question",
            "rerank": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["debug"]["detected_language"] == "de"
    assert data["debug"]["answer_language_used"] == "de"
    llm_call = fake_openai.chat.completions.calls[0]
    messages = llm_call["messages"]
    system_content = next(m["content"] for m in messages if m["role"] == "system")
    assert "German" in system_content


@pytest.mark.asyncio
async def test_citation_validation_enforced_for_translated_answers(
    lang_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Citation validation must fire even when answer language is different from chunk language."""
    user, org = await _seed(db_session)
    doc, chunk = await _seed_doc_chunk(db_session, org=org, user=user, text="Leave is 30 days.")
    token = _make_token(str(user.id), str(org.id))

    qdrant_module.qdrant_client = FakeQdrantClient([_qdrant_result(org, doc, chunk)])
    # Model returns a citation referencing a FAKE chunk_id — should be caught.
    fake_chunk_id = str(uuid4())
    answer_json = (
        f'{{"answer":"Der Urlaub beträgt 30 Tage.","not_found":false,'
        f'"citations":[{{"document_id":"{doc.id}","chunk_id":"{fake_chunk_id}",'
        '"filename":"test.pdf","page_number":1,"text_snippet":"Leave is 30 days."}'
        "]}"
    )
    fake_openai = FakeOpenAIClient(answer=answer_json)
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await lang_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token, str(org.id)),
        json={
            "question": "How many leave days?",
            "document_ids": [str(doc.id)],
            "answer_language": "de",
            "rerank": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    # citation_validation_failed must be True because chunk_id was hallucinated.
    assert data["citation_validation_failed"] is True


@pytest.mark.asyncio
async def test_language_setting_cannot_bypass_org_isolation(
    lang_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Language settings must not grant access to another org's documents."""
    user, org = await _seed(db_session)
    token = _make_token(str(user.id), str(org.id))

    # Create a document in a different org.
    other_org = Organization(id=uuid4(), name="Other Org", slug=f"other-{uuid4()}")
    other_user = User(id=uuid4(), email=f"other-{uuid4()}@example.com", hashed_password="x")
    db_session.add_all([other_org, other_user])
    await db_session.flush()
    _, _other_chunk = await _seed_doc_chunk(
        db_session, org=other_org, user=other_user, text="Confidential data."
    )

    qdrant_module.qdrant_client = FakeQdrantClient([])
    fake_openai = FakeOpenAIClient(answer='{"answer":"not found","not_found":true,"citations":[]}')
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await lang_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token, str(org.id)),
        json={
            "question": "What is the confidential data?",
            "answer_language": "en",
            "rerank": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    # The answer must be not_found — the other org's doc was never returned.
    assert data["not_found"] is True


@pytest.mark.asyncio
async def test_debug_response_includes_language_metadata(
    lang_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed(db_session)
    token = _make_token(str(user.id), str(org.id))

    qdrant_module.qdrant_client = FakeQdrantClient([])
    fake_openai = FakeOpenAIClient(answer='{"answer":"ok","not_found":false,"citations":[]}')
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await lang_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token, str(org.id)),
        json={
            "question": "¿Cuántos días de vacaciones hay?",
            "scope_mode": "none",
            "answer_language": "es",
            "rerank": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "detected_language" in data["debug"]
    assert "answer_language_used" in data["debug"]
    assert data["debug"]["answer_language_used"] == "es"
    # Spanish question with markers → detected as Spanish
    assert data["debug"]["detected_language"] == "es"


@pytest.mark.asyncio
async def test_answer_language_not_set_has_null_fields_in_debug(
    lang_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed(db_session)
    token = _make_token(str(user.id), str(org.id))

    qdrant_module.qdrant_client = FakeQdrantClient([])
    fake_openai = FakeOpenAIClient(answer='{"answer":"ok","not_found":false,"citations":[]}')
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await lang_client.post(
        "/api/v1/chat",
        headers=_auth_headers(token, str(org.id)),
        json={
            "question": "What is leave?",
            "scope_mode": "none",
            "rerank": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["debug"]["answer_language_used"] is None
