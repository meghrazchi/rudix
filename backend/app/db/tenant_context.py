"""Database session tenant context and SQLAlchemy ORM tenant isolation guard.

Provides defense-in-depth multi-tenant isolation at the SQLAlchemy ORM and
PostgreSQL transaction layers:
- Binds the active tenant (`organization_id`) to `AsyncSession.info` and a
  context variable (`current_tenant_id`).
- Automatically filters ORM SELECT statements via `with_loader_criteria` when
  `enforce_tenant_guard` is enabled on the session or execution options.
- Blocks cross-tenant ORM writes during `before_flush` when a model's
  `organization_id` does not match the session's bound tenant.
- Sets PostgreSQL transaction-local `app.current_organization_id` via
  `set_config(..., is_local=true)` for Row-Level Security (RLS) policies.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

_CURRENT_TENANT_ID: ContextVar[UUID | None] = ContextVar("current_tenant_id", default=None)

# Models that represent cross-org identity or membership lookups and must not
# be implicitly restricted by `organization_id` loader criteria.
_EXEMPT_MODEL_NAMES: frozenset[str] = frozenset(
    {
        "User",
        "Organization",
        "OrganizationMember",
    }
)

_GUARD_INSTALLED = False


class TenantIsolationError(RuntimeError):
    """Raised when an ORM operation violates the active session tenant boundary."""


def get_current_tenant_id() -> UUID | None:
    """Return the active tenant UUID from the current async context, if any."""
    return _CURRENT_TENANT_ID.get()


def _coerce_uuid(value: UUID | str | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    stripped = str(value).strip()
    if not stripped:
        return None
    try:
        return UUID(stripped)
    except ValueError:
        return None


def bind_session_tenant(
    db_session: Any,
    organization_id: UUID | str | None,
    *,
    enforce_guard: bool = False,
) -> UUID | None:
    """Bind `organization_id` onto `db_session.info` and the context var."""
    org_uuid = _coerce_uuid(organization_id)
    _CURRENT_TENANT_ID.set(org_uuid)

    session_info = getattr(db_session, "info", None)
    if isinstance(session_info, dict):
        session_info["organization_id"] = org_uuid
        if enforce_guard:
            session_info["enforce_tenant_guard"] = True
    return org_uuid


async def set_postgres_tenant_context(
    db_session: AsyncSession,
    organization_id: UUID | str,
) -> None:
    """Set transaction-local `app.current_organization_id` on PostgreSQL sessions."""
    org_uuid = _coerce_uuid(organization_id)
    if org_uuid is None:
        raise ValueError("Valid organization_id UUID is required for PostgreSQL tenant context")

    await db_session.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, true)"),
        {"org_id": str(org_uuid)},
    )


@contextmanager
def tenant_scoped_session(
    db_session: Any,
    organization_id: UUID | str,
) -> Iterator[UUID]:
    """Context manager that enables strict ORM read/write tenant guard on `db_session`."""
    org_uuid = _coerce_uuid(organization_id)
    if org_uuid is None:
        raise ValueError("Valid organization_id UUID is required for tenant_scoped_session")

    install_sqlalchemy_tenant_guard()
    token = _CURRENT_TENANT_ID.set(org_uuid)
    session_info = getattr(db_session, "info", None)
    prev_org = session_info.get("organization_id") if isinstance(session_info, dict) else None
    prev_enforce = (
        session_info.get("enforce_tenant_guard", False) if isinstance(session_info, dict) else False
    )

    if isinstance(session_info, dict):
        session_info["organization_id"] = org_uuid
        session_info["enforce_tenant_guard"] = True

    try:
        yield org_uuid
    finally:
        _CURRENT_TENANT_ID.reset(token)
        if isinstance(session_info, dict):
            session_info["organization_id"] = prev_org
            session_info["enforce_tenant_guard"] = prev_enforce


def _is_tenant_scoped_entity(entity: Any) -> bool:
    if not isinstance(entity, type):
        return False
    if entity.__name__ in _EXEMPT_MODEL_NAMES:
        return False
    return hasattr(entity, "organization_id") and hasattr(entity, "__mapper__")


def _build_tenant_criterion(tenant_id: UUID) -> Callable[[Any], Any]:
    def _criterion(cls: Any) -> Any:
        return cls.organization_id == tenant_id

    return _criterion


def _on_do_orm_execute(orm_execute_state: ORMExecuteState) -> None:
    if orm_execute_state.execution_options.get("bypass_tenant_guard", False):
        return

    session_info = orm_execute_state.session.info
    enforce = bool(
        orm_execute_state.execution_options.get(
            "enforce_tenant_guard",
            session_info.get("enforce_tenant_guard", False),
        )
    )
    if not enforce or not orm_execute_state.is_select:
        return

    tenant_id = _coerce_uuid(session_info.get("organization_id"))
    if tenant_id is None:
        raise TenantIsolationError(
            "ORM query executed with enforce_tenant_guard=True but no organization_id is bound"
        )

    stmt = orm_execute_state.statement
    criterion = _build_tenant_criterion(tenant_id)
    for mapper in orm_execute_state.all_mappers:
        entity = mapper.class_
        if _is_tenant_scoped_entity(entity):
            stmt = stmt.options(
                with_loader_criteria(
                    entity,
                    criterion,
                    include_aliases=True,
                )
            )
    orm_execute_state.statement = stmt


def _on_before_flush(session: Session, _flush_context: Any, _instances: Any) -> None:
    session_info = session.info
    if not session_info.get("enforce_tenant_guard", False):
        return

    tenant_id = _coerce_uuid(session_info.get("organization_id"))
    if tenant_id is None:
        raise TenantIsolationError(
            "ORM flush executed with enforce_tenant_guard=True but no organization_id is bound"
        )

    for obj in list(session.new) + list(session.dirty):
        cls = type(obj)
        if not _is_tenant_scoped_entity(cls):
            continue
        obj_org_id = _coerce_uuid(getattr(obj, "organization_id", None))
        if obj_org_id is None and obj in session.new:
            obj.organization_id = tenant_id
            continue
        if obj_org_id != tenant_id:
            raise TenantIsolationError(
                f"Cross-tenant write blocked for {cls.__name__}: "
                f"object organization_id={obj_org_id} does not match session tenant {tenant_id}"
            )


def install_sqlalchemy_tenant_guard() -> None:
    """Idempotently register SQLAlchemy ORM tenant isolation listeners on `Session`."""
    global _GUARD_INSTALLED
    if _GUARD_INSTALLED:
        return
    event.listen(Session, "do_orm_execute", _on_do_orm_execute)
    event.listen(Session, "before_flush", _on_before_flush)
    _GUARD_INSTALLED = True
