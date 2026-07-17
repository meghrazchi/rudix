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
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/rag_app")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
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
from app.models.report import ReportEvent
from app.models.user import User


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value
    app.dependency_overrides.clear()


async def seed(db: AsyncSession, role: OrganizationRole) -> tuple[Organization, User, str]:
    org = Organization(name=f"Report {uuid4().hex[:6]}", slug=f"report-{uuid4().hex}")
    db.add(org)
    await db.flush()
    user = User(
        organization_id=org.id, external_auth_id=f"report:{uuid4()}", email=f"{uuid4()}@example.com"
    )
    db.add(user)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db.commit()
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    return org, user, token


def headers(org: Organization, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)}


@pytest.mark.asyncio
async def test_report_contract_aggregates_filters_sorts_and_paginates(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, token = await seed(db_session, OrganizationRole.admin)
    for category, event_type, count, status in (
        ("question", "question.asked", 2, "success"),
        ("indexing", "indexing.completed", 3, "success"),
        ("connector_sync", "connector_sync.failed", 1, "failed"),
    ):
        db_session.add(
            ReportEvent(
                organization_id=org.id,
                user_id=user.id,
                category=category,
                event_type=event_type,
                count=count,
                status=status,
                occurred_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
            )
        )
    await db_session.commit()

    response = await client.get(
        "/api/v1/reports",
        headers=headers(org, token),
        params={
            "from": "2026-07-01T00:00:00Z",
            "to": "2026-07-02T00:00:00Z",
            "page_size": 2,
            "sort": "category",
            "direction": "asc",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "organization_id",
        "generated_at",
        "from_at",
        "to_at",
        "metrics",
        "chart",
        "table",
        "action_items",
        "pagination",
    }
    assert payload["pagination"] == {"page": 1, "page_size": 2, "total": 3, "pages": 2}
    assert payload["table"][0]["category"] == "connector_sync"
    assert payload["action_items"][0]["count"] == 1
    assert all(
        "metadata" not in row and "content" not in row and "snippet" not in row
        for row in payload["table"]
    )


@pytest.mark.asyncio
async def test_report_api_is_tenant_isolated(client: AsyncClient, db_session: AsyncSession) -> None:
    org, user, token = await seed(db_session, OrganizationRole.admin)
    other, other_user, _ = await seed(db_session, OrganizationRole.admin)
    now = datetime.now(tz=UTC)
    db_session.add_all(
        [
            ReportEvent(
                organization_id=org.id,
                user_id=user.id,
                category="audit",
                event_type="audit.read",
                count=1,
                occurred_at=now,
            ),
            ReportEvent(
                organization_id=other.id,
                user_id=other_user.id,
                category="audit",
                event_type="audit.private",
                count=99,
                occurred_at=now,
            ),
        ]
    )
    await db_session.commit()
    response = await client.get("/api/v1/reports", headers=headers(org, token))
    assert response.status_code == 200
    assert response.json()["pagination"]["total"] == 1
    assert response.json()["table"][0]["event_type"] == "audit.read"


@pytest.mark.asyncio
async def test_report_api_rejects_non_admin_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, _user, token = await seed(db_session, OrganizationRole.member)
    response = await client.get("/api/v1/reports", headers=headers(org, token))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_report_event_contract_forbids_private_content(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, _user, token = await seed(db_session, OrganizationRole.admin)
    body = {
        "category": "answer",
        "event_type": "answer.generated",
        "occurred_at": "2026-07-01T12:00:00Z",
        "answer": "private source text",
    }
    response = await client.post("/api/v1/reports/events", headers=headers(org, token), json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_large_report_query_remains_bounded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, token = await seed(db_session, OrganizationRole.admin)
    occurred_at = datetime(2026, 7, 1, 12, tzinfo=UTC)
    db_session.add_all(
        [
            ReportEvent(
                organization_id=org.id,
                user_id=user.id,
                category="question",
                event_type="question.asked",
                count=1,
                occurred_at=occurred_at,
            )
            for _ in range(1_000)
        ]
    )
    await db_session.commit()

    response = await client.get(
        "/api/v1/reports",
        headers=headers(org, token),
        params={
            "from": "2026-07-01T00:00:00Z",
            "to": "2026-07-02T00:00:00Z",
            "page_size": 25,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["total"] == 1_000
    assert len(payload["table"]) == 25
    assert len(payload["chart"]) == 1
