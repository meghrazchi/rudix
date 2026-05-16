import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
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
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.main import app
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.evaluation import EvaluationQuestion
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def evaluation_sets_client(
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
    role: OrganizationRole = OrganizationRole.member,
) -> tuple[User, Organization, Organization]:
    primary_org = Organization(name="Eval Primary", slug=f"eval-primary-{uuid4().hex[:8]}")
    secondary_org = Organization(name="Eval Secondary", slug=f"eval-secondary-{uuid4().hex[:8]}")
    db_session.add_all([primary_org, secondary_org])
    await db_session.flush()

    user = User(
        organization_id=primary_org.id,
        external_auth_id=f"eval-user-{uuid4().hex[:8]}",
        email=f"eval-{uuid4().hex[:8]}@example.com",
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


async def _seed_user_for_org(
    db_session: AsyncSession,
    *,
    organization: Organization,
    role: OrganizationRole = OrganizationRole.member,
) -> User:
    user = User(
        organization_id=organization.id,
        external_auth_id=f"eval-org-user-{uuid4().hex[:8]}",
        email=f"eval-org-{uuid4().hex[:8]}@example.com",
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
    return user


async def _seed_document(
    db_session: AsyncSession,
    *,
    organization: Organization,
    uploader: User,
    filename: str,
) -> Document:
    repository = DocumentRepository()
    document = await repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename=filename,
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/{filename}-{uuid4().hex}.pdf",
        status=DocumentStatus.indexed.value,
    )
    await db_session.commit()
    await db_session.refresh(document)
    return document


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest.mark.asyncio
async def test_create_evaluation_set_persists_record(
    evaluation_sets_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await evaluation_sets_client.post(
        "/api/v1/evaluation-sets",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={"name": "HR policy set", "description": "Evaluation questions for HR docs"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "HR policy set"
    assert payload["description"] == "Evaluation questions for HR docs"
    assert payload["question_count"] == 0

    repository = EvaluationRepository()
    created_sets = await repository.list_evaluation_sets(
        db_session,
        organization_id=organization.id,
        limit=10,
        offset=0,
    )
    assert len(created_sets) == 1
    assert str(created_sets[0].id) == payload["evaluation_set_id"]


@pytest.mark.asyncio
async def test_create_evaluation_set_rejects_viewer_role(
    evaluation_sets_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session, role=OrganizationRole.viewer)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await evaluation_sets_client.post(
        "/api/v1/evaluation-sets",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={"name": "viewer cannot create"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role for requested operation"


@pytest.mark.asyncio
async def test_list_evaluation_sets_scoped_to_organization_with_question_counts(
    evaluation_sets_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = EvaluationRepository()
    user, organization, other_organization = await _seed_principal(db_session, role=OrganizationRole.member)
    other_user = await _seed_user_for_org(db_session, organization=other_organization)

    own_set_old = await repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Own Set Old",
        description=None,
    )
    own_set_new = await repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Own Set New",
        description=None,
    )
    _ = await repository.create_evaluation_set(
        db_session,
        organization_id=other_organization.id,
        name="Foreign Set",
        description=None,
    )
    await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=own_set_new.id,
        question="What is the leave policy?",
    )
    await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=own_set_new.id,
        question="What is the probation period?",
    )
    await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=own_set_old.id,
        question="How many sick days exist?",
    )
    _ = await _seed_document(
        db_session,
        organization=other_organization,
        uploader=other_user,
        filename="foreign.pdf",
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await evaluation_sets_client.get(
        "/api/v1/evaluation-sets",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={"limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 10
    assert payload["offset"] == 0
    assert len(payload["items"]) == 2
    counts_by_id = {item["evaluation_set_id"]: item["question_count"] for item in payload["items"]}
    assert counts_by_id[str(own_set_old.id)] == 1
    assert counts_by_id[str(own_set_new.id)] == 2


@pytest.mark.asyncio
async def test_create_evaluation_question_validates_expected_document_access(
    evaluation_sets_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = EvaluationRepository()
    user, organization, other_organization = await _seed_principal(db_session, role=OrganizationRole.admin)
    other_user = await _seed_user_for_org(db_session, organization=other_organization)

    evaluation_set = await repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Access Validation Set",
        description=None,
    )
    allowed_document = await _seed_document(
        db_session,
        organization=organization,
        uploader=user,
        filename="allowed.pdf",
    )
    foreign_document = await _seed_document(
        db_session,
        organization=other_organization,
        uploader=other_user,
        filename="foreign.pdf",
    )

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    allowed_response = await evaluation_sets_client.post(
        f"/api/v1/evaluation-sets/{evaluation_set.id}/questions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "question": "What does the handbook state?",
            "expected_answer": "Handbook says X",
            "expected_document_id": str(allowed_document.id),
            "expected_page_number": 2,
            "tags": ["hr", "policy"],
            "metadata": {"difficulty": "easy"},
        },
    )

    assert allowed_response.status_code == 201
    allowed_payload = allowed_response.json()
    assert allowed_payload["evaluation_set_id"] == str(evaluation_set.id)
    assert allowed_payload["expected_document_id"] == str(allowed_document.id)
    assert allowed_payload["expected_page_number"] == 2
    assert allowed_payload["tags"] == ["hr", "policy"]
    assert allowed_payload["metadata"] == {"difficulty": "easy"}

    response = await evaluation_sets_client.post(
        f"/api/v1/evaluation-sets/{evaluation_set.id}/questions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "question": "Should fail",
            "expected_document_id": str(foreign_document.id),
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_list_evaluation_questions_scoped_to_set_and_paginates(
    evaluation_sets_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = EvaluationRepository()
    user, organization, other_organization = await _seed_principal(db_session, role=OrganizationRole.member)
    other_user = await _seed_user_for_org(db_session, organization=other_organization)

    own_set = await repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Own Questions Set",
        description=None,
    )
    _ = await repository.create_evaluation_set(
        db_session,
        organization_id=other_organization.id,
        name="Other Org Set",
        description=None,
    )
    await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=own_set.id,
        question="Q1",
        metadata={"tags": ["a"]},
    )
    await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=own_set.id,
        question="Q2",
        metadata={"tags": ["b"], "priority": "high"},
    )
    await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=own_set.id,
        question="Q3",
        metadata={"tags": []},
    )
    foreign_set = await repository.create_evaluation_set(
        db_session,
        organization_id=other_organization.id,
        name="Foreign Questions Set",
        description=None,
    )
    await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=foreign_set.id,
        question="Foreign Q",
    )
    _ = await _seed_document(
        db_session,
        organization=other_organization,
        uploader=other_user,
        filename="irrelevant.pdf",
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await evaluation_sets_client.get(
        f"/api/v1/evaluation-sets/{own_set.id}/questions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={"limit": 2, "offset": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluation_set_id"] == str(own_set.id)
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert len(payload["items"]) == 2
    returned_questions = {item["question"] for item in payload["items"]}
    assert returned_questions.issubset({"Q1", "Q2", "Q3"})
    assert "Foreign Q" not in returned_questions

    full_response = await evaluation_sets_client.get(
        f"/api/v1/evaluation-sets/{own_set.id}/questions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={"limit": 10, "offset": 0},
    )
    assert full_response.status_code == 200
    full_items = full_response.json()["items"]
    q2_item = next(item for item in full_items if item["question"] == "Q2")
    assert q2_item["tags"] == ["b"]
    assert q2_item["metadata"] == {"priority": "high"}

    foreign_response = await evaluation_sets_client.get(
        f"/api/v1/evaluation-sets/{foreign_set.id}/questions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert foreign_response.status_code == 404
    assert foreign_response.json()["detail"] == "Evaluation set not found"


@pytest.mark.asyncio
async def test_create_question_rejects_blank_question(
    evaluation_sets_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = EvaluationRepository()
    user, organization, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    evaluation_set = await repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Validation Set",
        description=None,
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await evaluation_sets_client.post(
        f"/api/v1/evaluation-sets/{evaluation_set.id}/questions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={"question": "   "},
    )

    assert response.status_code == 422

    result = await db_session.execute(
        select(EvaluationQuestion).where(EvaluationQuestion.evaluation_set_id == evaluation_set.id)
    )
    assert list(result.scalars().all()) == []
