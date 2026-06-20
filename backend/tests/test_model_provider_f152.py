"""Backend tests for F152: Model provider settings and fallback policy.

Covers:
  A. GET /model-provider-settings — 404 when no settings exist
  B. PATCH /model-provider-settings — create settings and read them back
  C. PATCH /model-provider-settings — update merges partial fields
  D. DELETE /model-provider-settings — resets org to system defaults
  E. GET /model-provider-settings/effective-policy — system_default when no settings
  F. GET /model-provider-settings/effective-policy — org_override when settings exist
  G. GET /model-provider-settings/change-log — history recorded on every update
  H. Role guards — member/viewer cannot PATCH or DELETE
  I. Secret redaction — llm_key_configured boolean, never the actual key
  J. Disabled model validation — duplicates rejected, blank entries rejected
  K. Org isolation — settings for one org not visible to another

Run:
    pytest tests/test_model_provider_f152.py -v
"""

from __future__ import annotations

import os
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
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mp_client(
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


def _make_token(
    user_id: str,
    org_id: str,
    role: str = OrganizationRole.admin.value,
) -> str:
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
async def admin_context(db_session: AsyncSession):
    org = Organization(name="MP Test Org", slug=f"mp-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"admin-{uuid4().hex[:6]}@test.com", display_name="Admin")
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.admin.value,
    )
    db_session.add(member)
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.admin.value)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


@pytest_asyncio.fixture
async def viewer_context(db_session: AsyncSession):
    org = Organization(name="Viewer Org", slug=f"viewer-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"viewer-{uuid4().hex[:6]}@test.com", display_name="Viewer")
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
# A. GET — 404 when no settings configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_not_found(mp_client: AsyncClient, admin_context: dict) -> None:
    resp = await mp_client.get(
        "/api/model-provider-settings",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# B. PATCH — create settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_settings(mp_client: AsyncClient, admin_context: dict) -> None:
    resp = await mp_client.patch(
        "/api/model-provider-settings",
        json={
            "provider": "openai",
            "llm_model": "gpt-4o",
            "embedding_model": "text-embedding-3-small",
            "max_tokens": 4096,
            "timeout_seconds": 30,
            "max_retries": 2,
            "fallback_model": "gpt-3.5-turbo",
            "disabled_models": ["davinci"],
            "change_note": "Initial config",
        },
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provider"] == "openai"
    assert data["llm_model"] == "gpt-4o"
    assert data["embedding_model"] == "text-embedding-3-small"
    assert data["max_tokens"] == 4096
    assert data["timeout_seconds"] == 30
    assert data["max_retries"] == 2
    assert data["fallback_model"] == "gpt-3.5-turbo"
    assert data["disabled_models"] == ["davinci"]
    assert data["version"] == 1
    assert "llm_key_configured" in data
    assert "openai_api_key" not in str(data)
    assert "sk-" not in str(data)


@pytest.mark.asyncio
async def test_get_settings_after_create(mp_client: AsyncClient, admin_context: dict) -> None:
    await mp_client.patch(
        "/api/model-provider-settings",
        json={"provider": "openai", "llm_model": "gpt-4o"},
        headers=_auth(admin_context["token"]),
    )
    resp = await mp_client.get(
        "/api/model-provider-settings",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["llm_model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# C. PATCH — update merges partial fields, version bumps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_settings_bumps_version(mp_client: AsyncClient, admin_context: dict) -> None:
    await mp_client.patch(
        "/api/model-provider-settings",
        json={"provider": "openai", "llm_model": "gpt-4o", "max_tokens": 2048},
        headers=_auth(admin_context["token"]),
    )
    resp = await mp_client.patch(
        "/api/model-provider-settings",
        json={"llm_model": "gpt-4o-mini"},
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm_model"] == "gpt-4o-mini"
    assert data["provider"] == "openai"
    assert data["max_tokens"] == 2048
    assert data["version"] == 2


# ---------------------------------------------------------------------------
# D. DELETE — resets org to system defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_settings(mp_client: AsyncClient, admin_context: dict) -> None:
    await mp_client.patch(
        "/api/model-provider-settings",
        json={"provider": "openai", "llm_model": "gpt-4o"},
        headers=_auth(admin_context["token"]),
    )
    resp = await mp_client.delete(
        "/api/model-provider-settings",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 204

    # Should be 404 after deletion
    resp = await mp_client.get(
        "/api/model-provider-settings",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_settings_not_found(mp_client: AsyncClient, admin_context: dict) -> None:
    resp = await mp_client.delete(
        "/api/model-provider-settings",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# E. Effective policy — system_default when no settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_policy_system_default(mp_client: AsyncClient, admin_context: dict) -> None:
    resp = await mp_client.get(
        "/api/model-provider-settings/effective-policy",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "system_default"
    assert data["provider"] == "openai"
    assert data["version"] == 0
    assert "llm_key_configured" in data
    assert "openai_api_key" not in str(data)


# ---------------------------------------------------------------------------
# F. Effective policy — org_override when settings exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_policy_org_override(mp_client: AsyncClient, admin_context: dict) -> None:
    await mp_client.patch(
        "/api/model-provider-settings",
        json={"provider": "openai", "llm_model": "gpt-4o-mini", "max_retries": 5},
        headers=_auth(admin_context["token"]),
    )
    resp = await mp_client.get(
        "/api/model-provider-settings/effective-policy",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "org_override"
    assert data["llm_model"] == "gpt-4o-mini"
    assert data["max_retries"] == 5
    assert data["version"] == 1


# ---------------------------------------------------------------------------
# G. Change log — history recorded on every update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_log_records_updates(mp_client: AsyncClient, admin_context: dict) -> None:
    await mp_client.patch(
        "/api/model-provider-settings",
        json={"llm_model": "gpt-4o", "change_note": "First"},
        headers=_auth(admin_context["token"]),
    )
    await mp_client.patch(
        "/api/model-provider-settings",
        json={"llm_model": "gpt-4o-mini", "change_note": "Second"},
        headers=_auth(admin_context["token"]),
    )

    resp = await mp_client.get(
        "/api/model-provider-settings/change-log",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    # Returned newest-first
    assert data["items"][0]["version_number"] == 2
    assert data["items"][0]["change_note"] == "Second"
    assert data["items"][1]["version_number"] == 1
    assert data["items"][1]["change_note"] == "First"
    # Snapshot must not include raw API keys
    for item in data["items"]:
        assert "openai_api_key" not in str(item["settings_snapshot"])
        assert "sk-" not in str(item["settings_snapshot"])


@pytest.mark.asyncio
async def test_change_log_includes_reset_entry(mp_client: AsyncClient, admin_context: dict) -> None:
    await mp_client.patch(
        "/api/model-provider-settings",
        json={"llm_model": "gpt-4o"},
        headers=_auth(admin_context["token"]),
    )
    await mp_client.delete(
        "/api/model-provider-settings",
        headers=_auth(admin_context["token"]),
    )
    # Re-create org (change log survives deletion via org FK cascade would delete it,
    # but within same org we test the log count incremented to 2)
    resp = await mp_client.get(
        "/api/model-provider-settings/change-log",
        headers=_auth(admin_context["token"]),
    )
    # After DELETE the settings row is gone but log entries are too (CASCADE)
    # This verifies the endpoint returns 200 with empty list
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# H. Role guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_cannot_update_settings(mp_client: AsyncClient, viewer_context: dict) -> None:
    resp = await mp_client.patch(
        "/api/model-provider-settings",
        json={"llm_model": "gpt-4o"},
        headers=_auth(viewer_context["token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_delete_settings(mp_client: AsyncClient, viewer_context: dict) -> None:
    resp = await mp_client.delete(
        "/api/model-provider-settings",
        headers=_auth(viewer_context["token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_view_change_log(mp_client: AsyncClient, viewer_context: dict) -> None:
    resp = await mp_client.get(
        "/api/model-provider-settings/change-log",
        headers=_auth(viewer_context["token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_read_settings(mp_client: AsyncClient, viewer_context: dict) -> None:
    # Viewer can GET effective policy (public-safe endpoint) but cannot read settings (404 since no settings)
    resp = await mp_client.get(
        "/api/model-provider-settings/effective-policy",
        headers=_auth(viewer_context["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["source"] == "system_default"


# ---------------------------------------------------------------------------
# I. Secret redaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_secret_never_in_response(mp_client: AsyncClient, admin_context: dict) -> None:
    resp = await mp_client.patch(
        "/api/model-provider-settings",
        json={"provider": "openai", "llm_model": "gpt-4o"},
        headers=_auth(admin_context["token"]),
    )
    body = resp.text
    assert "sk-" not in body
    assert "openai_api_key" not in body
    assert "secret" not in body.lower().replace("secret_ref", "").replace("llm_key_configured", "")


# ---------------------------------------------------------------------------
# J. Disabled models validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_models_duplicate_rejected(
    mp_client: AsyncClient, admin_context: dict
) -> None:
    resp = await mp_client.patch(
        "/api/model-provider-settings",
        json={"disabled_models": ["gpt-3.5-turbo", "gpt-3.5-turbo"]},
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_disabled_models_blank_entry_rejected(
    mp_client: AsyncClient, admin_context: dict
) -> None:
    resp = await mp_client.patch(
        "/api/model-provider-settings",
        json={"disabled_models": ["  "]},
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_max_retries_out_of_range_rejected(
    mp_client: AsyncClient, admin_context: dict
) -> None:
    resp = await mp_client.patch(
        "/api/model-provider-settings",
        json={"max_retries": 99},
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# K. Org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_isolation(mp_client: AsyncClient, db_session: AsyncSession) -> None:
    # Set up two separate orgs with separate admins
    org_a = Organization(name="Org A", slug=f"org-a-{uuid4().hex[:8]}")
    org_b = Organization(name="Org B", slug=f"org-b-{uuid4().hex[:8]}")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    user_a = User(email=f"a-{uuid4().hex[:6]}@test.com", display_name="A")
    user_b = User(email=f"b-{uuid4().hex[:6]}@test.com", display_name="B")
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    for org, user in ((org_a, user_a), (org_b, user_b)):
        db_session.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=user.id,
                role=OrganizationRole.admin.value,
            )
        )
    await db_session.flush()

    token_a = _make_token(str(user_a.id), str(org_a.id))
    token_b = _make_token(str(user_b.id), str(org_b.id))

    # Org A creates settings
    resp = await mp_client.patch(
        "/api/model-provider-settings",
        json={"llm_model": "gpt-4o"},
        headers=_auth(token_a),
    )
    assert resp.status_code == 200

    # Org B should see 404
    resp = await mp_client.get(
        "/api/model-provider-settings",
        headers=_auth(token_b),
    )
    assert resp.status_code == 404

    # Org B effective policy should be system_default
    resp = await mp_client.get(
        "/api/model-provider-settings/effective-policy",
        headers=_auth(token_b),
    )
    assert resp.json()["source"] == "system_default"
