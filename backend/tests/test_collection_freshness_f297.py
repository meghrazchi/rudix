"""Tests for collection freshness review metadata and filters (F297)."""

from __future__ import annotations

import os
from datetime import date
from uuid import uuid4

import pytest
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

from app.domains.collections.repositories.collections import CollectionRepository
from app.models.collection import Collection
from app.models.enums import DocumentReviewStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

collection_repository = CollectionRepository()


async def _seed_principal(db_session: AsyncSession) -> tuple[Organization, User]:
    org = Organization(name="Collections Org", slug=f"collections-{uuid4().hex[:8]}")
    user = User(
        organization_id=org.id,
        external_auth_id=f"collections-user-{uuid4().hex[:8]}",
        email=f"collections-{uuid4().hex[:8]}@example.com",
    )
    db_session.add_all([org, user])
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()
    return org, user


async def _seed_collection(
    db_session: AsyncSession,
    *,
    organization: Organization,
    owner: User,
    name: str,
) -> Collection:
    collection = await collection_repository.create(
        db_session,
        organization_id=organization.id,
        owner_id=owner.id,
        name=name,
        description=None,
        access_policy="org_wide",
    )
    await db_session.flush()
    return collection


@pytest.mark.asyncio
async def test_collection_list_filters_by_freshness(db_session: AsyncSession) -> None:
    org, user = await _seed_principal(db_session)
    current = await _seed_collection(db_session, organization=org, owner=user, name="Current")
    stale = await _seed_collection(db_session, organization=org, owner=user, name="Stale")

    await collection_repository.update(
        db_session,
        collection=stale,
        review_status=DocumentReviewStatus.stale.value,
        review_due_date=date(2026, 6, 1),
        trust_level="high",
    )
    await db_session.commit()

    items = await collection_repository.list(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        user_roles=[OrganizationRole.member.value],
        review_status=DocumentReviewStatus.stale.value,
    )

    assert [item.id for item in items] == [stale.id]
    assert items[0].review_status == "stale"
    assert items[0].trust_level == "high"
    assert current.review_status == "current"


@pytest.mark.asyncio
async def test_collection_update_sets_review_owner_and_due_date(
    db_session: AsyncSession,
) -> None:
    org, user = await _seed_principal(db_session)
    reviewer = User(
        organization_id=org.id,
        external_auth_id=f"reviewer-{uuid4().hex[:8]}",
        email=f"reviewer-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(reviewer)
    await db_session.flush()
    collection = await _seed_collection(db_session, organization=org, owner=user, name="Docs")

    updated = await collection_repository.update(
        db_session,
        collection=collection,
        review_status=DocumentReviewStatus.needs_review.value,
        review_owner_id=reviewer.id,
        review_due_date=date(2026, 7, 1),
        expiry_date=date(2026, 8, 1),
        trust_level="gold",
    )
    await db_session.commit()

    assert updated.review_status == "needs_review"
    assert updated.review_owner_id == reviewer.id
    assert updated.review_due_date == date(2026, 7, 1)
    assert updated.expiry_date == date(2026, 8, 1)
    assert updated.trust_level == "gold"
