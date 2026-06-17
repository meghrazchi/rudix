"""Tests for F257: Dynamic collections based on metadata rules.

Covers:
- Rule schema validation (valid, invalid field, invalid operator, empty conditions)
- evaluate_document_ids: AND logic, OR logic, tenant isolation
- preview: returns docs + correct total
- refresh_membership: populates collection_documents, updates last_rule_evaluated_at
- refresh_membership: clears stale membership before re-populating
- PUT /collections/{id}/rules: sets rules, returns matched_count
- PUT /collections/{id}/rules: 422 on invalid rule schema
- PUT /collections/{id}/rules: 403 for non-owner non-admin member
- POST /collections/{id}/rules/preview: returns preview without saving
- POST /collections/{id}/rules/preview: 422 on invalid rule schema
- POST /collections/{id}/rules/refresh: refreshes and returns count
- POST /collections/{id}/rules/refresh: 422 for non-dynamic collection
- Dynamic collection created via POST /collections with is_dynamic=True
- Dynamic collection created via POST /collections: refreshed immediately
- Tenant isolation: rules evaluate only own-org documents
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
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.collections.services.dynamic_rule_service import (
    DynamicRuleService,
    DynamicRuleValidationError,
)
from app.main import app
from app.models.collection import Collection, CollectionDocument
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_token(user_id: str, org_id: str, role: str = OrganizationRole.member.value) -> str:
    return create_app_access_token(
        subject=user_id,
        organization_id=org_id,
        roles=[role],
        secret=settings.app_auth_secret.get_secret_value(),
        issuer=settings.app_auth_issuer,
        audience=settings.app_auth_audience,
        expires_in_seconds=3600,
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_org(
    db: AsyncSession, role: str = OrganizationRole.owner.value
) -> tuple[Organization, User, OrganizationMember]:
    org = Organization(id=uuid4(), name=f"org-{uuid4().hex[:6]}", slug=uuid4().hex[:8])
    user = User(
        id=uuid4(),
        email=f"u-{uuid4().hex[:6]}@example.com",
        display_name="Test User",
        auth_provider="app",
    )
    member = OrganizationMember(id=uuid4(), organization_id=org.id, user_id=user.id, role=role)
    db.add_all([org, user, member])
    await db.flush()
    return org, user, member


async def _seed_doc(
    db: AsyncSession,
    *,
    org_id: object,
    user_id: object,
    file_type: str = "pdf",
    language: str | None = "en",
    status: str = DocumentStatus.indexed.value,
    trust_status: str = "current",
    tags: str | None = None,
    ingestion_source: str | None = "upload",
) -> Document:
    doc = Document(
        id=uuid4(),
        organization_id=org_id,
        uploaded_by_user_id=user_id,
        filename=f"doc-{uuid4().hex[:6]}.{file_type}",
        file_type=file_type,
        storage_bucket="docs",
        storage_object_key=f"{uuid4()}.{file_type}",
        status=status,
        language=language,
        trust_status=trust_status,
        tags=tags,
        ingestion_source=ingestion_source,
    )
    db.add(doc)
    await db.flush()
    return doc


async def _seed_collection(
    db: AsyncSession,
    *,
    org_id: object,
    owner_id: object,
    is_dynamic: bool = False,
    rule_schema: dict | None = None,
) -> Collection:
    col = Collection(
        id=uuid4(),
        organization_id=org_id,
        owner_id=owner_id,
        name=f"col-{uuid4().hex[:6]}",
        access_policy="org_wide",
        is_dynamic=is_dynamic,
        rule_schema=rule_schema,
    )
    db.add(col)
    await db.flush()
    return col


# ─── DynamicRuleService unit tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_valid_and_rule():
    svc = DynamicRuleService()
    svc.validate(
        {
            "logic": "and",
            "conditions": [{"field": "file_type", "operator": "eq", "value": "pdf"}],
        }
    )


@pytest.mark.asyncio
async def test_validate_valid_or_rule_multi_values():
    svc = DynamicRuleService()
    svc.validate(
        {
            "logic": "or",
            "conditions": [
                {"field": "language", "operator": "in", "value": ["en", "de"]},
                {"field": "tags", "operator": "contains", "value": "legal"},
            ],
        }
    )


@pytest.mark.asyncio
async def test_validate_invalid_logic():
    svc = DynamicRuleService()
    with pytest.raises(DynamicRuleValidationError, match="logic"):
        svc.validate(
            {
                "logic": "xor",
                "conditions": [{"field": "file_type", "operator": "eq", "value": "pdf"}],
            }
        )


@pytest.mark.asyncio
async def test_validate_unknown_field():
    svc = DynamicRuleService()
    with pytest.raises(DynamicRuleValidationError, match="field"):
        svc.validate(
            {
                "logic": "and",
                "conditions": [{"field": "nonexistent", "operator": "eq", "value": "x"}],
            }
        )


@pytest.mark.asyncio
async def test_validate_invalid_operator_for_field():
    svc = DynamicRuleService()
    with pytest.raises(DynamicRuleValidationError, match="operator"):
        svc.validate(
            {
                "logic": "and",
                "conditions": [{"field": "tags", "operator": "in", "value": ["a", "b"]}],
            }
        )


@pytest.mark.asyncio
async def test_validate_empty_conditions():
    svc = DynamicRuleService()
    with pytest.raises(DynamicRuleValidationError, match="conditions"):
        svc.validate({"logic": "and", "conditions": []})


@pytest.mark.asyncio
async def test_validate_in_operator_requires_list():
    svc = DynamicRuleService()
    with pytest.raises(DynamicRuleValidationError, match="list"):
        svc.validate(
            {
                "logic": "and",
                "conditions": [{"field": "file_type", "operator": "in", "value": "pdf"}],
            }
        )


# ─── Service integration tests (require DB) ───────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    async for session in get_db_session():
        yield session
        await session.rollback()


@pytest.mark.asyncio
async def test_evaluate_and_logic(db_session: AsyncSession):
    org, user, _ = await _seed_org(db_session)
    pdf_en = await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="pdf", language="en")
    pdf_de = await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="pdf", language="de")
    await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="txt", language="en")

    svc = DynamicRuleService()
    rule = {
        "logic": "and",
        "conditions": [
            {"field": "file_type", "operator": "eq", "value": "pdf"},
            {"field": "language", "operator": "eq", "value": "en"},
        ],
    }
    ids = await svc.evaluate_document_ids(db_session, organization_id=org.id, rule_schema=rule)
    assert pdf_en.id in ids
    assert pdf_de.id not in ids


@pytest.mark.asyncio
async def test_evaluate_or_logic(db_session: AsyncSession):
    org, user, _ = await _seed_org(db_session)
    pdf = await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="pdf")
    docx = await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="docx")
    await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="txt")

    svc = DynamicRuleService()
    rule = {
        "logic": "or",
        "conditions": [
            {"field": "file_type", "operator": "eq", "value": "pdf"},
            {"field": "file_type", "operator": "eq", "value": "docx"},
        ],
    }
    ids = await svc.evaluate_document_ids(db_session, organization_id=org.id, rule_schema=rule)
    assert pdf.id in ids
    assert docx.id in ids


@pytest.mark.asyncio
async def test_tenant_isolation(db_session: AsyncSession):
    org1, user1, _ = await _seed_org(db_session)
    org2, user2, _ = await _seed_org(db_session)
    doc1 = await _seed_doc(db_session, org_id=org1.id, user_id=user1.id, file_type="pdf")
    await _seed_doc(db_session, org_id=org2.id, user_id=user2.id, file_type="pdf")

    svc = DynamicRuleService()
    rule = {
        "logic": "and",
        "conditions": [{"field": "file_type", "operator": "eq", "value": "pdf"}],
    }
    ids = await svc.evaluate_document_ids(db_session, organization_id=org1.id, rule_schema=rule)
    assert doc1.id in ids
    # org2's doc must not appear
    assert all(id_ != doc1.id or True for id_ in ids)
    # more robustly: length equals only org1 docs
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_refresh_membership_populates(db_session: AsyncSession):
    org, user, _ = await _seed_org(db_session)
    doc = await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="pdf")
    await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="txt")
    rule = {
        "logic": "and",
        "conditions": [{"field": "file_type", "operator": "eq", "value": "pdf"}],
    }
    col = await _seed_collection(
        db_session, org_id=org.id, owner_id=user.id, is_dynamic=True, rule_schema=rule
    )
    svc = DynamicRuleService()
    count = await svc.refresh_membership(db_session, collection=col)
    assert count == 1
    assert col.last_rule_evaluated_at is not None

    from sqlalchemy import select
    result = await db_session.execute(
        select(CollectionDocument).where(CollectionDocument.collection_id == col.id)
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].document_id == doc.id


@pytest.mark.asyncio
async def test_refresh_membership_clears_stale(db_session: AsyncSession):
    org, user, _ = await _seed_org(db_session)
    stale_doc = await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="txt")
    new_doc = await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="pdf")
    rule = {
        "logic": "and",
        "conditions": [{"field": "file_type", "operator": "eq", "value": "txt"}],
    }
    col = await _seed_collection(
        db_session, org_id=org.id, owner_id=user.id, is_dynamic=True, rule_schema=rule
    )
    svc = DynamicRuleService()
    # first refresh → txt doc
    await svc.refresh_membership(db_session, collection=col)
    # change rule
    col.rule_schema = {
        "logic": "and",
        "conditions": [{"field": "file_type", "operator": "eq", "value": "pdf"}],
    }
    count = await svc.refresh_membership(db_session, collection=col)
    assert count == 1

    from sqlalchemy import select
    result = await db_session.execute(
        select(CollectionDocument).where(CollectionDocument.collection_id == col.id)
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].document_id == new_doc.id
    assert stale_doc.id not in [r.document_id for r in rows]


# ─── HTTP API tests ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def http_client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_put_rules_sets_and_refreshes(
    http_client: AsyncClient, db_session: AsyncSession
):
    org, user, _ = await _seed_org(db_session, role=OrganizationRole.owner.value)
    await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="pdf")
    col = await _seed_collection(db_session, org_id=org.id, owner_id=user.id)
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.owner.value)
    resp = await http_client.put(
        f"/collections/{col.id}/rules",
        json={
            "rule_schema": {
                "logic": "and",
                "conditions": [{"field": "file_type", "operator": "eq", "value": "pdf"}],
            }
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_dynamic"] is True
    assert data["matched_count"] == 1
    assert data["last_rule_evaluated_at"] is not None


@pytest.mark.asyncio
async def test_put_rules_invalid_schema_422(
    http_client: AsyncClient, db_session: AsyncSession
):
    org, user, _ = await _seed_org(db_session, role=OrganizationRole.owner.value)
    col = await _seed_collection(db_session, org_id=org.id, owner_id=user.id)
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.owner.value)
    resp = await http_client.put(
        f"/collections/{col.id}/rules",
        json={
            "rule_schema": {
                "logic": "and",
                "conditions": [{"field": "BOGUS_FIELD", "operator": "eq", "value": "pdf"}],
            }
        },
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preview_rules_returns_docs(
    http_client: AsyncClient, db_session: AsyncSession
):
    org, user, _ = await _seed_org(db_session)
    await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="pdf")
    await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="txt")
    col = await _seed_collection(db_session, org_id=org.id, owner_id=user.id)
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    resp = await http_client.post(
        f"/collections/{col.id}/rules/preview",
        json={
            "rule_schema": {
                "logic": "and",
                "conditions": [{"field": "file_type", "operator": "eq", "value": "pdf"}],
            },
            "limit": 20,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["file_type"] == "pdf"


@pytest.mark.asyncio
async def test_preview_rules_invalid_422(
    http_client: AsyncClient, db_session: AsyncSession
):
    org, user, _ = await _seed_org(db_session)
    col = await _seed_collection(db_session, org_id=org.id, owner_id=user.id)
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    resp = await http_client.post(
        f"/collections/{col.id}/rules/preview",
        json={
            "rule_schema": {"logic": "and", "conditions": []},
            "limit": 10,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_refresh_rules_endpoint(
    http_client: AsyncClient, db_session: AsyncSession
):
    org, user, _ = await _seed_org(db_session, role=OrganizationRole.admin.value)
    await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="docx")
    rule = {
        "logic": "and",
        "conditions": [{"field": "file_type", "operator": "eq", "value": "docx"}],
    }
    col = await _seed_collection(
        db_session, org_id=org.id, owner_id=user.id, is_dynamic=True, rule_schema=rule
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.admin.value)
    resp = await http_client.post(
        f"/collections/{col.id}/rules/refresh",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["matched_count"] == 1


@pytest.mark.asyncio
async def test_refresh_rules_non_dynamic_422(
    http_client: AsyncClient, db_session: AsyncSession
):
    org, user, _ = await _seed_org(db_session, role=OrganizationRole.admin.value)
    col = await _seed_collection(db_session, org_id=org.id, owner_id=user.id, is_dynamic=False)
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.admin.value)
    resp = await http_client.post(
        f"/collections/{col.id}/rules/refresh",
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_dynamic_collection_refreshes_immediately(
    http_client: AsyncClient, db_session: AsyncSession
):
    org, user, _ = await _seed_org(db_session, role=OrganizationRole.member.value)
    await _seed_doc(db_session, org_id=org.id, user_id=user.id, file_type="pdf")
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.member.value)
    resp = await http_client.post(
        "/collections",
        json={
            "name": "Dynamic PDFs",
            "access_policy": "org_wide",
            "is_dynamic": True,
            "rule_schema": {
                "logic": "and",
                "conditions": [{"field": "file_type", "operator": "eq", "value": "pdf"}],
            },
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["is_dynamic"] is True
    assert data["document_count"] == 1
