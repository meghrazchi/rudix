from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
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

from app.core.config import settings
from app.db.session import get_db_session
from app.main import app
from app.models.incident import Incident
from app.models.organization import Organization


@pytest_asyncio.fixture
async def public_client(db_session: AsyncSession) -> AsyncClient:
    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_public_org(db_session: AsyncSession) -> Organization:
    organization = Organization(
        name="Public Status Org",
        slug=f"public-status-{uuid4().hex[:8]}",
    )
    db_session.add(organization)
    await db_session.commit()
    await db_session.refresh(organization)
    return organization


async def _seed_incident(
    db_session: AsyncSession,
    *,
    organization_id: object,
    title: str,
    status: str,
    severity: str,
    affected_services: list[str] | None = None,
    started_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> Incident:
    now = datetime.now(tz=UTC)
    incident = Incident(
        id=uuid4(),
        organization_id=organization_id,
        title=title,
        status=status,
        severity=severity,
        affected_services=affected_services or [],
        message=f"{title} update",
        is_public=True,
        started_at=started_at or now,
        resolved_at=resolved_at,
        created_at=now,
        updated_at=now,
    )
    db_session.add(incident)
    await db_session.commit()
    return incident


@pytest.mark.asyncio
async def test_public_status_defaults_to_operational_when_no_public_incidents(
    public_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = await _seed_public_org(db_session)
    monkeypatch.setattr(settings, "public_status_organization_slug", organization.slug)

    response = await public_client.get(f"{settings.api_prefix}/status")

    assert response.status_code == 200
    data = response.json()
    assert data["overall_status"] == "operational"
    assert data["current_incidents"] == []
    assert data["scheduled_maintenance"] == []
    assert data["recent_history"] == []
    assert "organization_id" not in data


@pytest.mark.asyncio
async def test_public_status_reports_degraded_current_incident(
    public_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = await _seed_public_org(db_session)
    monkeypatch.setattr(settings, "public_status_organization_slug", organization.slug)

    await _seed_incident(
        db_session,
        organization_id=organization.id,
        title="API latency increase",
        status="investigating",
        severity="medium",
        affected_services=["api"],
    )

    response = await public_client.get(f"{settings.api_prefix}/status")

    assert response.status_code == 200
    data = response.json()
    assert data["overall_status"] == "degraded"
    assert len(data["current_incidents"]) == 1
    assert data["current_incidents"][0]["kind"] == "incident"
    api_component = next(component for component in data["components"] if component["key"] == "api")
    assert api_component["status"] == "degraded"


@pytest.mark.asyncio
async def test_public_status_reports_maintenance_and_recent_history(
    public_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = await _seed_public_org(db_session)
    monkeypatch.setattr(settings, "public_status_organization_slug", organization.slug)

    now = datetime.now(tz=UTC)
    await _seed_incident(
        db_session,
        organization_id=organization.id,
        title="Scheduled maintenance",
        status="monitoring",
        severity="low",
        affected_services=[],
        started_at=now - timedelta(hours=1),
    )
    await _seed_incident(
        db_session,
        organization_id=organization.id,
        title="Search outage",
        status="resolved",
        severity="high",
        affected_services=["answering"],
        started_at=now - timedelta(days=1),
        resolved_at=now - timedelta(hours=4),
    )

    response = await public_client.get(f"{settings.api_prefix}/status")

    assert response.status_code == 200
    data = response.json()
    assert data["overall_status"] == "maintenance"
    assert len(data["scheduled_maintenance"]) == 1
    assert data["scheduled_maintenance"][0]["kind"] == "maintenance"
    assert len(data["recent_history"]) == 1
    assert data["recent_history"][0]["title"] == "Search outage"
