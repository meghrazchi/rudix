import os
from uuid import uuid4

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

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.admin.repositories.usage import UsageRepository
from app.main import app
from app.models.api_key import ApiKey
from app.models.chat import ChatMessage, ChatSession
from app.models.collection import Collection
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.evaluation import EvaluationQuestion, EvaluationSet
from app.models.metadata import MetadataField
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.models.webhook import Webhook


@pytest_asyncio.fixture
async def portability_client(
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


async def _seed_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
) -> tuple[User, Organization]:
    organization = Organization(name="Portability Org", slug=f"portability-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()
    user = User(
        organization_id=organization.id,
        external_auth_id=f"portable-user-{uuid4().hex[:8]}",
        email=f"portable-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, organization


def _headers(user: User, organization: Organization) -> dict[str, str]:
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(organization.id)}


async def _seed_export_data(
    db_session: AsyncSession,
    *,
    user: User,
    organization: Organization,
) -> None:
    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=user.id,
        filename="policy.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="uploads/private/policy.pdf",
        status="indexed",
        retention_class="legal_hold",
        checksum="sha256-export",
    )
    collection = Collection(
        organization_id=organization.id,
        owner_id=user.id,
        name="Legal Hold",
        description="Portable collection",
        access_policy="org_wide",
    )
    chat_session = ChatSession(
        organization_id=organization.id,
        user_id=user.id,
        title="Policy review",
    )
    dataset = EvaluationSet(
        organization_id=organization.id,
        name="Policy eval",
        description="Evaluation dataset",
        owner_id=user.id,
    )
    db_session.add_all([document, collection, chat_session, dataset])
    await db_session.flush()
    db_session.add_all(
        [
            ChatMessage(
                chat_session_id=chat_session.id,
                role="user",
                content="Does the policy mention api_key=secret-token?",
            ),
            EvaluationQuestion(
                evaluation_set_id=dataset.id,
                question="What is the retention class?",
                expected_answer="legal hold",
                owner_id=user.id,
            ),
            ApiKey(
                organization_id=organization.id,
                name="CI key",
                key_prefix="rudix_test",
                key_hash="hash-must-not-export",
                scopes=["documents:read"],
                created_by_id=user.id,
            ),
            Webhook(
                organization_id=organization.id,
                name="Events",
                url="https://hooks.example.com/rudix",
                secret_prefix="whsec_prefix",
                secret_hash="webhook-secret-hash",
                event_types=["document.indexed"],
                created_by_id=user.id,
            ),
        ]
    )
    await UsageRepository().create_audit_log(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        action="api.key.created",
        resource_type="api_key",
        metadata={"authorization": "Bearer private-token", "status_code": 201},
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_admin_can_export_and_download_sanitized_artifact(
    portability_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_user(db_session, role=OrganizationRole.admin)
    await _seed_export_data(db_session, user=user, organization=organization)

    response = await portability_client.post(
        "/api/v1/admin/portability/exports",
        headers=_headers(user, organization),
        json={
            "sections": [
                "collections",
                "document_metadata",
                "chat_transcripts",
                "audit_logs",
                "api_metadata",
                "webhook_metadata",
            ],
            "max_rows_per_section": 50,
        },
    )

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "completed"
    assert job["download_available"] is True

    download = await portability_client.get(
        f"/api/v1/admin/portability/jobs/{job['job_id']}/download",
        headers=_headers(user, organization),
    )
    assert download.status_code == 200
    artifact_text = download.text
    artifact = download.json()
    assert artifact["schema_version"] == "rudix.workspace_export.v1"
    assert "storage_object_key" not in artifact_text
    assert "hash-must-not-export" not in artifact_text
    assert "webhook-secret-hash" not in artifact_text
    assert "whsec_prefix" not in artifact_text
    assert "private-token" not in artifact_text
    assert "api_key=***" in artifact_text
    assert (
        artifact["sections"]["document_metadata"]["documents"][0]["retention_class"] == "legal_hold"
    )


@pytest.mark.asyncio
async def test_member_cannot_request_workspace_export(
    portability_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_user(db_session, role=OrganizationRole.member)
    response = await portability_client.post(
        "/api/v1/admin/portability/exports",
        headers=_headers(user, organization),
        json={"sections": ["collections"]},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_import_validation_runs_before_processing(
    portability_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_user(db_session, role=OrganizationRole.admin)
    response = await portability_client.post(
        "/api/v1/admin/portability/imports",
        headers=_headers(user, organization),
        json={
            "apply": True,
            "artifact": {
                "schema_version": "rudix.workspace_export.v1",
                "sections": {"collections": {"items": [{"description": "missing name"}]}},
            },
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "validation_failed"
    assert payload["validation_errors"][0]["path"] == "items[0].name"

    count = int(
        (
            await db_session.execute(
                select(func.count(Collection.id)).where(
                    Collection.organization_id == organization.id
                )
            )
        ).scalar_one()
    )
    assert count == 0


@pytest.mark.asyncio
async def test_import_validation_rejects_malformed_numeric_fields_before_processing(
    portability_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_user(db_session, role=OrganizationRole.admin)
    response = await portability_client.post(
        "/api/v1/admin/portability/imports",
        headers=_headers(user, organization),
        json={
            "apply": True,
            "artifact": {
                "schema_version": "rudix.workspace_export.v1",
                "sections": {
                    "document_metadata": {
                        "fields": [
                            {
                                "name": "department",
                                "field_type": "text",
                                "sort_order": "later",
                            }
                        ]
                    },
                    "evaluation_datasets": {
                        "items": [
                            {
                                "name": "Broken Eval",
                                "questions": [
                                    {
                                        "question": "What does the policy say?",
                                        "expected_page_number": "front",
                                    }
                                ],
                            }
                        ]
                    },
                },
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "validation_failed"
    assert {issue["path"] for issue in payload["validation_errors"]} == {
        "fields[0].sort_order",
        "items[0].questions[0].expected_page_number",
    }

    field_count = int(
        (
            await db_session.execute(
                select(func.count(MetadataField.id)).where(
                    MetadataField.organization_id == organization.id
                )
            )
        ).scalar_one()
    )
    dataset_count = int(
        (
            await db_session.execute(
                select(func.count(EvaluationSet.id)).where(
                    EvaluationSet.organization_id == organization.id
                )
            )
        ).scalar_one()
    )
    assert field_count == 0
    assert dataset_count == 0


@pytest.mark.asyncio
async def test_import_apply_creates_safe_records_without_documents(
    portability_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_user(db_session, role=OrganizationRole.admin)
    artifact = {
        "schema_version": "rudix.workspace_export.v1",
        "sections": {
            "collections": {
                "items": [
                    {
                        "name": "Imported Collection",
                        "description": "Portable",
                        "access_policy": "org_wide",
                    }
                ]
            },
            "document_metadata": {
                "fields": [
                    {
                        "name": "department",
                        "display_name": "Department",
                        "field_type": "text",
                    }
                ],
                "documents": [
                    {
                        "filename": "manifest-only.pdf",
                        "file_type": "pdf",
                        "retention_class": "legal_hold",
                    }
                ],
            },
            "evaluation_datasets": {
                "items": [
                    {
                        "name": "Imported Eval",
                        "questions": [{"question": "What does the policy say?"}],
                    }
                ]
            },
        },
    }

    response = await portability_client.post(
        "/api/v1/admin/portability/imports",
        headers=_headers(user, organization),
        json={"apply": True, "artifact": artifact},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "completed"
    assert any(w["code"] == "manifest_only" for w in payload["warnings"])

    collection_count = int(
        (
            await db_session.execute(
                select(func.count(Collection.id)).where(
                    Collection.organization_id == organization.id
                )
            )
        ).scalar_one()
    )
    field_count = int(
        (
            await db_session.execute(
                select(func.count(MetadataField.id)).where(
                    MetadataField.organization_id == organization.id
                )
            )
        ).scalar_one()
    )
    dataset_count = int(
        (
            await db_session.execute(
                select(func.count(EvaluationSet.id)).where(
                    EvaluationSet.organization_id == organization.id
                )
            )
        ).scalar_one()
    )
    document_count = int(
        (
            await db_session.execute(
                select(func.count(Document.id)).where(Document.organization_id == organization.id)
            )
        ).scalar_one()
    )
    assert collection_count == 1
    assert field_count == 1
    assert dataset_count == 1
    assert document_count == 0
