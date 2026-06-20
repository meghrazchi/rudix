"""Backend tests for F221: Admin model provider diagnostics.

Covers:
  A. GET /admin/model-providers — returns two cards (chat + embeddings)
  B. GET /admin/model-providers — provider_type reflects settings
  C. GET /admin/model-providers — is_configured=True when OpenAI key present
  D. GET /admin/model-providers — is_configured=False for local when base_url absent
  E. GET /admin/model-providers — capability populated from registry when model known
  F. GET /admin/model-providers — reindex_required=True when embedding dim mismatches
  G. GET /admin/model-providers — correct task_assignments for each card
  H. POST /admin/model-providers/test — ok status on successful chat probe
  I. POST /admin/model-providers/test — ok status on successful embeddings probe
  J. POST /admin/model-providers/test — configuration_error when provider unavailable
  K. POST /admin/model-providers/test — error code on probe exception
  L. POST /admin/model-providers/test — 422 on invalid provider_key
  M. Role guard — viewer can GET but cannot POST test
  N. Role guard — unauthenticated request returns 401

Run:
    pytest tests/test_model_provider_diagnostics_f221.py -v
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
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
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.ai.providers.capability_registry import default_capability_registry
from app.domains.ai.providers.errors import ProviderUnavailableError
from app.domains.ai.providers.protocols import ChatCompletionResponse, EmbeddingResponse
from app.domains.ai.providers.schemas import CostBehavior, ModelCapability
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

BASE = "/api/v1/admin/model-providers"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def diag_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


def _make_token(user_id: str, org_id: str, role: str = OrganizationRole.admin.value) -> str:
    return create_app_access_token(
        user_id=user_id,
        organization_id=org_id,
        role=role,
        secret=SecretStr("test-secret"),
        issuer="rudix-test",
        audience="rudix-test-audience",
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_ctx(db_session: AsyncSession):
    org = Organization(name="Diag Org", slug=f"diag-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"diag-admin-{uuid4().hex[:6]}@test.com", display_name="Admin")
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.admin.value,
    )
    db_session.add(member)
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id))
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


@pytest_asyncio.fixture
async def viewer_ctx(db_session: AsyncSession):
    org = Organization(name="Viewer Diag Org", slug=f"vdiag-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"vdiag-{uuid4().hex[:6]}@test.com", display_name="Viewer")
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.viewer.value,
    )
    db_session.add(member)
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.viewer.value)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


# ---------------------------------------------------------------------------
# A. Returns two provider cards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_providers_returns_two_cards(diag_client, admin_ctx) -> None:
    r = await diag_client.get(BASE, headers=_auth(admin_ctx["token"]))
    assert r.status_code == 200
    body = r.json()
    assert len(body["providers"]) == 2
    keys = {p["provider_key"] for p in body["providers"]}
    assert keys == {"chat", "embeddings"}


# ---------------------------------------------------------------------------
# B. Provider type reflects settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_type_from_settings(
    diag_client, admin_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "llm_default_provider", "openai")
    monkeypatch.setattr(settings, "embedding_default_provider", "openai")
    r = await diag_client.get(BASE, headers=_auth(admin_ctx["token"]))
    assert r.status_code == 200
    providers = {p["provider_key"]: p for p in r.json()["providers"]}
    assert providers["chat"]["provider_type"] == "openai"
    assert providers["embeddings"]["provider_type"] == "openai"


# ---------------------------------------------------------------------------
# C. is_configured=True when OpenAI key present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_configured_true_when_key_present(
    diag_client, admin_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-test"))
    monkeypatch.setattr(settings, "llm_default_provider", "openai")
    monkeypatch.setattr(settings, "embedding_default_provider", "openai")
    r = await diag_client.get(BASE, headers=_auth(admin_ctx["token"]))
    assert r.status_code == 200
    providers = {p["provider_key"]: p for p in r.json()["providers"]}
    assert providers["chat"]["is_configured"] is True
    assert providers["embeddings"]["is_configured"] is True


# ---------------------------------------------------------------------------
# D. is_configured=False for local when base_url absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_configured_false_local_no_base_url(
    diag_client, admin_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "llm_default_provider", "local")
    monkeypatch.setattr(settings, "local_llm_base_url", None)
    monkeypatch.setattr(settings, "embedding_default_provider", "local")
    monkeypatch.setattr(settings, "local_embedding_base_url", None)
    r = await diag_client.get(BASE, headers=_auth(admin_ctx["token"]))
    assert r.status_code == 200
    providers = {p["provider_key"]: p for p in r.json()["providers"]}
    assert providers["chat"]["is_configured"] is False
    assert providers["embeddings"]["is_configured"] is False


# ---------------------------------------------------------------------------
# E. Capability populated from registry when model known
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_populated_from_registry(
    diag_client, admin_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_cap = ModelCapability(
        provider="openai",
        model_name="gpt-test-model",
        context_window=128000,
        max_input_tokens=128000,
        is_chat_model=True,
        supports_json_mode=True,
        supports_tool_calling=True,
        supports_streaming=True,
        cost_behavior=CostBehavior.per_token,
    )
    default_capability_registry.register(test_cap)
    monkeypatch.setattr(settings, "llm_default_provider", "openai")
    monkeypatch.setattr(settings, "openai_llm_model", "gpt-test-model")
    try:
        r = await diag_client.get(BASE, headers=_auth(admin_ctx["token"]))
        assert r.status_code == 200
        providers = {p["provider_key"]: p for p in r.json()["providers"]}
        cap = providers["chat"]["capability"]
        assert cap is not None
        assert cap["context_window"] == 128000
        assert cap["supports_json_mode"] is True
        assert cap["supports_tool_calling"] is True
    finally:
        # Remove test entry to avoid polluting other tests
        default_capability_registry._registry.pop(("openai", "gpt-test-model"), None)


# ---------------------------------------------------------------------------
# F. reindex_required=True when embedding dimension mismatches qdrant_vector_size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reindex_required_on_dimension_mismatch(
    diag_client, admin_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_cap = ModelCapability(
        provider="openai",
        model_name="emb-mismatch-model",
        context_window=8192,
        max_input_tokens=8192,
        is_chat_model=False,
        is_embedding_model=True,
        embedding_dimension=3072,
        cost_behavior=CostBehavior.per_token,
    )
    default_capability_registry.register(test_cap)
    monkeypatch.setattr(settings, "embedding_default_provider", "openai")
    monkeypatch.setattr(settings, "openai_embedding_model", "emb-mismatch-model")
    monkeypatch.setattr(settings, "qdrant_vector_size", 1536)
    try:
        r = await diag_client.get(BASE, headers=_auth(admin_ctx["token"]))
        assert r.status_code == 200
        providers = {p["provider_key"]: p for p in r.json()["providers"]}
        assert providers["embeddings"]["reindex_required"] is True
    finally:
        default_capability_registry._registry.pop(("openai", "emb-mismatch-model"), None)


# ---------------------------------------------------------------------------
# G. Correct task_assignments for each card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_assignments(diag_client, admin_ctx) -> None:
    r = await diag_client.get(BASE, headers=_auth(admin_ctx["token"]))
    assert r.status_code == 200
    providers = {p["provider_key"]: p for p in r.json()["providers"]}
    assert set(providers["chat"]["task_assignments"]) == {
        "chat",
        "summarization",
        "comparison",
        "evaluations",
        "agentic",
    }
    assert providers["embeddings"]["task_assignments"] == ["embeddings"]


# ---------------------------------------------------------------------------
# H. POST test — ok on successful chat probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_chat_ok(diag_client, admin_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_response = ChatCompletionResponse(
        content="OK",
        model="gpt-test",
        prompt_tokens=3,
        completion_tokens=1,
        total_tokens=4,
        latency_ms=50,
    )
    mock_provider = MagicMock()
    mock_provider.complete = AsyncMock(return_value=mock_response)

    with patch(
        "app.interfaces.http.model_provider_diagnostics.default_provider_factory.get_chat_provider",
        return_value=mock_provider,
    ):
        monkeypatch.setattr(settings, "llm_default_provider", "openai")
        r = await diag_client.post(
            f"{BASE}/test",
            json={"provider_key": "chat"},
            headers=_auth(admin_ctx["token"]),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["provider_key"] == "chat"
    assert body["latency_ms"] is not None
    assert body["error_code"] is None


# ---------------------------------------------------------------------------
# I. POST test — ok on successful embeddings probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_embeddings_ok(diag_client, admin_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_response = EmbeddingResponse(
        vectors=[[0.1, 0.2]],
        model="text-embedding-3-small",
        prompt_tokens=1,
        total_tokens=1,
        latency_ms=30,
    )
    mock_provider = MagicMock()
    mock_provider.embed = AsyncMock(return_value=mock_response)

    with patch(
        "app.interfaces.http.model_provider_diagnostics.default_provider_factory.get_embedding_provider",
        return_value=mock_provider,
    ):
        monkeypatch.setattr(settings, "embedding_default_provider", "openai")
        r = await diag_client.post(
            f"{BASE}/test",
            json={"provider_key": "embeddings"},
            headers=_auth(admin_ctx["token"]),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["provider_key"] == "embeddings"
    assert body["error_code"] is None


# ---------------------------------------------------------------------------
# J. POST test — configuration_error when provider unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_chat_configuration_error(
    diag_client, admin_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    with patch(
        "app.interfaces.http.model_provider_diagnostics.default_provider_factory.get_chat_provider",
        side_effect=ProviderUnavailableError("No API key"),
    ):
        monkeypatch.setattr(settings, "llm_default_provider", "openai")
        r = await diag_client.post(
            f"{BASE}/test",
            json={"provider_key": "chat"},
            headers=_auth(admin_ctx["token"]),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "configuration_error"
    assert body["error_code"] == "configuration_error"
    assert body["error_message"] is not None
    # Must not expose the original exception message
    assert "No API key" not in (body["error_message"] or "")


# ---------------------------------------------------------------------------
# K. POST test — error code on generic probe exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_chat_generic_error(
    diag_client, admin_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_provider = MagicMock()
    mock_provider.complete = AsyncMock(side_effect=RuntimeError("unexpected"))

    with patch(
        "app.interfaces.http.model_provider_diagnostics.default_provider_factory.get_chat_provider",
        return_value=mock_provider,
    ):
        monkeypatch.setattr(settings, "llm_default_provider", "openai")
        r = await diag_client.post(
            f"{BASE}/test",
            json={"provider_key": "chat"},
            headers=_auth(admin_ctx["token"]),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert body["error_code"] == "error"
    # Must not expose the raw exception message
    assert "unexpected" not in (body["error_message"] or "")


# ---------------------------------------------------------------------------
# L. POST test — 422 on invalid provider_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_invalid_provider_key(diag_client, admin_ctx) -> None:
    r = await diag_client.post(
        f"{BASE}/test",
        json={"provider_key": "unknown"},
        headers=_auth(admin_ctx["token"]),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# M. Role guard — viewer can GET but cannot POST /test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_can_get_providers(diag_client, viewer_ctx) -> None:
    r = await diag_client.get(BASE, headers=_auth(viewer_ctx["token"]))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_post_test(diag_client, viewer_ctx) -> None:
    r = await diag_client.post(
        f"{BASE}/test",
        json={"provider_key": "chat"},
        headers=_auth(viewer_ctx["token"]),
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# N. Unauthenticated request returns 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_get(diag_client) -> None:
    r = await diag_client.get(BASE)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_post_test(diag_client) -> None:
    r = await diag_client.post(f"{BASE}/test", json={"provider_key": "chat"})
    assert r.status_code == 401
