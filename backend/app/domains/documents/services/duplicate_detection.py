from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.repositories.documents import DocumentRepository

DuplicateAction = Literal["allow", "warn", "reject"]


@dataclass(frozen=True)
class DuplicateDetectionResult:
    is_duplicate: bool
    action: DuplicateAction
    existing_document_id: UUID | None = None


_repository = DocumentRepository()


async def check_for_duplicate(
    db_session: AsyncSession,
    *,
    checksum: str,
    organization_id: UUID,
    enabled: bool = True,
    action: DuplicateAction = "warn",
) -> DuplicateDetectionResult:
    """Query the org's documents for an existing record with the same SHA-256 checksum.

    Only active (non-deleted, non-blocked) documents are considered duplicates so that
    re-uploading after deletion or a blocked upload works correctly.
    """
    if not enabled or not checksum:
        return DuplicateDetectionResult(is_duplicate=False, action="allow")

    existing_id = await _repository.find_active_document_id_by_checksum(
        db_session,
        checksum=checksum,
        organization_id=organization_id,
    )
    if existing_id is None:
        return DuplicateDetectionResult(is_duplicate=False, action="allow")

    return DuplicateDetectionResult(
        is_duplicate=True,
        action=action,
        existing_document_id=existing_id,
    )
