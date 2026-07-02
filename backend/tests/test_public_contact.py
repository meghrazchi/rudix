import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
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

from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.contact import ContactSubmission


@pytest_asyncio.fixture
async def contact_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "email_provider", "console")
    monkeypatch.setattr(settings, "email_from_address", "noreply@example.com")
    monkeypatch.setattr(settings, "email_from_name", "Rudix")

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


def _payload() -> dict[str, object]:
    return {
        "full_name": "Alex Rivera",
        "work_email": "alex@example.com",
        "company": "Acme Legal",
        "role_title": "Head of Knowledge",
        "use_case": "Legal document Q&A",
        "team_size": "51-250",
        "message": "We want a demo focused on citations, retention, and governance.",
        "consent_accepted": True,
        "captcha_token": "captcha-token",
        "source": "public_contact_page",
    }


@pytest.mark.asyncio
async def test_public_contact_submission_sends_email_and_saves_database_row(
    contact_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "email_enabled", True)
    monkeypatch.setattr(settings, "contact_receiver_email", "sales@example.com")

    response = await contact_client.post(
        "/api/v1/contact",
        json=_payload(),
        headers={"x-request-id": "req-contact-1", "user-agent": "contact-test"},
    )

    assert response.status_code == 201
    assert response.json()["email_status"] == "sent"

    submission = (
        await db_session.execute(
            select(ContactSubmission).where(ContactSubmission.work_email == "alex@example.com")
        )
    ).scalar_one()
    assert submission.full_name == "Alex Rivera"
    assert submission.receiver_email == "sales@example.com"
    assert submission.email_status == "sent"
    assert submission.email_provider == "console"
    assert submission.request_id == "req-contact-1"
    assert submission.user_agent == "contact-test"
    assert "retention" in submission.message


@pytest.mark.asyncio
async def test_public_contact_submission_validation_failure_does_not_save(
    contact_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "email_enabled", True)
    monkeypatch.setattr(settings, "contact_receiver_email", "sales@example.com")

    payload = _payload()
    payload["consent_accepted"] = False
    response = await contact_client.post("/api/v1/contact", json=payload)

    assert response.status_code == 422
    count = int((await db_session.execute(select(func.count(ContactSubmission.id)))).scalar_one())
    assert count == 0


@pytest.mark.asyncio
async def test_public_contact_submission_is_saved_when_email_not_configured(
    contact_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "email_enabled", True)
    monkeypatch.setattr(settings, "contact_receiver_email", None)

    response = await contact_client.post("/api/v1/contact", json=_payload())

    assert response.status_code == 503
    submission = (
        await db_session.execute(
            select(ContactSubmission).where(ContactSubmission.work_email == "alex@example.com")
        )
    ).scalar_one()
    assert submission.email_status == "skipped"
    assert submission.email_error == "contact_receiver_email_not_configured"
