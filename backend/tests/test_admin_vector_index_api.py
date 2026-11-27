"""GET /admin/vector-index/status (R06-08): roles, legacy mode, organisation scoping."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

# Strict settings must load when this module is collected on its own.
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
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.models.vector_index import VectorIndexGeneration, VectorIndexGenerationDocument

pytestmark = [pytest.mark.asyncio, pytest.mark.both_dialects]

ALIAS = "rudix_live_status"
URL = "/api/v1/admin/vector-index/status"


@pytest_asyncio.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http_client:
        yield http_client
    app.dependency_overrides.clear()


async def _seed_org(
    session: AsyncSession, role: OrganizationRole, *, indexed: int, other: int = 0
) -> tuple[Organization, User, list[Document]]:
    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}")
    session.add(org)
    await session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"user-{suffix}",
        email=f"user-{suffix}@example.com",
        display_name="Status User",
    )
    session.add(user)
    await session.flush()
    session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    documents = []
    for index in range(indexed + other):
        document = Document(
            organization_id=org.id,
            uploaded_by_user_id=user.id,
            filename=f"doc-{index}.txt",
            file_type="txt",
            storage_bucket="documents",
            storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
            status="indexed" if index < indexed else "processing",
        )
        session.add(document)
        documents.append(document)
    await session.flush()
    return org, user, documents


async def _seed_generations(session: AsyncSession) -> VectorIndexGeneration:
    session.add(
        VectorIndexGeneration(
            alias_name=ALIAS,
            collection_name=f"oldcoll_{uuid4().hex[:6]}",
            embedding_model="embed-old",
            vector_size=1536,
            distance="cosine",
            generation=1,
            state="active",
            activated_at=datetime(2026, 11, 1, tzinfo=UTC),
        )
    )
    building = VectorIndexGeneration(
        alias_name=ALIAS,
        collection_name=f"secret_internal_{uuid4().hex[:6]}",
        embedding_model="embed-new",
        vector_size=8,
        distance="cosine",
        generation=2,
        state="building",
    )
    session.add(building)
    await session.flush()
    return building


async def _mark_done(
    session: AsyncSession, generation: VectorIndexGeneration, org: UUID, docs: list[Document]
) -> None:
    for document in docs:
        session.add(
            VectorIndexGenerationDocument(
                generation_id=generation.id,
                organization_id=org,
                document_id=document.id,
                point_count=999,
            )
        )
    await session.flush()


def _headers(user: User, org: Organization, role: OrganizationRole) -> dict[str, str]:
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=role.value
    )
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)}


async def test_legacy_mode_reports_the_configured_model(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "qdrant_collection_alias", None)
    org, user, _ = await _seed_org(db_session, OrganizationRole.owner, indexed=1)
    await db_session.commit()

    response = await client.get(URL, headers=_headers(user, org, OrganizationRole.owner))

    assert response.status_code == 200
    body = response.json()
    assert body["legacy_mode"] is True and body["alias"] is None
    assert body["active"]["embedding_model"] == settings.openai_embedding_model
    assert body["active"]["generation"] is None
    assert body["building"] is None and body["progress"] is None


async def test_progress_counts_only_the_callers_organisation(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "qdrant_collection_alias", ALIAS)
    org_a, admin_a, docs_a = await _seed_org(db_session, OrganizationRole.admin, indexed=3, other=1)
    org_b, owner_b, docs_b = await _seed_org(db_session, OrganizationRole.owner, indexed=5)
    building = await _seed_generations(db_session)
    await _mark_done(db_session, building, org_a.id, docs_a[:1])
    await _mark_done(db_session, building, org_b.id, docs_b[:4])
    await db_session.commit()

    response_a = await client.get(URL, headers=_headers(admin_a, org_a, OrganizationRole.admin))
    response_b = await client.get(URL, headers=_headers(owner_b, org_b, OrganizationRole.owner))

    assert response_a.status_code == response_b.status_code == 200
    body_a, body_b = response_a.json(), response_b.json()
    assert body_a["progress"] == {"documents_total": 3, "documents_done": 1}
    assert body_b["progress"] == {"documents_total": 5, "documents_done": 4}
    assert body_a["alias"] == ALIAS and body_a["legacy_mode"] is False
    assert body_a["active"]["generation"] == 1
    assert body_a["active"]["embedding_model"] == "embed-old"
    assert body_a["building"]["generation"] == 2
    assert body_a["building"]["state"] == "building"
    assert body_a["building"]["embedding_model"] == "embed-new"
    # No collection internals or point counts leave the API.
    text = response_a.text
    assert "secret_internal" not in text and "oldcoll_" not in text and "999" not in text
    assert set(body_a) == {"alias", "legacy_mode", "active", "building", "progress"}


async def test_no_building_generation_means_no_progress(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "qdrant_collection_alias", ALIAS)
    org, user, _ = await _seed_org(db_session, OrganizationRole.admin, indexed=2)
    await db_session.commit()

    response = await client.get(URL, headers=_headers(user, org, OrganizationRole.admin))

    assert response.status_code == 200
    body = response.json()
    assert body["active"] is None and body["building"] is None and body["progress"] is None


@pytest.mark.parametrize("role", [OrganizationRole.viewer, OrganizationRole.member])
async def test_lower_roles_are_forbidden(
    client: AsyncClient, db_session: AsyncSession, role: OrganizationRole
) -> None:
    org, user, _ = await _seed_org(db_session, role, indexed=1)
    await db_session.commit()

    response = await client.get(URL, headers=_headers(user, org, role))

    assert response.status_code == 403


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(URL)
    assert response.status_code == 401
