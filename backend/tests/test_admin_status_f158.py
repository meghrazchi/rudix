import os
from datetime import UTC, datetime
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
from app.models.incident import Incident, IncidentNote
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

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
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
        display_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, org


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


async def _seed_incident(
    db_session: AsyncSession,
    *,
    organization_id: object,
    title: str = "Test incident",
    status: str = "investigating",
    severity: str = "medium",
    is_public: bool = False,
    resolved_at: datetime | None = None,
) -> Incident:
    now = datetime.now(tz=UTC)
    incident = Incident(
        id=uuid4(),
        organization_id=organization_id,
        title=title,
        status=status,
        severity=severity,
        affected_services=["search", "chat"],
        message="Something is broken.",
        is_public=is_public,
        started_at=now,
        resolved_at=resolved_at,
        created_at=now,
        updated_at=now,
    )
    db_session.add(incident)
    await db_session.commit()
    return incident


# ─── GET /admin/status ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_snapshot_returns_active_incidents(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    await _seed_incident(db_session, organization_id=org.id, status="investigating")
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.get(
        "/admin/status", headers=_auth_headers(token=token, organization_id=str(org.id))
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["active_incidents"]) == 1
    assert data["banner"]["has_active_incident"] is True


@pytest.mark.asyncio
async def test_status_snapshot_no_incidents(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.get(
        "/admin/status", headers=_auth_headers(token=token, organization_id=str(org.id))
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_incidents"] == []
    assert data["banner"]["has_active_incident"] is False
    assert data["banner"]["active_incident_count"] == 0


@pytest.mark.asyncio
async def test_status_snapshot_member_forbidden(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.member.value,
    )
    resp = await admin_client.get(
        "/admin/status", headers=_auth_headers(token=token, organization_id=str(org.id))
    )
    assert resp.status_code == 403


# ─── GET /status/banner ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_banner_returns_false_when_no_public_incidents(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    await _seed_incident(
        db_session, organization_id=org.id, status="investigating", is_public=False
    )
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.member.value,
    )
    resp = await admin_client.get(
        "/status/banner",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_active_incident"] is False


@pytest.mark.asyncio
async def test_banner_returns_true_for_public_incident(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    await _seed_incident(
        db_session,
        organization_id=org.id,
        status="investigating",
        is_public=True,
        severity="critical",
    )
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.member.value,
    )
    resp = await admin_client.get(
        "/status/banner",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_active_incident"] is True
    assert data["active_incident_count"] == 1
    assert data["highest_severity"] == "critical"


# ─── GET /admin/incidents ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_incidents_empty(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.get(
        "/admin/incidents",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_incidents_scoped_to_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    _, other_org = await _seed_principal(db_session, role=OrganizationRole.admin)
    await _seed_incident(db_session, organization_id=org.id)
    await _seed_incident(db_session, organization_id=other_org.id)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.get(
        "/admin/incidents",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_list_incidents_filter_active_only(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    await _seed_incident(db_session, organization_id=org.id, status="investigating")
    await _seed_incident(
        db_session,
        organization_id=org.id,
        status="resolved",
        resolved_at=datetime.now(tz=UTC),
    )
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.get(
        "/admin/incidents?active_only=true",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["status"] == "investigating"


# ─── POST /admin/incidents ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_incident_sets_defaults(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.post(
        "/admin/incidents",
        json={"title": "API outage", "severity": "high", "is_public": True},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "API outage"
    assert data["status"] == "investigating"
    assert data["severity"] == "high"
    assert data["is_public"] is True
    assert len(data["notes"]) == 1
    assert data["notes"][0]["status_change"] == "investigating"


@pytest.mark.asyncio
async def test_create_incident_member_forbidden(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.member.value,
    )
    resp = await admin_client.post(
        "/admin/incidents",
        json={"title": "Test"},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 403


# ─── GET /admin/incidents/{id} ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_incident_returns_detail_with_notes(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    incident = await _seed_incident(db_session, organization_id=org.id)
    note = IncidentNote(
        id=uuid4(),
        incident_id=incident.id,
        organization_id=org.id,
        note="Engineers are looking into this.",
        status_change=None,
        created_at=datetime.now(tz=UTC),
    )
    db_session.add(note)
    await db_session.commit()

    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.get(
        f"/admin/incidents/{incident.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(incident.id)
    assert len(data["notes"]) == 1
    assert data["notes"][0]["note"] == "Engineers are looking into this."


@pytest.mark.asyncio
async def test_get_incident_404_for_wrong_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    _, other_org = await _seed_principal(db_session, role=OrganizationRole.admin)
    incident = await _seed_incident(db_session, organization_id=other_org.id)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.get(
        f"/admin/incidents/{incident.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 404


# ─── PATCH /admin/incidents/{id} ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_incident_status_creates_audit_note(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    incident = await _seed_incident(db_session, organization_id=org.id)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.patch(
        f"/admin/incidents/{incident.id}",
        json={"status": "identified"},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "identified"
    status_notes = [n for n in data["notes"] if n["status_change"] == "identified"]
    assert len(status_notes) == 1


@pytest.mark.asyncio
async def test_update_incident_resolved_sets_resolved_at(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    incident = await _seed_incident(db_session, organization_id=org.id)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.patch(
        f"/admin/incidents/{incident.id}",
        json={"status": "resolved"},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resolved"
    assert data["resolved_at"] is not None


# ─── POST /admin/incidents/{id}/notes ────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_note_without_status_change(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    incident = await _seed_incident(db_session, organization_id=org.id)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.post(
        f"/admin/incidents/{incident.id}/notes",
        json={"note": "Engineers are on-call and investigating."},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 201
    data = resp.json()
    user_notes = [n for n in data["notes"] if "on-call" in n["note"]]
    assert len(user_notes) == 1
    assert data["status"] == "investigating"


@pytest.mark.asyncio
async def test_add_note_with_status_change_updates_incident(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    incident = await _seed_incident(db_session, organization_id=org.id)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.post(
        f"/admin/incidents/{incident.id}/notes",
        json={"note": "Root cause identified.", "status_change": "identified"},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "identified"
    notes_with_change = [n for n in data["notes"] if n["status_change"] == "identified"]
    assert len(notes_with_change) == 1


@pytest.mark.asyncio
async def test_add_note_404_for_wrong_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    _, other_org = await _seed_principal(db_session, role=OrganizationRole.admin)
    incident = await _seed_incident(db_session, organization_id=other_org.id)
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=OrganizationRole.admin.value,
    )
    resp = await admin_client.post(
        f"/admin/incidents/{incident.id}/notes",
        json={"note": "Should not work."},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 404
