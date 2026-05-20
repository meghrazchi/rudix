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
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app")
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
from app.domains.pipeline.repositories.pipeline import PipelineRepository
from app.main import app
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


pipeline_repository = PipelineRepository()


@pytest_asyncio.fixture
async def pipeline_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
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
    role: OrganizationRole = OrganizationRole.member,
) -> tuple[User, Organization, Organization]:
    primary_org = Organization(name="Pipeline Primary", slug=f"pipeline-primary-{uuid4().hex[:8]}")
    secondary_org = Organization(name="Pipeline Secondary", slug=f"pipeline-secondary-{uuid4().hex[:8]}")
    db_session.add_all([primary_org, secondary_org])
    await db_session.flush()

    user = User(
        organization_id=primary_org.id,
        external_auth_id=f"pipeline-user-{uuid4().hex[:8]}",
        email=f"pipeline-{uuid4().hex[:8]}@example.com",
        display_name="Pipeline API User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=primary_org.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, primary_org, secondary_org


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


async def _seed_document(
    db_session: AsyncSession,
    *,
    organization_id,
    uploaded_by_user_id,
    suffix: str,
) -> Document:
    document = Document(
        organization_id=organization_id,
        uploaded_by_user_id=uploaded_by_user_id,
        filename=f"pipeline-{suffix}.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"uploads/{suffix}.pdf",
        status="indexed",
    )
    db_session.add(document)
    await db_session.flush()
    return document


@pytest.mark.asyncio
async def test_pipeline_run_graph_returns_nodes_edges_and_canonical_type(
    pipeline_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    started_at = datetime.now(UTC)
    run = await pipeline_repository.create_pipeline_run(
        db_session,
        organization_id=organization.id,
        pipeline_type="document.reindex",
        status="running",
        started_at=started_at,
        inputs={"document_id": "doc-123"},
        config={"index_version": "v1"},
    )
    await pipeline_repository.create_pipeline_event(
        db_session,
        pipeline_run_id=run.id,
        sequence=0,
        node_name="extract",
        status="started",
        started_at=started_at,
        inputs={"source": "pdf"},
    )
    await pipeline_repository.create_pipeline_event(
        db_session,
        pipeline_run_id=run.id,
        sequence=1,
        node_name="extract",
        status="completed",
        started_at=started_at,
        completed_at=started_at,
        duration_ms=15,
        outputs={"metrics": {"page_count": 3}},
    )
    await pipeline_repository.create_pipeline_event(
        db_session,
        pipeline_run_id=run.id,
        sequence=2,
        node_name="chunk",
        status="completed",
        started_at=started_at,
        completed_at=started_at,
        duration_ms=25,
        outputs={"metrics": {"chunk_count": 9}},
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await pipeline_client.get(
        f"/api/v1/pipeline/runs/{run.id}",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipeline_run_id"] == str(run.id)
    assert payload["pipeline_type"] == "document.process"
    assert payload["status"] == "running"
    assert [node["id"] for node in payload["nodes"]] == ["extract", "chunk"]
    assert payload["nodes"][0]["section"] == "ingestion"
    assert payload["nodes"][0]["status"] == "completed"
    assert payload["nodes"][0]["metrics"]["page_count"] == 3
    assert payload["edges"] == [{"id": "extract->chunk:0", "source": "extract", "target": "chunk"}]


@pytest.mark.asyncio
async def test_pipeline_run_graph_hides_cross_organization_run(
    pipeline_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, other_organization = await _seed_principal(db_session)
    foreign_run = await pipeline_repository.create_pipeline_run(
        db_session,
        organization_id=other_organization.id,
        pipeline_type="document.process",
        status="running",
        started_at=datetime.now(UTC),
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await pipeline_client.get(
        f"/api/v1/pipeline/runs/{foreign_run.id}",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Pipeline run not found"


@pytest.mark.asyncio
async def test_pipeline_node_detail_returns_latest_node_event(
    pipeline_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    started_at = datetime.now(UTC)
    run = await pipeline_repository.create_pipeline_run(
        db_session,
        organization_id=organization.id,
        pipeline_type="document.process",
        status="failed",
        started_at=started_at,
    )
    await pipeline_repository.create_pipeline_event(
        db_session,
        pipeline_run_id=run.id,
        sequence=0,
        node_name="embed",
        status="started",
        started_at=started_at,
        inputs={"embedding_model": "text-embedding-3-small"},
    )
    await pipeline_repository.create_pipeline_event(
        db_session,
        pipeline_run_id=run.id,
        sequence=1,
        node_name="embed",
        status="failed",
        started_at=started_at,
        completed_at=started_at,
        duration_ms=42,
        outputs={"metrics": {"batch_count": 2}},
        logs=["timeout while calling embeddings api"],
        error_message="Embedding provider timeout",
        error_details={"code": "EMBED_TIMEOUT"},
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await pipeline_client.get(
        f"/api/v1/pipeline/runs/{run.id}/nodes/embed",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == "embed"
    assert payload["title"] == "Embed"
    assert payload["status"] == "failed"
    assert payload["inputs"]["embedding_model"] == "text-embedding-3-small"
    assert payload["metrics"]["batch_count"] == 2
    assert payload["error_message"] == "Embedding provider timeout"
    assert payload["error_details"]["code"] == "EMBED_TIMEOUT"
    assert payload["duration_ms"] == 42


@pytest.mark.asyncio
async def test_pipeline_node_detail_returns_404_for_unknown_node(
    pipeline_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    run = await pipeline_repository.create_pipeline_run(
        db_session,
        organization_id=organization.id,
        pipeline_type="document.process",
        status="running",
        started_at=datetime.now(UTC),
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await pipeline_client.get(
        f"/api/v1/pipeline/runs/{run.id}/nodes/unknown-node",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Pipeline node not found"


@pytest.mark.asyncio
async def test_pipeline_run_resolve_by_document_id_returns_latest_match(
    pipeline_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    document = await _seed_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=user.id,
        suffix=uuid4().hex[:8],
    )
    first_run = await pipeline_repository.create_pipeline_run(
        db_session,
        organization_id=organization.id,
        pipeline_type="document.process",
        status="completed",
        document_id=document.id,
        started_at=datetime.now(UTC),
    )
    second_run = await pipeline_repository.create_pipeline_run(
        db_session,
        organization_id=organization.id,
        pipeline_type="document.reindex",
        status="running",
        document_id=document.id,
        started_at=datetime.now(UTC),
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await pipeline_client.get(
        "/api/v1/pipeline/runs/resolve",
        params={
            "run_type": "document.process",
            "document_id": str(document.id),
        },
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipeline_run_id"] == str(second_run.id)
    assert payload["pipeline_type"] == "document.process"
    assert payload["status"] == "running"
    assert payload["pipeline_run_id"] != str(first_run.id)


@pytest.mark.asyncio
async def test_pipeline_run_resolve_hides_cross_organization_context(
    pipeline_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, other_organization = await _seed_principal(db_session)
    foreign_user = User(
        organization_id=other_organization.id,
        external_auth_id=f"pipeline-foreign-{uuid4().hex[:8]}",
        email=f"pipeline-foreign-{uuid4().hex[:8]}@example.com",
        display_name="Pipeline Foreign User",
    )
    db_session.add(foreign_user)
    await db_session.flush()

    foreign_document = await _seed_document(
        db_session,
        organization_id=other_organization.id,
        uploaded_by_user_id=foreign_user.id,
        suffix=uuid4().hex[:8],
    )
    await pipeline_repository.create_pipeline_run(
        db_session,
        organization_id=other_organization.id,
        pipeline_type="document.process",
        status="completed",
        document_id=foreign_document.id,
        started_at=datetime.now(UTC),
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await pipeline_client.get(
        "/api/v1/pipeline/runs/resolve",
        params={
            "run_type": "document.process",
            "document_id": str(foreign_document.id),
        },
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Pipeline run not found"
