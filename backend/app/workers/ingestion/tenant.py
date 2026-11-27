"""Tenant checks of the document tasks (R06-01 part 2, plan contract 4.2.7).

``RudixTask.__call__`` binds the tenant named by the ``organization_id`` kwarg. Before any
write, a document task confirms that the document belongs to that organisation:

- visible through the bound session and owned by another organisation, or invisible to it
  (strict row-level security hides other tenants) but present when read through
  ``maintenance_session()``: ``TenantMismatchError``;
- missing everywhere: the caller's existing not-found handling applies.

A ``documents.process`` message without ``organization_id`` (published before 0.6.0)
resolves it with one ``maintenance_session()`` read.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.logging import get_logger
from app.models.document import Document
from app.workers.base_task import TenantMismatchError
from app.workers.ingestion.deps import current_deps

logger = get_logger("worker.ingestion")


def _uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        return None


async def _owner_via(session_factory: Any, document_id: UUID) -> UUID | None:
    async with session_factory() as session:
        stmt = select(Document.organization_id).where(Document.id == document_id)
        return (await session.execute(stmt)).scalar_one_or_none()


async def _owner_via_maintenance(document_id: UUID) -> UUID | None:
    from app.db.session import maintenance_session

    try:
        async with maintenance_session() as session:
            stmt = select(Document.organization_id).where(Document.id == document_id)
            return (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        # Without a reachable maintenance role the document counts as missing.
        logger.warning(
            "ingestion.tenant_lookup_failed",
            document_id=str(document_id),
            error_type=type(exc).__name__,
        )
        return None


async def check_document_tenant(document_id: Any, organization_id: Any) -> None:
    """Raise ``TenantMismatchError`` when the document belongs to another organisation."""
    document_uuid = _uuid(document_id)
    expected = _uuid(organization_id)
    if document_uuid is None or expected is None:
        return
    owner = await _owner_via(current_deps().SessionLocal, document_uuid)
    if owner is None:
        owner = await _owner_via_maintenance(document_uuid)
    if owner is not None and owner != expected:
        raise TenantMismatchError()


async def resolve_document_organization(document_id: Any) -> str | None:
    """Organisation of a document for an old message without ``organization_id``."""
    document_uuid = _uuid(document_id)
    if document_uuid is None:
        return None
    owner = await _owner_via_maintenance(document_uuid)
    return str(owner) if owner is not None else None


def ensure_document_tenant(document_id: Any, organization_id: Any) -> None:
    """Synchronous form for the Celery task bodies."""
    if _uuid(document_id) is None or _uuid(organization_id) is None:
        return
    current_deps().run(check_document_tenant(document_id, organization_id))
