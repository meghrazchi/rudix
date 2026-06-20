"""Backend tests for F220: Model profiles, provider policy, configuration precedence.

Covers:
  A. GET /model-profiles — empty list when no profiles configured
  B. PUT /model-profiles/{task_type} — create a profile for a task type
  C. GET /model-profiles/{task_type} — retrieve the profile
  D. PUT /model-profiles/{task_type} — update an existing profile bumps version
  E. DELETE /model-profiles/{task_type} — removes profile, next GET → 404
  F. GET /model-profiles/effective — env_default when no org profiles
  G. GET /model-profiles/effective — org_profile source when profile exists
  H. POST /model-profiles/validate — valid profile returns valid=True, no issues
  I. POST /model-profiles/validate — json_mode_required for evaluations task
  J. POST /model-profiles/validate — local provider blocked when flag off
  K. POST /model-profiles/validate — experimental blocked when flag off
  L. PUT /model-profiles/{task_type} — 422 when validation fails
  M. Role guards — viewer cannot PUT or DELETE
  N. Org isolation — org A profiles not visible to org B
  O. Change-log entry written on create
  P. Change-log entry written on delete
  Q. Fallback key must differ from provider_type
  R. Embeddings task with json_mode=true rejected
  S. Precedence: feature flags exposed in effective policy response
  T. All six task types accepted by PUT endpoint

Run:
    pytest tests/test_model_profiles_f220.py -v
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
from app.domains.ai.profile.schemas import TaskType, ValidateProfileRequest
from app.domains.ai.profile.service import validate_profile
from app.main import app
from app.models.enums import OrganizationRole
from app.models.model_profile import OrgModelProfileChangeLog
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
    org = Organization(name="Profile Org", slug=f"prof-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"prof-admin-{uuid4().hex[:6]}@test.com", display_name="Admin")
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


_VALID_CHAT_PAYLOAD = {
    "profile_name": "Default Chat",
    "provider_type": "openai",
    "base_model": "gpt-4o",
    "json_mode": False,
    "streaming": True,
}

_VALID_EVAL_PAYLOAD = {
    "profile_name": "Eval Profile",
    "provider_type": "openai",
    "base_model": "gpt-4o",
    "json_mode": True,
    "streaming": False,
}

BASE = "/api/v1/model-profiles"


# ---------------------------------------------------------------------------
# A. List profiles — empty initially
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_profiles_empty(mp_client, admin_ctx) -> None:
    r = await mp_client.get(BASE, headers=_auth(admin_ctx["token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


# ---------------------------------------------------------------------------
# B. PUT creates profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_creates_chat_profile(mp_client, admin_ctx) -> None:
    r = await mp_client.put(
        f"{BASE}/chat",
        json=_VALID_CHAT_PAYLOAD,
        headers=_auth(admin_ctx["token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_type"] == "chat"
    assert body["provider_type"] == "openai"
    assert body["base_model"] == "gpt-4o"
    assert body["version"] == 1


# ---------------------------------------------------------------------------
# C. GET retrieves profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_chat_profile(mp_client, admin_ctx) -> None:
    await mp_client.put(f"{BASE}/chat", json=_VALID_CHAT_PAYLOAD, headers=_auth(admin_ctx["token"]))
    r = await mp_client.get(f"{BASE}/chat", headers=_auth(admin_ctx["token"]))
    assert r.status_code == 200
    assert r.json()["task_type"] == "chat"


# ---------------------------------------------------------------------------
# D. PUT updates — version bumps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_update_bumps_version(mp_client, admin_ctx) -> None:
    await mp_client.put(f"{BASE}/chat", json=_VALID_CHAT_PAYLOAD, headers=_auth(admin_ctx["token"]))
    updated = {**_VALID_CHAT_PAYLOAD, "base_model": "gpt-4o-mini", "profile_name": "Updated"}
    r = await mp_client.put(f"{BASE}/chat", json=updated, headers=_auth(admin_ctx["token"]))
    assert r.status_code == 200
    assert r.json()["version"] == 2
    assert r.json()["base_model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# E. DELETE removes profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_profile(mp_client, admin_ctx) -> None:
    await mp_client.put(f"{BASE}/chat", json=_VALID_CHAT_PAYLOAD, headers=_auth(admin_ctx["token"]))
    r = await mp_client.delete(f"{BASE}/chat", headers=_auth(admin_ctx["token"]))
    assert r.status_code == 204
    r2 = await mp_client.get(f"{BASE}/chat", headers=_auth(admin_ctx["token"]))
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# F. Effective policy — env_default when no profiles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_policy_all_env_default(mp_client, admin_ctx) -> None:
    r = await mp_client.get(f"{BASE}/effective", headers=_auth(admin_ctx["token"]))
    assert r.status_code == 200
    body = r.json()
    assert all(p["source"] == "env_default" for p in body["profiles"])
    assert len(body["profiles"]) == 6  # all TaskType values


# ---------------------------------------------------------------------------
# G. Effective policy — org_profile source when profile exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_policy_org_profile_source(mp_client, admin_ctx) -> None:
    await mp_client.put(f"{BASE}/chat", json=_VALID_CHAT_PAYLOAD, headers=_auth(admin_ctx["token"]))
    r = await mp_client.get(f"{BASE}/effective", headers=_auth(admin_ctx["token"]))
    body = r.json()
    chat = next(p for p in body["profiles"] if p["task_type"] == "chat")
    assert chat["source"] == "org_profile"
    others = [p for p in body["profiles"] if p["task_type"] != "chat"]
    assert all(p["source"] == "env_default" for p in others)


# ---------------------------------------------------------------------------
# H. Validate — valid payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_valid_profile(mp_client, admin_ctx) -> None:
    r = await mp_client.post(
        f"{BASE}/validate",
        json={"task_type": "chat", "provider_type": "openai", "base_model": "gpt-4o"},
        headers=_auth(admin_ctx["token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["issues"] == []


# ---------------------------------------------------------------------------
# I. Validate — json_mode required for evaluations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_json_mode_required_for_evaluations(mp_client, admin_ctx) -> None:
    r = await mp_client.post(
        f"{BASE}/validate",
        json={
            "task_type": "evaluations",
            "provider_type": "openai",
            "base_model": "gpt-4o",
            "json_mode": False,
        },
        headers=_auth(admin_ctx["token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    codes = [i["code"] for i in body["issues"]]
    assert "json_mode_required" in codes


# ---------------------------------------------------------------------------
# J. Validate — local provider blocked when flag off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_local_llm_blocked_when_flag_off(monkeypatch, mp_client, admin_ctx) -> None:
    monkeypatch.setattr(settings, "feature_enable_local_llm_profiles", False)
    r = await mp_client.post(
        f"{BASE}/validate",
        json={"task_type": "chat", "provider_type": "local", "base_model": "llama3"},
        headers=_auth(admin_ctx["token"]),
    )
    body = r.json()
    assert body["valid"] is False
    assert any(i["code"] == "local_llm_disabled" for i in body["issues"])


# ---------------------------------------------------------------------------
# K. Validate — experimental blocked when flag off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_experimental_blocked_when_flag_off(
    monkeypatch, mp_client, admin_ctx
) -> None:
    monkeypatch.setattr(settings, "feature_enable_experimental_profiles", False)
    r = await mp_client.post(
        f"{BASE}/validate",
        json={
            "task_type": "evaluations",
            "provider_type": "openai",
            "base_model": "gpt-4o",
            "json_mode": True,
            "is_experimental": True,
        },
        headers=_auth(admin_ctx["token"]),
    )
    body = r.json()
    assert body["valid"] is False
    assert any(i["code"] == "experimental_profiles_disabled" for i in body["issues"])


# ---------------------------------------------------------------------------
# L. PUT — 422 when validation fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_rejects_invalid_profile(mp_client, admin_ctx) -> None:
    payload = {
        "profile_name": "Bad Eval",
        "provider_type": "openai",
        "base_model": "gpt-4o",
        "json_mode": False,  # evaluations requires json_mode=True
    }
    r = await mp_client.put(f"{BASE}/evaluations", json=payload, headers=_auth(admin_ctx["token"]))
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# M. Role guards — viewer cannot PUT or DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_cannot_put_profile(mp_client, viewer_ctx) -> None:
    r = await mp_client.put(
        f"{BASE}/chat",
        json=_VALID_CHAT_PAYLOAD,
        headers=_auth(viewer_ctx["token"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_delete_profile(mp_client, viewer_ctx) -> None:
    r = await mp_client.delete(f"{BASE}/chat", headers=_auth(viewer_ctx["token"]))
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# N. Org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_isolation(mp_client, admin_ctx, db_session) -> None:
    other_org = Organization(name="Other Org", slug=f"other-{uuid4().hex[:8]}")
    db_session.add(other_org)
    await db_session.flush()
    other_user = User(email=f"other-{uuid4().hex[:6]}@test.com", display_name="Other")
    db_session.add(other_user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=other_org.id,
            user_id=other_user.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db_session.flush()
    other_token = _make_token(str(other_user.id), str(other_org.id))

    # Create profile in org A
    await mp_client.put(f"{BASE}/chat", json=_VALID_CHAT_PAYLOAD, headers=_auth(admin_ctx["token"]))

    # Org B should see empty list
    r = await mp_client.get(BASE, headers=_auth(other_token))
    assert r.status_code == 200
    assert r.json()["total"] == 0


# ---------------------------------------------------------------------------
# O. Change log written on create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_log_written_on_create(mp_client, admin_ctx, db_session) -> None:
    from sqlalchemy import select

    await mp_client.put(f"{BASE}/chat", json=_VALID_CHAT_PAYLOAD, headers=_auth(admin_ctx["token"]))
    result = await db_session.execute(
        select(OrgModelProfileChangeLog).where(OrgModelProfileChangeLog.task_type == "chat")
    )
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].version_number == 1


# ---------------------------------------------------------------------------
# P. Change log written on delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_log_written_on_delete(mp_client, admin_ctx, db_session) -> None:
    from sqlalchemy import select

    await mp_client.put(f"{BASE}/chat", json=_VALID_CHAT_PAYLOAD, headers=_auth(admin_ctx["token"]))
    await mp_client.delete(f"{BASE}/chat", headers=_auth(admin_ctx["token"]))
    result = await db_session.execute(
        select(OrgModelProfileChangeLog).where(OrgModelProfileChangeLog.task_type == "chat")
    )
    entries = result.scalars().all()
    # Create + delete = 2 entries
    assert len(entries) == 2
    snapshots = {e.version_number: e.profile_snapshot for e in entries}
    assert snapshots[2].get("_action") == "deleted"


# ---------------------------------------------------------------------------
# Q. Fallback key must differ from provider_type (schema-level)
# ---------------------------------------------------------------------------


def test_upsert_request_fallback_same_as_provider_rejected() -> None:
    from pydantic import ValidationError

    from app.domains.ai.profile.schemas import UpsertModelProfileRequest

    with pytest.raises(ValidationError, match="fallback_provider_key must differ"):
        UpsertModelProfileRequest(
            profile_name="test",
            provider_type="openai",
            base_model="gpt-4o",
            fallback_provider_key="openai",
        )


# ---------------------------------------------------------------------------
# R. Embeddings task with json_mode=true rejected
# ---------------------------------------------------------------------------


def test_validate_json_mode_invalid_for_embeddings() -> None:
    result = validate_profile(
        ValidateProfileRequest(
            task_type=TaskType.embeddings,
            provider_type="openai",
            base_model="text-embedding-3-small",
            json_mode=True,
        )
    )
    assert result.valid is False
    assert any(i.code == "json_mode_invalid_for_embeddings" for i in result.issues)


# ---------------------------------------------------------------------------
# S. Feature flags exposed in effective policy response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_policy_exposes_feature_flags(monkeypatch, mp_client, admin_ctx) -> None:
    monkeypatch.setattr(settings, "feature_enable_local_llm_profiles", True)
    monkeypatch.setattr(settings, "feature_enable_provider_fallback", True)
    r = await mp_client.get(f"{BASE}/effective", headers=_auth(admin_ctx["token"]))
    body = r.json()
    assert body["feature_local_llm_enabled"] is True
    assert body["feature_fallback_enabled"] is True


# ---------------------------------------------------------------------------
# T. All six task types accepted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_task_types_accepted(mp_client, admin_ctx) -> None:
    task_payloads = {
        "chat": _VALID_CHAT_PAYLOAD,
        "summarization": _VALID_CHAT_PAYLOAD,
        "comparison": {**_VALID_EVAL_PAYLOAD, "profile_name": "Comparison"},
        "embeddings": {
            "profile_name": "Embeddings",
            "provider_type": "openai",
            "base_model": "text-embedding-3-small",
            "json_mode": False,
            "streaming": False,
        },
        "evaluations": _VALID_EVAL_PAYLOAD,
        "agentic": _VALID_CHAT_PAYLOAD,
    }
    for task_type, payload in task_payloads.items():
        r = await mp_client.put(
            f"{BASE}/{task_type}",
            json={**payload, "profile_name": f"{task_type} Profile"},
            headers=_auth(admin_ctx["token"]),
        )
        assert r.status_code == 200, f"Failed for task_type={task_type}: {r.text}"
        assert r.json()["task_type"] == task_type
