"""API tests for F147: Evaluation dataset builder.

Covers: update, delete, publish, duplicate, import (CSV+JSON), validate,
list versions, PATCH question, DELETE question, and role guards.
"""

import json
import os
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
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.main import app
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def dataset_builder_client(
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


async def _seed_org_and_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.admin,
) -> tuple[User, Organization]:
    org = Organization(name=f"Org-{uuid4().hex[:6]}", slug=f"org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"u-{uuid4().hex[:8]}",
        email=f"u-{uuid4().hex[:8]}@test.com",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, org


async def _seed_document(
    db_session: AsyncSession,
    *,
    organization: Organization,
    uploader: User,
) -> Document:
    repo = DocumentRepository()
    doc = await repo.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename=f"doc-{uuid4().hex[:6]}.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"test/{uuid4().hex}.pdf",
        status=DocumentStatus.indexed.value,
    )
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


def _headers(*, token: str, org_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": org_id,
    }


def _token(user: User, org: Organization) -> str:
    return create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )


# ---------------------------------------------------------------------------
# PATCH /evaluation-sets/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_evaluation_set_name_and_description(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name="Original Name"
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.patch(
        f"/api/v1/evaluation-sets/{evset.id}",
        headers=_headers(token=token, org_id=str(org.id)),
        json={"name": "Updated Name", "description": "New desc"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Updated Name"
    assert payload["description"] == "New desc"
    assert payload["evaluation_set_id"] == str(evset.id)


@pytest.mark.asyncio
async def test_update_evaluation_set_404_for_foreign_org(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    _, other_org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    foreign_set = await repo.create_evaluation_set(
        db_session, organization_id=other_org.id, name="Foreign"
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.patch(
        f"/api/v1/evaluation-sets/{foreign_set.id}",
        headers=_headers(token=token, org_id=str(org.id)),
        json={"name": "Hijack"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /evaluation-sets/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_evaluation_set_removes_record(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="To Delete")
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.delete(
        f"/api/v1/evaluation-sets/{evset.id}",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 204

    result = await repo.get_evaluation_set(
        db_session, evaluation_set_id=evset.id, organization_id=org.id
    )
    assert result is None


@pytest.mark.asyncio
async def test_delete_evaluation_set_rejects_viewer(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    viewer, org = await _seed_org_and_user(db_session, role=OrganizationRole.viewer)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="No Del")
    await db_session.commit()

    token = _token(viewer, org)
    response = await dataset_builder_client.delete(
        f"/api/v1/evaluation-sets/{evset.id}",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /evaluation-sets/{id}/publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_dataset_creates_version_and_sets_status(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Draft Set")
    await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="What is the refund policy?"
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.post(
        f"/api/v1/evaluation-sets/{evset.id}/publish",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "published"
    assert payload["question_count"] == 1
    assert payload["version_number"] >= 1

    versions_response = await dataset_builder_client.get(
        f"/api/v1/evaluation-sets/{evset.id}/versions",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert versions_response.status_code == 200
    versions_payload = versions_response.json()
    assert versions_payload["total"] == 1
    assert versions_payload["items"][0]["question_count"] == 1


@pytest.mark.asyncio
async def test_publish_dataset_rejects_empty_set(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Empty")
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.post(
        f"/api/v1/evaluation-sets/{evset.id}/publish",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 409
    assert "no questions" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /evaluation-sets/{id}/duplicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_dataset_copies_questions(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Source Set")
    await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Q1", difficulty="easy"
    )
    await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Q2", difficulty="hard"
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.post(
        f"/api/v1/evaluation-sets/{evset.id}/duplicate",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 201
    payload = response.json()
    assert "copy" in payload["name"].lower()
    assert payload["question_count"] == 2
    assert payload["status"] == "draft"
    assert payload["evaluation_set_id"] != str(evset.id)


# ---------------------------------------------------------------------------
# POST /evaluation-sets/{id}/import  (JSON format)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_json_cases_persists_questions(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Import JSON")
    await db_session.commit()

    cases = json.dumps(
        [
            {"question": "What is RAG?", "expected_answer": "Retrieval Augmented Generation"},
            {"question": "Define chunking.", "difficulty": "hard", "tags": "nlp,search"},
            {"question": "What is embeddings?"},
        ]
    )

    token = _token(user, org)
    response = await dataset_builder_client.post(
        f"/api/v1/evaluation-sets/{evset.id}/import",
        headers=_headers(token=token, org_id=str(org.id)),
        json={"format": "json", "data": cases, "skip_duplicates": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == 3
    assert payload["skipped_duplicates"] == 0

    count = await repo.count_evaluation_questions(db_session, evaluation_set_id=evset.id)
    assert count == 3


@pytest.mark.asyncio
async def test_import_json_skips_duplicates(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name="Dedup Import"
    )
    await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Existing question"
    )
    await db_session.commit()

    cases = json.dumps(
        [
            {"question": "Existing question"},
            {"question": "New question"},
        ]
    )

    token = _token(user, org)
    response = await dataset_builder_client.post(
        f"/api/v1/evaluation-sets/{evset.id}/import",
        headers=_headers(token=token, org_id=str(org.id)),
        json={"format": "json", "data": cases, "skip_duplicates": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == 1
    assert payload["skipped_duplicates"] == 1


@pytest.mark.asyncio
async def test_import_csv_cases_persists_questions(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Import CSV")
    await db_session.commit()

    csv_data = "question,expected_answer,difficulty\nWhat is AI?,A machine that thinks,easy\nExplain neural nets.,,medium"

    token = _token(user, org)
    response = await dataset_builder_client.post(
        f"/api/v1/evaluation-sets/{evset.id}/import",
        headers=_headers(token=token, org_id=str(org.id)),
        json={"format": "csv", "data": csv_data, "skip_duplicates": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == 2
    assert payload["skipped_duplicates"] == 0


@pytest.mark.asyncio
async def test_import_invalid_json_returns_errors(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Bad JSON")
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.post(
        f"/api/v1/evaluation-sets/{evset.id}/import",
        headers=_headers(token=token, org_id=str(org.id)),
        json={"format": "json", "data": "not json at all {{"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /evaluation-sets/{id}/validate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_clean_dataset_returns_valid(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name="Clean Dataset"
    )
    await repo.create_evaluation_question(
        db_session,
        evaluation_set_id=evset.id,
        question="What is retrieval augmented generation?",
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.get(
        f"/api/v1/evaluation-sets/{evset.id}/validate",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_valid"] is True
    assert payload["issue_count"] == 0
    assert payload["issues"] == []


@pytest.mark.asyncio
async def test_validate_detects_duplicate_questions(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name="Duplicate Dataset"
    )
    await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Same question"
    )
    await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Same question"
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.get(
        f"/api/v1/evaluation-sets/{evset.id}/validate",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_valid"] is False
    assert payload["issue_count"] >= 1
    issue_types = {issue["issue_type"] for issue in payload["issues"]}
    assert "duplicate" in issue_types


# ---------------------------------------------------------------------------
# GET /evaluation-sets/{id}/versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_versions_empty_before_publish(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="No Versions")
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.get(
        f"/api/v1/evaluation-sets/{evset.id}/versions",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0


# ---------------------------------------------------------------------------
# PATCH /evaluation-sets/{id}/questions/{qid}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_question_changes_fields(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Update Q")
    question = await repo.create_evaluation_question(
        db_session,
        evaluation_set_id=evset.id,
        question="Original question",
        difficulty="easy",
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.patch(
        f"/api/v1/evaluation-sets/{evset.id}/questions/{question.id}",
        headers=_headers(token=token, org_id=str(org.id)),
        json={
            "question": "Updated question",
            "difficulty": "hard",
            "expected_answer": "42",
            "tags": ["updated", "tag"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == "Updated question"
    assert payload["difficulty"] == "hard"
    assert payload["expected_answer"] == "42"
    assert "updated" in payload["tags"]


@pytest.mark.asyncio
async def test_update_question_returns_404_for_wrong_set(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    set_a = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Set A")
    set_b = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Set B")
    question = await repo.create_evaluation_question(
        db_session, evaluation_set_id=set_a.id, question="Q in set A"
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.patch(
        f"/api/v1/evaluation-sets/{set_b.id}/questions/{question.id}",
        headers=_headers(token=token, org_id=str(org.id)),
        json={"question": "Should fail"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /evaluation-sets/{id}/questions/{qid}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_question_removes_record(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Del Q")
    question = await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Delete me"
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.delete(
        f"/api/v1/evaluation-sets/{evset.id}/questions/{question.id}",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 204

    count = await repo.count_evaluation_questions(db_session, evaluation_set_id=evset.id)
    assert count == 0


@pytest.mark.asyncio
async def test_delete_question_404_for_nonexistent(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Del 404")
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.delete(
        f"/api/v1/evaluation-sets/{evset.id}/questions/{uuid4()}",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Role guard: member cannot publish or delete sets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_cannot_publish_dataset(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    member, org = await _seed_org_and_user(db_session, role=OrganizationRole.member)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Member Pub")
    await repo.create_evaluation_question(db_session, evaluation_set_id=evset.id, question="Q")
    await db_session.commit()

    token = _token(member, org)
    response = await dataset_builder_client.post(
        f"/api/v1/evaluation-sets/{evset.id}/publish",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_delete_dataset(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    member, org = await _seed_org_and_user(db_session, role=OrganizationRole.member)
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Member Del")
    await db_session.commit()

    token = _token(member, org)
    response = await dataset_builder_client.delete(
        f"/api/v1/evaluation-sets/{evset.id}",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_cannot_target_foreign_set(
    dataset_builder_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    _, other_org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    foreign_set = await repo.create_evaluation_set(
        db_session, organization_id=other_org.id, name="Foreign"
    )
    await db_session.commit()

    token = _token(user, org)
    response = await dataset_builder_client.post(
        f"/api/v1/evaluation-sets/{foreign_set.id}/import",
        headers=_headers(token=token, org_id=str(org.id)),
        json={"format": "json", "data": json.dumps([{"question": "Injected Q"}])},
    )
    assert response.status_code == 404
