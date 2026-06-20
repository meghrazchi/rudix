import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure strict settings can be loaded when importing modules in tests.
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
from app.models.failed_job import FailedJob
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
        display_name="Test Admin",
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


async def _seed_failed_job(
    db_session: AsyncSession,
    *,
    organization_id: object,
    task_name: str = "documents.process",
    job_type: str = "extraction",
    status: str = "failed",
    is_retryable: bool = True,
    attempt_count: int = 1,
    error_code: str | None = "TimeoutError",
    queue_name: str | None = "documents_processing",
) -> FailedJob:
    job = FailedJob(
        id=uuid4(),
        organization_id=organization_id,
        task_id=f"task-{uuid4().hex}",
        task_name=task_name,
        job_type=job_type,
        status=status,
        queue_name=queue_name,
        error_code=error_code,
        error_message="Connection timed out after 30s",
        attempt_count=attempt_count,
        is_retryable=is_retryable,
        entity_type="document",
        entity_id=uuid4(),
        metadata_json={},
        last_attempted_at=datetime.now(tz=UTC),
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    db_session.add(job)
    await db_session.commit()
    return job


# ─── List endpoint ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_failed_jobs_returns_empty_for_new_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/failed-jobs", headers=_auth_headers(token=token, organization_id=str(org.id))
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_list_failed_jobs_returns_org_scoped_results(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    _, other_org = await _seed_principal(db_session, role=OrganizationRole.admin)
    await _seed_failed_job(db_session, organization_id=org.id)
    await _seed_failed_job(db_session, organization_id=org.id)
    await _seed_failed_job(db_session, organization_id=other_org.id)

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/failed-jobs", headers=_auth_headers(token=token, organization_id=str(org.id))
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_failed_jobs_filters_by_job_type(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    await _seed_failed_job(db_session, organization_id=org.id, job_type="extraction")
    await _seed_failed_job(db_session, organization_id=org.id, job_type="reindex")

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/failed-jobs?job_type=extraction",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["job_type"] == "extraction"


@pytest.mark.asyncio
async def test_list_failed_jobs_filters_by_status(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    await _seed_failed_job(db_session, organization_id=org.id, status="failed")
    await _seed_failed_job(db_session, organization_id=org.id, status="resolved")

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/failed-jobs?status=resolved",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["status"] == "resolved"


@pytest.mark.asyncio
async def test_list_failed_jobs_retryable_only_filter(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    await _seed_failed_job(db_session, organization_id=org.id, is_retryable=True)
    await _seed_failed_job(db_session, organization_id=org.id, is_retryable=False)

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/failed-jobs?retryable_only=true",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["is_retryable"] is True


@pytest.mark.asyncio
async def test_list_failed_jobs_requires_admin_role(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    response = await admin_client.get(
        "/admin/failed-jobs", headers=_auth_headers(token=token, organization_id=str(org.id))
    )
    assert response.status_code == 403


# ─── Detail endpoint ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_failed_job_returns_detail(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(db_session, organization_id=org.id)

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        f"/admin/failed-jobs/{job.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(job.id)
    assert data["error_message"] == "Connection timed out after 30s"
    assert "audit_log" in data


@pytest.mark.asyncio
async def test_get_failed_job_not_found_for_other_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    _, other_org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(db_session, organization_id=other_org.id)

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        f"/admin/failed-jobs/{job.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 404


# ─── Retry endpoint ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_failed_job_sets_status_to_retrying(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched: list[str] = []
    monkeypatch.setattr(
        "app.interfaces.http.failed_jobs._dispatch_retry",
        lambda job: dispatched.append(job.task_name),
    )

    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(db_session, organization_id=org.id, status="failed")

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        f"/admin/failed-jobs/{job.id}/retry",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "retrying"
    assert dispatched == ["documents.process"]


@pytest.mark.asyncio
async def test_retry_non_retryable_job_returns_409(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(
        db_session, organization_id=org.id, status="failed", is_retryable=False
    )

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        f"/admin/failed-jobs/{job.id}/retry",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409
    assert "non-retryable" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retry_resolved_job_returns_409(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(db_session, organization_id=org.id, status="resolved")

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        f"/admin/failed-jobs/{job.id}/retry",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_retry_creates_audit_log_entry(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.interfaces.http.failed_jobs._dispatch_retry", lambda job: None)

    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(db_session, organization_id=org.id)

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    await admin_client.post(
        f"/admin/failed-jobs/{job.id}/retry",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    detail_response = await admin_client.get(
        f"/admin/failed-jobs/{job.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    detail = detail_response.json()
    assert len(detail["audit_log"]) == 1
    assert detail["audit_log"][0]["action"] == "retry"


# ─── Bulk retry endpoint ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_retry_queues_eligible_jobs(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched: list[str] = []
    monkeypatch.setattr(
        "app.interfaces.http.failed_jobs._dispatch_retry",
        lambda job: dispatched.append(str(job.id)),
    )

    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job_a = await _seed_failed_job(db_session, organization_id=org.id, status="failed")
    job_b = await _seed_failed_job(
        db_session, organization_id=org.id, status="failed", is_retryable=False
    )

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        "/admin/failed-jobs/bulk-retry",
        json={"job_ids": [str(job_a.id), str(job_b.id)]},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert str(job_a.id) in data["queued"]
    assert str(job_b.id) in data["skipped"]
    assert data["skip_reasons"][str(job_b.id)] == "non_retryable"
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_bulk_retry_skips_jobs_from_other_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.interfaces.http.failed_jobs._dispatch_retry", lambda job: None)

    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    _, other_org = await _seed_principal(db_session, role=OrganizationRole.admin)
    other_job = await _seed_failed_job(db_session, organization_id=other_org.id)

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        "/admin/failed-jobs/bulk-retry",
        json={"job_ids": [str(other_job.id)]},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert str(other_job.id) in data["skipped"]
    assert data["skip_reasons"][str(other_job.id)] == "not_found"


# ─── Cancel endpoint ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_failed_job_sets_status(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(db_session, organization_id=org.id, status="failed")

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        f"/admin/failed-jobs/{job.id}/cancel",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_already_cancelled_job_returns_409(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(db_session, organization_id=org.id, status="cancelled")

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        f"/admin/failed-jobs/{job.id}/cancel",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409


# ─── Resolve endpoint ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_failed_job_sets_status(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(db_session, organization_id=org.id, status="failed")

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        f"/admin/failed-jobs/{job.id}/resolve",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "resolved"
    assert data["resolved_at"] is not None


@pytest.mark.asyncio
async def test_resolve_already_resolved_job_returns_409(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(db_session, organization_id=org.id, status="resolved")

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        f"/admin/failed-jobs/{job.id}/resolve",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409


# ─── Idempotency / safety ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_retryable_deletion_cleanup_job_blocked(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    job = await _seed_failed_job(
        db_session,
        organization_id=org.id,
        task_name="documents.delete",
        job_type="deletion_cleanup",
        is_retryable=False,
        status="failed",
    )

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        f"/admin/failed-jobs/{job.id}/retry",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_pagination_respects_page_size(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    for _ in range(5):
        await _seed_failed_job(db_session, organization_id=org.id)

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/failed-jobs?page_size=2&page=1",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1
