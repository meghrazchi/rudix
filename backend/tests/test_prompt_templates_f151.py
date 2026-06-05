"""Backend tests for F151: prompt template management and versioning."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

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
from app.domains.agents.repositories.agent_runs import AgentRunRepository
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.domains.prompt_templates.services.rendering import (
    PromptTemplateValidationError,
    render_prompt_template,
    validate_template_definition,
)
from app.main import app
from app.models.enums import ChatRole, EvaluationRunStatus, OrganizationRole, PromptTemplateKey
from app.models.evaluation import EvaluationRun, EvaluationSet
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def prompt_client(
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
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


async def _seed_principal(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
    prefix: str,
) -> tuple[User, Organization, str]:
    organization = Organization(
        name=f"{prefix}-org-{uuid4().hex[:6]}",
        slug=f"{prefix}-{uuid4().hex[:8]}",
    )
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"{prefix}-user-{uuid4().hex[:8]}",
        email=f"{prefix}-{uuid4().hex[:8]}@example.com",
        display_name=prefix,
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

    token = create_app_access_token(
        subject=str(user.id),
        organization_id=str(organization.id),
        email=user.email,
        expires_in_seconds=600,
    )
    return user, organization, token


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


def _api(path: str) -> str:
    return f"{settings.api_prefix}{path}"


def test_render_prompt_template_rejects_missing_variables() -> None:
    with pytest.raises(PromptTemplateValidationError, match="Missing template variables"):
        render_prompt_template("Question: {{ question }}", {})


def test_validate_template_definition_rejects_undeclared_variable() -> None:
    with pytest.raises(PromptTemplateValidationError, match="not declared"):
        validate_template_definition(
            content="Question: {{ question }}\nContext: {{ context }}",
            variables=[{"name": "question", "required": True}],
            variable_schema={
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
            preview_context={"question": "What changed?"},
        )


@pytest.mark.asyncio
async def test_admin_can_create_publish_and_rollback_prompt_versions(
    prompt_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _user, organization, token = await _seed_principal(
        db_session,
        role=OrganizationRole.admin,
        prefix="prompt-admin",
    )
    headers = _headers(token=token, organization_id=str(organization.id))

    list_response = await prompt_client.get(_api("/prompt-templates"), headers=headers)
    assert list_response.status_code == 200, list_response.text
    templates = list_response.json()["items"]
    assert {item["template_key"] for item in templates} >= {
        "answer_generation",
        "summarization",
        "comparison",
        "citation_validation",
        "agent_planning",
    }

    draft_response = await prompt_client.post(
        _api("/prompt-templates/answer_generation/drafts"),
        json={"change_note": "Candidate wording"},
        headers=headers,
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    assert draft["version_number"] == 2
    assert draft["state"] == "draft"

    updated_content = draft["content"].replace(
        "You are a document-grounded assistant.",
        "You are a Rudix document-grounded assistant.",
    )
    update_response = await prompt_client.patch(
        _api("/prompt-templates/answer_generation/versions/2"),
        json={"content": updated_content, "change_note": "Product voice"},
        headers=headers,
    )
    assert update_response.status_code == 200, update_response.text

    review_response = await prompt_client.post(
        _api("/prompt-templates/answer_generation/versions/2/submit-review"),
        headers=headers,
    )
    assert review_response.status_code == 200, review_response.text
    assert review_response.json()["state"] == "review"

    publish_response = await prompt_client.post(
        _api("/prompt-templates/answer_generation/versions/2/publish"),
        json={"change_note": "Publish v2"},
        headers=headers,
    )
    assert publish_response.status_code == 200, publish_response.text
    assert publish_response.json()["state"] == "published"

    immutable_response = await prompt_client.patch(
        _api("/prompt-templates/answer_generation/versions/2"),
        json={"content": updated_content},
        headers=headers,
    )
    assert immutable_response.status_code == 409

    rollback_response = await prompt_client.post(
        _api("/prompt-templates/answer_generation/rollback"),
        json={"version_number": 1, "change_note": "Restore original"},
        headers=headers,
    )
    assert rollback_response.status_code == 200, rollback_response.text
    rollback = rollback_response.json()
    assert rollback["version_number"] == 3
    assert rollback["state"] == "published"
    assert rollback["source_version_number"] == 1

    detail_response = await prompt_client.get(
        _api("/prompt-templates/answer_generation"),
        headers=headers,
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["template"]["active_version_number"] == 3


@pytest.mark.asyncio
async def test_prompt_template_preview_validates_fake_context(
    prompt_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _user, organization, token = await _seed_principal(
        db_session,
        role=OrganizationRole.owner,
        prefix="prompt-preview",
    )
    headers = _headers(token=token, organization_id=str(organization.id))

    response = await prompt_client.post(
        _api("/prompt-templates/summarization/preview"),
        json={
            "content": "Focus: {{ focus }}\nMissing: {{ missing }}",
            "context": {"focus": "risk"},
        },
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_prompt_template_eval_results_are_scoped_to_version(
    prompt_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _user, organization, token = await _seed_principal(
        db_session,
        role=OrganizationRole.admin,
        prefix="prompt-eval",
    )
    headers = _headers(token=token, organization_id=str(organization.id))

    detail_response = await prompt_client.get(
        _api("/prompt-templates/answer_generation"),
        headers=headers,
    )
    assert detail_response.status_code == 200, detail_response.text
    active_version = detail_response.json()["active_version"]

    evaluation_set = EvaluationSet(
        organization_id=organization.id,
        name="Prompt Eval Set",
    )
    db_session.add(evaluation_set)
    await db_session.flush()
    evaluation_run = EvaluationRun(
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.completed.value,
        config={
            "run_name": "Prompt baseline",
            "metrics_summary": {"overall_score": 0.91, "not_found_rate": 0.02},
        },
        prompt_template_version_id=UUID(active_version["version_id"]),
    )
    db_session.add(evaluation_run)
    await db_session.commit()

    results_response = await prompt_client.get(
        _api("/prompt-templates/answer_generation/versions/1/eval-results"),
        headers=headers,
    )
    assert results_response.status_code == 200, results_response.text
    payload = results_response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["run_name"] == "Prompt baseline"
    assert payload["items"][0]["summary"]["overall_score"] == 0.91


@pytest.mark.asyncio
async def test_chat_eval_and_agent_runs_record_prompt_version(
    db_session: AsyncSession,
) -> None:
    user, organization, _token = await _seed_principal(
        db_session,
        role=OrganizationRole.admin,
        prefix="prompt-runs",
    )

    prompt_version = await PromptTemplateService().resolve_active_version(
        db_session,
        organization_id=organization.id,
        template_key=PromptTemplateKey.answer_generation.value,
    )
    await db_session.commit()

    chat_repository = ChatRepository()
    chat_session = await chat_repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        title="Prompt version run",
    )
    chat_message = await chat_repository.create_chat_message(
        db_session,
        chat_session_id=chat_session.id,
        role=ChatRole.assistant.value,
        content="Grounded answer",
        prompt_template_version_id=prompt_version.id,
    )

    evaluation_repository = EvaluationRepository()
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Prompt Version Eval",
    )
    evaluation_run = await evaluation_repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.queued.value,
        config={"prompt_template": {"version_id": str(prompt_version.id)}},
        prompt_template_version_id=prompt_version.id,
    )

    agent_run = await AgentRunRepository().create_agent_run(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        objective="Check retrieved context",
        prompt_template_version_id=prompt_version.id,
    )

    assert chat_message.prompt_template_version_id == prompt_version.id
    assert evaluation_run.prompt_template_version_id == prompt_version.id
    assert agent_run.prompt_template_version_id == prompt_version.id


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_prompt_templates(
    prompt_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _user, organization, token = await _seed_principal(
        db_session,
        role=OrganizationRole.member,
        prefix="prompt-member",
    )
    response = await prompt_client.get(
        _api("/prompt-templates"),
        headers=_headers(token=token, organization_id=str(organization.id)),
    )
    assert response.status_code == 403
