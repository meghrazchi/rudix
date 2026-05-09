import os
from typing import Any
from uuid import UUID, uuid4

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

from app.api import evaluations as evaluations_api
from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.document import Document
from app.models.enums import DocumentStatus, EvaluationRunStatus, OrganizationRole
from app.models.evaluation import EvaluationRun
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.repositories.documents import DocumentRepository
from app.repositories.evaluations import EvaluationRepository


class FakeTaskResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class FakeRunEvaluationTask:
    def __init__(self) -> None:
        self.delay_calls: list[dict[str, Any]] = []
        self.fail_delay = False

    def delay(self, evaluation_run_id: str, **kwargs: Any) -> FakeTaskResult:
        if self.fail_delay:
            raise RuntimeError("enqueue failure")
        self.delay_calls.append({"evaluation_run_id": evaluation_run_id, **kwargs})
        return FakeTaskResult(task_id=f"eval-task-{len(self.delay_calls)}")


@pytest_asyncio.fixture
async def evaluations_run_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "evaluation_prevent_duplicate_active_runs", True)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def fake_run_evaluation_task(monkeypatch: pytest.MonkeyPatch) -> FakeRunEvaluationTask:
    fake = FakeRunEvaluationTask()
    monkeypatch.setattr(evaluations_api, "run_evaluation_task", fake)
    return fake


async def _seed_org_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
    slug_prefix: str,
) -> tuple[User, Organization]:
    org = Organization(name=f"{slug_prefix}-org", slug=f"{slug_prefix}-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"{slug_prefix}-user-{uuid4().hex[:8]}",
        email=f"{slug_prefix}-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, org


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


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest.mark.asyncio
async def test_run_evaluation_queues_run_and_persists_config(
    evaluations_run_client: AsyncClient,
    db_session: AsyncSession,
    fake_run_evaluation_task: FakeRunEvaluationTask,
) -> None:
    evaluation_repository = EvaluationRepository()
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, slug_prefix="eval-run-admin")
    document = await _seed_document(db_session, organization=org, uploader=user, filename="local.pdf")
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=org.id,
        name="Run Set",
    )
    await db_session.commit()

    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)
    response = await evaluations_run_client.post(
        "/api/v1/evaluations/run",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={
            "evaluation_set_id": str(evaluation_set.id),
            "config": {
                "top_k": 7,
                "rerank": False,
                "model_name": "gpt-5.4-mini",
                "selected_document_ids": [str(document.id)],
                "metric_options": {"faithfulness": True},
            },
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    run_id = payload["evaluation_run_id"]

    assert len(fake_run_evaluation_task.delay_calls) == 1
    delay_call = fake_run_evaluation_task.delay_calls[0]
    assert delay_call["evaluation_run_id"] == run_id
    assert delay_call["organization_id"] == str(org.id)
    assert delay_call["user_id"] == str(user.id)

    created_run = await evaluation_repository.get_evaluation_run(
        db_session,
        evaluation_run_id=UUID(run_id),
    )
    assert created_run is not None
    assert created_run.status == EvaluationRunStatus.queued.value
    assert created_run.config["top_k"] == 7
    assert created_run.config["rerank"] is False
    assert created_run.config["model_name"] == "gpt-5.4-mini"
    assert created_run.config["selected_document_ids"] == [str(document.id)]
    assert created_run.config["metric_options"] == {"faithfulness": True}


@pytest.mark.asyncio
async def test_run_evaluation_rejects_invalid_evaluation_set(
    evaluations_run_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, slug_prefix="eval-run-invalid-set")
    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)

    response = await evaluations_run_client.post(
        "/api/v1/evaluations/run",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"evaluation_set_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Evaluation set not found"


@pytest.mark.asyncio
async def test_run_evaluation_rejects_invalid_config(
    evaluations_run_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    evaluation_repository = EvaluationRepository()
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, slug_prefix="eval-run-invalid-config")
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=org.id,
        name="Validation Set",
    )
    await db_session.commit()
    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)

    response = await evaluations_run_client.post(
        "/api/v1/evaluations/run",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={
            "evaluation_set_id": str(evaluation_set.id),
            "config": {
                "top_k": 0,
            },
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_run_evaluation_rejects_member_role(
    evaluations_run_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    evaluation_repository = EvaluationRepository()
    user, org = await _seed_org_user(db_session, role=OrganizationRole.member, slug_prefix="eval-run-member")
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=org.id,
        name="Member Role Set",
    )
    await db_session.commit()
    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)

    response = await evaluations_run_client.post(
        "/api/v1/evaluations/run",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"evaluation_set_id": str(evaluation_set.id)},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role for requested operation"


@pytest.mark.asyncio
async def test_run_evaluation_blocks_duplicate_active_run_for_set(
    evaluations_run_client: AsyncClient,
    db_session: AsyncSession,
    fake_run_evaluation_task: FakeRunEvaluationTask,
) -> None:
    evaluation_repository = EvaluationRepository()
    user, org = await _seed_org_user(db_session, role=OrganizationRole.owner, slug_prefix="eval-run-duplicate")
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=org.id,
        name="Duplicate Guard Set",
    )
    await evaluation_repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.queued.value,
    )
    await db_session.commit()

    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)
    response = await evaluations_run_client.post(
        "/api/v1/evaluations/run",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"evaluation_set_id": str(evaluation_set.id)},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "An evaluation run is already active for this evaluation set"
    assert fake_run_evaluation_task.delay_calls == []


@pytest.mark.asyncio
async def test_run_evaluation_enqueue_failure_marks_run_failed(
    evaluations_run_client: AsyncClient,
    db_session: AsyncSession,
    fake_run_evaluation_task: FakeRunEvaluationTask,
) -> None:
    fake_run_evaluation_task.fail_delay = True
    evaluation_repository = EvaluationRepository()
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, slug_prefix="eval-run-enqueue-fail")
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=org.id,
        name="Enqueue Failure Set",
    )
    await db_session.commit()
    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)

    response = await evaluations_run_client.post(
        "/api/v1/evaluations/run",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"evaluation_set_id": str(evaluation_set.id)},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Evaluation run could not be queued"

    created_runs_result = await db_session.execute(
        select(EvaluationRun).where(EvaluationRun.evaluation_set_id == evaluation_set.id)
    )
    created_runs = list(created_runs_result.scalars().all())
    assert len(created_runs) == 1
    assert created_runs[0].status == EvaluationRunStatus.failed.value
