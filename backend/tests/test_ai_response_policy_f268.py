"""Backend tests for F268: AI response policy engine.

Covers:
  A. Policy engine — resolve (no policy)
  B. Policy engine — resolve (org policy active)
  C. Policy engine — resolve (collection override merges)
  D. Policy engine — pre-generation: topic blocked
  E. Policy engine — pre-generation: allowed-topics deny when no match
  F. Policy engine — pre-generation: topic not blocked
  G. Policy engine — post-generation: citation_mode required blocks
  H. Policy engine — post-generation: min_sources_required blocks
  I. Policy engine — post-generation: low confidence refuses
  J. Policy engine — post-generation: low confidence warns
  K. Policy engine — post-generation: stale source refuses
  L. Policy engine — post-generation: stale source warns
  M. Policy engine — not_found refuse
  N. Policy engine — apply_disclaimer prepend
  O. Policy engine — apply_disclaimer append
  P. Repository — create / get / get_active / list / count
  Q. Repository — activate deactivates existing active policy
  R. Repository — update
  S. Repository — collection override upsert / get / delete
  T. Repository — eval log create / list
  U. HTTP — POST /admin/ai-response-policy creates draft policy
  V. HTTP — GET /admin/ai-response-policy/active returns active policy
  W. HTTP — PATCH /{id}/activate activates policy
  X. HTTP — POST /{id}/deactivate deactivates policy
  Y. HTTP — PATCH /{id} updates policy fields
  Z. HTTP — DELETE /{id} refuses when policy is active
  AA. HTTP — DELETE /{id} succeeds when inactive
  AB. HTTP — POST /preview returns evaluation result
  AC. HTTP — GET /logs returns evaluation logs
  AD. HTTP — role guard: non-admin cannot create policy
  AE. HTTP — org isolation: cannot get another org's policy

Run:
    pytest tests/test_ai_response_policy_f268.py -v
"""

from __future__ import annotations

import os
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

from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.ai_response_policy.repositories.ai_response_policy import (
    AiResponsePolicyRepository,
)
from app.domains.ai_response_policy.services.policy_engine import (
    AiResponsePolicyEngine,
    EffectivePolicy,
    PolicyEvaluationResult,
)
from app.main import app
from app.models.ai_response_policy import OrgAiResponsePolicy
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(db_session: AsyncSession) -> AsyncSession:
    return db_session


def _make_token(user_id: str, org_id: str, role: str) -> str:
    settings.auth_provider = AuthProvider.app
    return create_app_access_token(user_id=user_id, organization_id=org_id, role=role)


@pytest_asyncio.fixture
async def org(db: AsyncSession) -> Organization:
    o = Organization(name="PolicyTestOrg", slug=f"policy-{uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    return o


@pytest_asyncio.fixture
async def org2(db: AsyncSession) -> Organization:
    o = Organization(name="OtherOrg", slug=f"otherorg-{uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    return o


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"admin-{uuid4().hex[:6]}@test.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db.flush()
    token = _make_token(str(u.id), str(org.id), OrganizationRole.admin.value)
    return u, token


@pytest_asyncio.fixture
async def member_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"member-{uuid4().hex[:6]}@test.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org.id,
            role=OrganizationRole.member.value,
        )
    )
    await db.flush()
    token = _make_token(str(u.id), str(org.id), OrganizationRole.member.value)
    return u, token


@pytest_asyncio.fixture
async def other_admin(db: AsyncSession, org2: Organization) -> tuple[User, str]:
    u = User(email=f"other-{uuid4().hex[:6]}@test.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org2.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db.flush()
    token = _make_token(str(u.id), str(org2.id), OrganizationRole.admin.value)
    return u, token


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncClient:
    async def _override():
        yield db

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


_repo = AiResponsePolicyRepository()
_engine = AiResponsePolicyEngine()

# ---------------------------------------------------------------------------
# A–C. Policy engine — resolve()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_resolve_no_policy() -> None:
    result = _engine.resolve(None)
    assert result.source == "none"
    assert result.policy_id is None


@pytest.mark.asyncio
async def test_engine_resolve_org_policy() -> None:
    import uuid

    policy = OrgAiResponsePolicy(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        policy_name="Test",
        is_active=True,
        citation_mode="required",
        min_confidence_threshold=0.5,
        no_answer_behavior="refuse",
        grounded_verification_mode="strict",
        grounded_verification_threshold=0.8,
        stale_source_behavior="warn",
        blocked_topics_json=["politics"],
        allowed_topics_json=None,
        min_sources_required=2,
        disclaimer_text="Disclaimer.",
        disclaimer_position="prepend",
        refusal_message="Refused.",
    )
    ep = _engine.resolve(policy)
    assert ep.source == "org"
    assert ep.citation_mode == "required"
    assert ep.grounded_verification_mode == "strict"
    assert ep.grounded_verification_threshold == 0.8
    assert ep.blocked_topics == ["politics"]
    assert ep.min_sources_required == 2


@pytest.mark.asyncio
async def test_engine_resolve_inactive_policy() -> None:
    import uuid

    policy = OrgAiResponsePolicy(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        policy_name="Test",
        is_active=False,
        citation_mode="required",
        min_confidence_threshold=0.5,
        no_answer_behavior="refuse",
        grounded_verification_mode="off",
        stale_source_behavior="warn",
        blocked_topics_json=[],
        allowed_topics_json=None,
        min_sources_required=None,
        disclaimer_text=None,
        disclaimer_position="prepend",
        refusal_message=None,
    )
    ep = _engine.resolve(policy)
    assert ep.source == "none"


# ---------------------------------------------------------------------------
# D–F. Policy engine — pre-generation topic checks
# ---------------------------------------------------------------------------


def _basic_ep(**kwargs) -> EffectivePolicy:
    defaults = {
        "policy_id": str(uuid4()),
        "source": "org",
        "citation_mode": "recommended",
        "min_confidence_threshold": None,
        "no_answer_behavior": "warn",
        "grounded_verification_mode": "off",
        "grounded_verification_threshold": None,
        "stale_source_behavior": "warn",
        "blocked_topics": [],
        "allowed_topics": None,
        "min_sources_required": None,
        "disclaimer_text": None,
        "disclaimer_position": "prepend",
        "refusal_message": "Blocked.",
    }
    defaults.update(kwargs)
    return EffectivePolicy(**defaults)


@pytest.mark.asyncio
async def test_engine_pre_gen_topic_blocked() -> None:
    ep = _basic_ep(blocked_topics=["politics", "gambling"])
    result = _engine.evaluate_pre_generation("What is the best gambling strategy?", ep)
    assert result.blocked is True
    assert any("gambling" in r for r in result.violated_rules)


@pytest.mark.asyncio
async def test_engine_pre_gen_allowed_topics_blocks_non_match() -> None:
    ep = _basic_ep(allowed_topics=["product support", "billing"])
    result = _engine.evaluate_pre_generation("Tell me about local weather.", ep)
    assert result.blocked is True
    assert "topic_not_in_allowed_list" in result.violated_rules


@pytest.mark.asyncio
async def test_engine_pre_gen_allowed_topics_passes_match() -> None:
    ep = _basic_ep(allowed_topics=["product support", "billing"])
    result = _engine.evaluate_pre_generation("I need billing help.", ep)
    assert result.blocked is False


@pytest.mark.asyncio
async def test_engine_pre_gen_no_policy_passes() -> None:
    ep = EffectivePolicy(policy_id=None, source="none")
    result = _engine.evaluate_pre_generation("anything", ep)
    assert result.blocked is False


# ---------------------------------------------------------------------------
# G–N. Policy engine — post-generation checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_post_gen_citation_required_blocks() -> None:
    ep = _basic_ep(citation_mode="required")
    result = _engine.evaluate_post_generation(
        confidence_score=0.9,
        citation_count=0,
        stale_source_count=0,
        not_found=False,
        effective_policy=ep,
    )
    assert result.blocked is True
    assert "citation_required_but_missing" in result.violated_rules


@pytest.mark.asyncio
async def test_engine_post_gen_min_sources_blocks() -> None:
    ep = _basic_ep(min_sources_required=3)
    result = _engine.evaluate_post_generation(
        confidence_score=0.9,
        citation_count=1,
        stale_source_count=0,
        not_found=False,
        effective_policy=ep,
    )
    assert result.blocked is True
    assert any("min_sources_required" in r for r in result.violated_rules)


@pytest.mark.asyncio
async def test_engine_post_gen_low_confidence_refuses() -> None:
    ep = _basic_ep(min_confidence_threshold=0.5, no_answer_behavior="refuse")
    result = _engine.evaluate_post_generation(
        confidence_score=0.3,
        citation_count=2,
        stale_source_count=0,
        not_found=False,
        effective_policy=ep,
    )
    assert result.blocked is True


@pytest.mark.asyncio
async def test_engine_post_gen_low_confidence_warns() -> None:
    ep = _basic_ep(min_confidence_threshold=0.5, no_answer_behavior="warn")
    result = _engine.evaluate_post_generation(
        confidence_score=0.3,
        citation_count=2,
        stale_source_count=0,
        not_found=False,
        effective_policy=ep,
    )
    assert result.blocked is False
    assert result.warned is True


@pytest.mark.asyncio
async def test_engine_post_gen_stale_source_refuses() -> None:
    ep = _basic_ep(stale_source_behavior="refuse")
    result = _engine.evaluate_post_generation(
        confidence_score=0.9,
        citation_count=2,
        stale_source_count=1,
        not_found=False,
        effective_policy=ep,
    )
    assert result.blocked is True
    assert any("stale_sources" in r for r in result.violated_rules)


@pytest.mark.asyncio
async def test_engine_post_gen_stale_source_warns() -> None:
    ep = _basic_ep(stale_source_behavior="warn")
    result = _engine.evaluate_post_generation(
        confidence_score=0.9,
        citation_count=2,
        stale_source_count=2,
        not_found=False,
        effective_policy=ep,
    )
    assert result.blocked is False
    assert result.warned is True
    assert any("stale_sources_warning" in f for f in result.warning_flags)


@pytest.mark.asyncio
async def test_engine_post_gen_not_found_refuses() -> None:
    ep = _basic_ep(no_answer_behavior="refuse")
    result = _engine.evaluate_post_generation(
        confidence_score=0.1,
        citation_count=0,
        stale_source_count=0,
        not_found=True,
        effective_policy=ep,
    )
    assert result.blocked is True


# ---------------------------------------------------------------------------
# N–O. Disclaimer application
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_disclaimer_prepend() -> None:
    result = PolicyEvaluationResult(
        disclaimer_text="AI can make mistakes.",
        disclaimer_position="prepend",
    )
    answer = _engine.apply_disclaimer("The answer is 42.", result)
    assert answer.startswith("AI can make mistakes.")
    assert "The answer is 42." in answer


@pytest.mark.asyncio
async def test_engine_disclaimer_append() -> None:
    result = PolicyEvaluationResult(
        disclaimer_text="AI can make mistakes.",
        disclaimer_position="append",
    )
    answer = _engine.apply_disclaimer("The answer is 42.", result)
    assert answer.endswith("AI can make mistakes.")
    assert "The answer is 42." in answer


@pytest.mark.asyncio
async def test_engine_disclaimer_not_applied_when_blocked() -> None:
    result = PolicyEvaluationResult(
        blocked=True,
        disclaimer_text="AI can make mistakes.",
        disclaimer_position="prepend",
    )
    answer = _engine.apply_disclaimer("Blocked.", result)
    assert answer == "Blocked."


# ---------------------------------------------------------------------------
# P–T. Repository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_create_get(db: AsyncSession, org: Organization) -> None:
    policy = await _repo.create(
        db,
        organization_id=org.id,
        policy_name="Safety Policy",
        citation_mode="required",
        no_answer_behavior="refuse",
        grounded_verification_mode="strict",
        grounded_verification_threshold=0.85,
    )
    await db.flush()

    fetched = await _repo.get(db, policy_id=policy.id, organization_id=org.id)
    assert fetched is not None
    assert fetched.policy_name == "Safety Policy"
    assert fetched.citation_mode == "required"
    assert fetched.grounded_verification_mode == "strict"
    assert fetched.is_active is False


@pytest.mark.asyncio
async def test_repo_activate_deactivates_previous(db: AsyncSession, org: Organization) -> None:
    p1 = await _repo.create(db, organization_id=org.id, policy_name="P1")
    p2 = await _repo.create(db, organization_id=org.id, policy_name="P2")
    await db.flush()

    await _repo.activate(db, organization_id=org.id, policy=p1)
    await db.flush()
    active = await _repo.get_active(db, organization_id=org.id)
    assert active is not None
    assert active.id == p1.id

    await _repo.activate(db, organization_id=org.id, policy=p2)
    await db.flush()
    active = await _repo.get_active(db, organization_id=org.id)
    assert active is not None
    assert active.id == p2.id
    # p1 must have been deactivated
    await db.refresh(p1)
    assert p1.is_active is False


@pytest.mark.asyncio
async def test_repo_list_count(db: AsyncSession, org: Organization) -> None:
    for i in range(3):
        await _repo.create(db, organization_id=org.id, policy_name=f"P{i}")
    await db.flush()

    items = await _repo.list(db, organization_id=org.id)
    total = await _repo.count(db, organization_id=org.id)
    assert len(items) == 3
    assert total == 3


@pytest.mark.asyncio
async def test_repo_collection_override_upsert_get(db: AsyncSession, org: Organization) -> None:
    from uuid import uuid4 as _uuid4

    policy = await _repo.create(db, organization_id=org.id, policy_name="P")
    await db.flush()

    col_id = _uuid4()
    await _repo.upsert_collection_override(
        db,
        org_policy_id=policy.id,
        collection_id=col_id,
        citation_mode="required",
        no_answer_behavior="refuse",
        grounded_verification_mode="standard",
        grounded_verification_threshold=0.65,
    )
    await db.flush()

    fetched = await _repo.get_collection_override(db, org_policy_id=policy.id, collection_id=col_id)
    assert fetched is not None
    assert fetched.citation_mode == "required"
    assert fetched.no_answer_behavior == "refuse"
    assert fetched.grounded_verification_mode == "standard"

    # Upsert again — should update existing row
    await _repo.upsert_collection_override(
        db,
        org_policy_id=policy.id,
        collection_id=col_id,
        citation_mode="disabled",
        grounded_verification_mode="strict",
    )
    await db.flush()
    fetched2 = await _repo.get_collection_override(
        db, org_policy_id=policy.id, collection_id=col_id
    )
    assert fetched2 is not None
    assert fetched2.citation_mode == "disabled"
    assert fetched2.grounded_verification_mode == "strict"


@pytest.mark.asyncio
async def test_repo_eval_log(db: AsyncSession, org: Organization) -> None:
    await _repo.create_eval_log(
        db,
        organization_id=org.id,
        user_id=None,
        org_policy_id=None,
        collection_id=None,
        chat_session_id=None,
        chat_message_id=None,
        outcome="blocked",
        policy_source="org",
        violated_rules=["blocked_topic:gambling"],
        warning_flags=[],
        question_preview="What gambling strategy?",
        confidence_score=0.9,
        citation_count=1,
        stale_source_count=0,
        is_preview_run=False,
    )
    await db.flush()

    items = await _repo.list_eval_logs(db, organization_id=org.id)
    total = await _repo.count_eval_logs(db, organization_id=org.id)
    assert len(items) == 1
    assert total == 1
    assert items[0].outcome == "blocked"


# ---------------------------------------------------------------------------
# U–AE. HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_create_policy(
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
) -> None:
    _, token = admin_user
    resp = await client.post(
        "/admin/ai-response-policy",
        json={
            "policy_name": "HTTP Test Policy",
            "citation_mode": "required",
            "no_answer_behavior": "refuse",
            "grounded_verification_mode": "strict",
            "grounded_verification_threshold": 0.8,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["policy_name"] == "HTTP Test Policy"
    assert data["citation_mode"] == "required"
    assert data["grounded_verification_mode"] == "strict"
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_http_get_active_policy(
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
    db: AsyncSession,
) -> None:
    _, token = admin_user
    # No active policy yet
    resp = await client.get(
        "/admin/ai-response-policy/active",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() is None

    # Create and activate
    policy = await _repo.create(db, organization_id=org.id, policy_name="Active P")
    await _repo.activate(db, organization_id=org.id, policy=policy)
    await db.commit()

    resp2 = await client.get(
        "/admin/ai-response-policy/active",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    assert resp2.json() is not None
    assert resp2.json()["policy_name"] == "Active P"


@pytest.mark.asyncio
async def test_http_activate_policy(
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
    db: AsyncSession,
) -> None:
    _, token = admin_user
    policy = await _repo.create(db, organization_id=org.id, policy_name="Activatable")
    await db.commit()

    resp = await client.post(
        f"/admin/ai-response-policy/{policy.id}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


@pytest.mark.asyncio
async def test_http_deactivate_policy(
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
    db: AsyncSession,
) -> None:
    _, token = admin_user
    policy = await _repo.create(db, organization_id=org.id, policy_name="Deactivatable")
    await _repo.activate(db, organization_id=org.id, policy=policy)
    await db.commit()

    resp = await client.post(
        f"/admin/ai-response-policy/{policy.id}/deactivate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_http_update_policy(
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
    db: AsyncSession,
) -> None:
    _, token = admin_user
    policy = await _repo.create(
        db, organization_id=org.id, policy_name="Updatable", citation_mode="disabled"
    )
    await db.commit()

    resp = await client.patch(
        f"/admin/ai-response-policy/{policy.id}",
        json={
            "policy_name": "Updated Name",
            "citation_mode": "required",
            "grounded_verification_mode": "strict",
            "grounded_verification_threshold": 0.8,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["policy_name"] == "Updated Name"
    assert resp.json()["citation_mode"] == "required"
    assert resp.json()["grounded_verification_mode"] == "strict"


@pytest.mark.asyncio
async def test_http_delete_active_policy_rejected(
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
    db: AsyncSession,
) -> None:
    _, token = admin_user
    policy = await _repo.create(db, organization_id=org.id, policy_name="Active")
    await _repo.activate(db, organization_id=org.id, policy=policy)
    await db.commit()

    resp = await client.delete(
        f"/admin/ai-response-policy/{policy.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_http_delete_inactive_policy(
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
    db: AsyncSession,
) -> None:
    _, token = admin_user
    policy = await _repo.create(db, organization_id=org.id, policy_name="Inactive")
    await db.commit()

    resp = await client.delete(
        f"/admin/ai-response-policy/{policy.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_http_preview_policy(
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
    db: AsyncSession,
) -> None:
    _, token = admin_user
    policy = await _repo.create(
        db,
        organization_id=org.id,
        policy_name="Preview",
        citation_mode="required",
        blocked_topics=["gambling"],
    )
    await db.commit()

    resp = await client.post(
        "/admin/ai-response-policy/preview",
        json={
            "question": "What is the best gambling strategy?",
            "confidence_score": 0.9,
            "citation_count": 0,
            "stale_source_count": 0,
            "policy_id": str(policy.id),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "blocked"
    assert any("gambling" in r for r in data["violated_rules"])


@pytest.mark.asyncio
async def test_http_logs(
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
    db: AsyncSession,
) -> None:
    _, token = admin_user
    await _repo.create_eval_log(
        db,
        organization_id=org.id,
        user_id=None,
        org_policy_id=None,
        collection_id=None,
        chat_session_id=None,
        chat_message_id=None,
        outcome="warned",
        policy_source="org",
        violated_rules=[],
        warning_flags=["stale_sources_warning:1"],
        question_preview="Help me!",
        confidence_score=0.7,
        citation_count=2,
        stale_source_count=1,
        is_preview_run=False,
    )
    await db.commit()

    resp = await client.get(
        "/admin/ai-response-policy/logs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(i["outcome"] == "warned" for i in data["items"])


@pytest.mark.asyncio
async def test_http_role_guard_member_cannot_create(
    client: AsyncClient,
    member_user: tuple[User, str],
) -> None:
    _, token = member_user
    resp = await client.post(
        "/admin/ai-response-policy",
        json={"policy_name": "Not allowed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_http_org_isolation(
    client: AsyncClient,
    admin_user: tuple[User, str],
    other_admin: tuple[User, str],
    org: Organization,
    db: AsyncSession,
) -> None:
    _, token_a = admin_user
    _, token_b = other_admin

    # org A creates a policy
    resp = await client.post(
        "/admin/ai-response-policy",
        json={"policy_name": "Org A Policy"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 201
    policy_id = resp.json()["policy_id"]

    # org B tries to access it — must get 404
    resp2 = await client.get(
        f"/admin/ai-response-policy/{policy_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp2.status_code == 404
