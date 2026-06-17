"""MCP trust and exposure controls — F176

Backend tests covering:
- Policy API: new trust control fields in PATCH/GET
- MCPTrustService: allowlist enforcement, redaction, payload limits
- Org isolation for trust settings
- Audit event records for policy changes including trust fields
"""

import os
from unittest.mock import MagicMock
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
from app.domains.mcp.trust_service import (
    AllowlistDenied,
    MCPTrustService,
    PayloadTooLarge,
)
from app.main import app
from app.models.enums import OrganizationRole
from app.models.mcp_policy import OrgMCPPolicy
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def admin_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_principal(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
) -> tuple[User, Organization]:
    org = Organization(name=f"Org-{uuid4().hex[:8]}", slug=f"org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Test Admin",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value)
    )
    await db_session.commit()
    return user, org


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


def _make_policy(**overrides: object) -> OrgMCPPolicy:
    defaults = dict(
        id=uuid4(),
        organization_id=uuid4(),
        enabled=True,
        read_only=False,
        allowed_tools=None,
        capabilities_owner=None,
        capabilities_admin=None,
        capabilities_member=None,
        capabilities_viewer=None,
        rate_limit_enabled=True,
        rate_limit_requests=30,
        rate_limit_window_seconds=60,
        allowed_resources=None,
        allowed_prompts=None,
        allowed_collections=None,
        allowed_roles=None,
        redact_document_text=True,
        max_chunk_chars=None,
        max_request_bytes=None,
        max_response_bytes=None,
    )
    defaults.update(overrides)
    mock = MagicMock(spec=OrgMCPPolicy)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock  # type: ignore[return-value]


# ─── API: new trust fields in PATCH/GET ──────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_policy_trust_fields_saved(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    headers = _auth_headers(token=token, organization_id=str(org.id))

    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={
            "allowed_resources": ["rag://documents/*"],
            "allowed_prompts": ["summarize", "explain"],
            "allowed_collections": ["col-abc123"],
            "allowed_roles": ["admin", "owner"],
            "redact_document_text": True,
            "max_chunk_chars": 500,
            "max_request_bytes": 65536,
            "max_response_bytes": 131072,
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed_resources"] == ["rag://documents/*"]
    assert data["allowed_prompts"] == ["summarize", "explain"]
    assert data["allowed_collections"] == ["col-abc123"]
    assert data["allowed_roles"] == ["admin", "owner"]
    assert data["redact_document_text"] is True
    assert data["max_chunk_chars"] == 500
    assert data["max_request_bytes"] == 65536
    assert data["max_response_bytes"] == 131072


@pytest.mark.asyncio
async def test_patch_policy_trust_fields_null_clears_allowlists(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    headers = _auth_headers(token=token, organization_id=str(org.id))

    await admin_client.patch(
        "/admin/mcp/policy",
        json={"allowed_resources": ["rag://documents/*"], "allowed_prompts": ["ask"]},
        headers=headers,
    )
    # Null out the allowlists
    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={"allowed_resources": None, "allowed_prompts": None},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed_resources"] is None
    assert data["allowed_prompts"] is None


@pytest.mark.asyncio
async def test_patch_policy_max_chunk_chars_too_small_rejected(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={"max_chunk_chars": 10},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_policy_max_request_bytes_too_small_rejected(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={"max_request_bytes": 10},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_policy_redact_document_text_false_persists(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    headers = _auth_headers(token=token, organization_id=str(org.id))
    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={"redact_document_text": False},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["redact_document_text"] is False

    get_resp = await admin_client.get("/admin/mcp/policy", headers=headers)
    assert get_resp.json()["redact_document_text"] is False


@pytest.mark.asyncio
async def test_get_policy_trust_defaults(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/mcp/policy",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed_resources"] is None
    assert data["allowed_prompts"] is None
    assert data["allowed_collections"] is None
    assert data["allowed_roles"] is None
    assert data["redact_document_text"] is True
    assert data["max_chunk_chars"] is None
    assert data["max_request_bytes"] is None
    assert data["max_response_bytes"] is None


@pytest.mark.asyncio
async def test_patch_trust_policy_org_isolation(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_principal(db_session, role=OrganizationRole.admin)
    user_b, org_b = await _seed_principal(db_session, role=OrganizationRole.admin)
    token_a = create_app_access_token(
        user_id=str(user_a.id), organization_id=str(org_a.id), role=OrganizationRole.admin.value
    )
    token_b = create_app_access_token(
        user_id=str(user_b.id), organization_id=str(org_b.id), role=OrganizationRole.admin.value
    )

    await admin_client.patch(
        "/admin/mcp/policy",
        json={"allowed_roles": ["owner"], "max_chunk_chars": 200},
        headers=_auth_headers(token=token_a, organization_id=str(org_a.id)),
    )

    resp_b = await admin_client.get(
        "/admin/mcp/policy",
        headers=_auth_headers(token=token_b, organization_id=str(org_b.id)),
    )
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert data_b["allowed_roles"] is None
    assert data_b["max_chunk_chars"] is None


# ─── MCPTrustService unit tests ───────────────────────────────────────────────

def test_trust_check_tool_null_allowlist_permits_all() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_tools=None)
    svc.check_tool_allowed(policy, "any_tool")  # must not raise


def test_trust_check_tool_in_allowlist_permitted() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_tools=["search", "summarize"])
    svc.check_tool_allowed(policy, "search")  # must not raise


def test_trust_check_tool_not_in_allowlist_raises() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_tools=["search"])
    with pytest.raises(AllowlistDenied) as exc_info:
        svc.check_tool_allowed(policy, "delete_document")
    assert exc_info.value.resource_type == "tool"
    assert "delete_document" in str(exc_info.value)


def test_trust_check_resource_exact_match_permitted() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_resources=["rag://documents/abc"])
    svc.check_resource_allowed(policy, "rag://documents/abc")


def test_trust_check_resource_wildcard_prefix_permitted() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_resources=["rag://documents/*"])
    svc.check_resource_allowed(policy, "rag://documents/123/content")


def test_trust_check_resource_not_matching_raises() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_resources=["rag://documents/*"])
    with pytest.raises(AllowlistDenied) as exc_info:
        svc.check_resource_allowed(policy, "rag://secrets/admin")
    assert exc_info.value.resource_type == "resource"


def test_trust_check_role_null_permits_all() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_roles=None)
    svc.check_role_allowed(policy, "viewer")


def test_trust_check_role_not_in_list_raises() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_roles=["owner", "admin"])
    with pytest.raises(AllowlistDenied) as exc_info:
        svc.check_role_allowed(policy, "member")
    assert exc_info.value.resource_type == "role"


def test_trust_redact_chunk_text_replaces_when_no_limit() -> None:
    svc = MCPTrustService()
    policy = _make_policy(redact_document_text=True, max_chunk_chars=None)
    result = svc.redact_chunk_text(policy, "This is raw document content.")
    assert result == "[content redacted by MCP trust policy]"


def test_trust_redact_chunk_text_truncates_at_limit() -> None:
    svc = MCPTrustService()
    policy = _make_policy(redact_document_text=True, max_chunk_chars=10)
    text = "A" * 200
    result = svc.redact_chunk_text(policy, text)
    assert result.startswith("A" * 10)
    assert "truncated" in result


def test_trust_redact_chunk_text_passthrough_when_disabled_within_limit() -> None:
    svc = MCPTrustService()
    policy = _make_policy(redact_document_text=False, max_chunk_chars=500)
    short = "Short text."
    assert svc.redact_chunk_text(policy, short) == short


def test_trust_enforce_request_size_within_limit() -> None:
    svc = MCPTrustService()
    policy = _make_policy(max_request_bytes=1024)
    svc.enforce_request_size(policy, 512)  # must not raise


def test_trust_enforce_request_size_exceeded_raises() -> None:
    svc = MCPTrustService()
    policy = _make_policy(max_request_bytes=256)
    with pytest.raises(PayloadTooLarge) as exc_info:
        svc.enforce_request_size(policy, 300)
    assert exc_info.value.direction == "request"
    assert exc_info.value.size == 300
    assert exc_info.value.limit == 256


def test_trust_enforce_response_size_exceeded_raises() -> None:
    svc = MCPTrustService()
    policy = _make_policy(max_response_bytes=512)
    with pytest.raises(PayloadTooLarge) as exc_info:
        svc.enforce_response_size(policy, 1000)
    assert exc_info.value.direction == "response"


def test_trust_check_collection_allowed() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_collections=["col-public"])
    svc.check_collection_allowed(policy, "col-public")
    with pytest.raises(AllowlistDenied):
        svc.check_collection_allowed(policy, "col-private")


def test_trust_check_prompt_allowed() -> None:
    svc = MCPTrustService()
    policy = _make_policy(allowed_prompts=["summarize"])
    svc.check_prompt_allowed(policy, "summarize")
    with pytest.raises(AllowlistDenied):
        svc.check_prompt_allowed(policy, "jailbreak")
