from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.services.audit_service import AuditLogService, sanitize_metadata
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User


async def _seed_org_user(db_session: AsyncSession) -> tuple[UUID, UUID]:
    organization = Organization(name="Audit Org", slug=f"audit-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"audit-user-{uuid4().hex[:8]}",
        email=f"audit-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    membership = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role=OrganizationRole.admin.value,
    )
    db_session.add(membership)
    await db_session.commit()
    return organization.id, user.id


def test_sanitize_metadata_redacts_sensitive_and_content_fields() -> None:
    sanitized = sanitize_metadata(
        {
            "password": "secret-value",
            "authorization": "Bearer my.token.value",
            "question": "What is in the document?",
            "document_text": "Highly sensitive body",
            "metadata": {"api_key": "k-123"},
            "notes": "token=abc123",
            "safe_number": 42,
        }
    )

    assert sanitized["password"] == "***"
    assert sanitized["authorization"] == "***"
    assert sanitized["question"] == "<redacted:question>"
    assert sanitized["document_text"] == "<redacted:document_text>"
    assert sanitized["metadata"]["api_key"] == "***"
    assert sanitized["notes"] == "token=***"
    assert sanitized["safe_number"] == 42


@pytest.mark.asyncio
async def test_audit_service_persists_audit_log_with_sanitized_metadata(db_session: AsyncSession) -> None:
    organization_id, user_id = await _seed_org_user(db_session)
    service = AuditLogService()

    wrote = await service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.query.completed",
        resource_type="chat_session",
        request_id="req-audit-1",
        metadata={
            "question": "What is in the document?",
            "raw_token": "abcd",
            "retrieval_count": 3,
        },
    )
    assert wrote is True
    await db_session.commit()

    rows = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(rows) == 1
    assert rows[0].action == "chat.query.completed"
    assert rows[0].metadata_json["request_id"] == "req-audit-1"
    assert rows[0].metadata_json["question"] == "<redacted:question>"
    assert rows[0].metadata_json["raw_token"] == "***"
    assert rows[0].metadata_json["retrieval_count"] == 3


class _FailingUsageRepository:
    async def create_audit_log(self, *_: object, **__: object) -> object:
        raise RuntimeError("audit write failed")


@pytest.mark.asyncio
async def test_audit_service_fail_open_by_default(db_session: AsyncSession) -> None:
    organization_id, user_id = await _seed_org_user(db_session)
    service = AuditLogService(usage_repository=_FailingUsageRepository())  # type: ignore[arg-type]
    wrote = await service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="document.upload.accepted",
        resource_type="document",
    )
    assert wrote is False


@pytest.mark.asyncio
async def test_audit_service_can_fail_closed_when_required(db_session: AsyncSession) -> None:
    organization_id, user_id = await _seed_org_user(db_session)
    service = AuditLogService(usage_repository=_FailingUsageRepository())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="audit write failed"):
        await service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="document.upload.accepted",
            resource_type="document",
            required=True,
        )
