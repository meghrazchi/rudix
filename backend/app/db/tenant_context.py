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

R04-08 adds the mode-aware session context:
- An `after_begin` listener runs one marked statement (`SESSION_CONTEXT_MARKER`) per
  transaction that sets `app.current_organization_id` and `app.rls_mode` (and, in
  PgBouncer mode, the statement and idle-in-transaction timeouts). The tenant comes from
  `session.info["organization_id"]`, else from the context variable.
- `apply_tenant_context(session)` runs it for a transaction that is already open.
- In `soft` mode, ORM statements and flushes that touch a strict RLS table with no tenant
  bound are logged (`rls.soft_denial`, throttled) and counted
  (`rudix_rls_soft_denials_total{table}`); nothing is denied.
- Sessions with `info["rls_maintenance"] = True` never bind a tenant and are not counted.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session, SessionTransaction, with_loader_criteria

from app.core.config import RlsEnforcement, settings
from app.core.logging import get_logger
from app.core.metrics import registry
from app.db.rls import RLS_STRICT_TABLES

SESSION_CONTEXT_MARKER = "/* rudix:session-context */"
RLS_MAINTENANCE_INFO_KEY = "rls_maintenance"
SOFT_DENIAL_LOG_INTERVAL_SECONDS = 60.0

RLS_SOFT_DENIALS_TOTAL = Counter(
    "rudix_rls_soft_denials_total",
    "ORM statements or flushes on a strict RLS table with no tenant bound (soft mode)",
    ["table"],
    registry=registry,
)

# 0.5.0 (S3): tenants bound by unauthenticated paths from the token, installation, or
# organisation they resolved (`bind_resolved_tenant`). The label set is fixed.
ResolvedTenantPath = Literal["agent_trace_share", "auth_audit", "bot_inbound"]
RLS_RESOLVED_TENANT_BINDINGS_TOTAL = Counter(
    "rudix_rls_resolved_tenant_bindings_total",
    "Tenants bound by unauthenticated paths before they touch strict RLS tables",
    ["path"],
    registry=registry,
)

_STRICT_TABLES: frozenset[str] = frozenset(RLS_STRICT_TABLES)
_soft_denial_last_logged: dict[str, float] = {}
_rls_logger = get_logger("events.rls")

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


# --- R04-08: session context and soft-mode detection ----------------------------------


def effective_rls_mode() -> RlsEnforcement:
    return settings.effective_rls_enforcement


def _is_maintenance(session: Any) -> bool:
    info = getattr(session, "info", None)
    return bool(isinstance(info, dict) and info.get(RLS_MAINTENANCE_INFO_KEY, False))


def _session_tenant(session: Any) -> UUID | None:
    info = getattr(session, "info", None)
    if isinstance(info, dict):
        bound = _coerce_uuid(info.get("organization_id"))
        if bound is not None:
            return bound
    return _CURRENT_TENANT_ID.get()


def build_session_context_statement(
    organization_id: UUID | None,
    mode: RlsEnforcement,
    *,
    include_tenant: bool,
) -> tuple[str, dict[str, str]] | None:
    """Return the marked `set_config` statement and its parameters, or None when not needed."""
    parts: list[str] = []
    params: dict[str, str] = {}
    if include_tenant:
        parts.append("set_config('app.current_organization_id', :org, true)")
        parts.append("set_config('app.rls_mode', :mode, true)")
        params["org"] = str(organization_id) if organization_id is not None else ""
        params["mode"] = mode.value
    if settings.db_pgbouncer_mode:
        # PgBouncer transaction pooling ignores startup parameters; set them per transaction.
        if settings.db_statement_timeout_ms > 0:
            parts.append("set_config('statement_timeout', :statement_timeout, true)")
            params["statement_timeout"] = str(settings.db_statement_timeout_ms)
        if settings.db_idle_in_transaction_timeout_ms > 0:
            parts.append("set_config('idle_in_transaction_session_timeout', :idle_timeout, true)")
            params["idle_timeout"] = str(settings.db_idle_in_transaction_timeout_ms)
    if not parts:
        return None
    return f"{SESSION_CONTEXT_MARKER} SELECT {', '.join(parts)}", params


def _context_statement_for(session: Any) -> tuple[str, dict[str, str]] | None:
    mode = effective_rls_mode()
    organization_id = _session_tenant(session)
    include_tenant = mode != RlsEnforcement.off and not _is_maintenance(session)
    if include_tenant and mode == RlsEnforcement.soft and organization_id is None:
        # Soft mode with no tenant behaves like an unset setting; skip the round trip.
        include_tenant = False
    return build_session_context_statement(organization_id, mode, include_tenant=include_tenant)


def _on_after_begin(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    if transaction.nested or connection.dialect.name != "postgresql":
        return
    statement = _context_statement_for(session)
    if statement is not None:
        connection.execute(text(statement[0]), statement[1])


async def apply_tenant_context(db_session: AsyncSession) -> None:
    """Run the session-context statement for the transaction that is already open.

    A transaction that starts later gets it from the `after_begin` listener.
    """
    if not db_session.in_transaction():
        return
    connection = await db_session.connection()
    if connection.dialect.name != "postgresql":
        return
    statement = _context_statement_for(db_session.sync_session)
    if statement is not None:
        await connection.execute(text(statement[0]), statement[1])


async def bind_resolved_tenant(
    db_session: AsyncSession,
    organization_id: UUID | str | None,
    *,
    path: ResolvedTenantPath,
) -> UUID | None:
    """Bind the tenant an unauthenticated path resolved before it touches strict tables.

    For the known gaps of R04-08 (0.5.0, S3): the shared agent trace page (from the share
    token), pre-authentication audit writes (login, refresh, logout, SSO: from the user,
    session, or SSO configuration), and bot inbound events (from the installation). It binds
    `session.info` and the context variable, then runs the session-context statement for a
    transaction that is already open. Unlike `bind_pipeline_session` it never turns on the
    ORM guard: these flows switch organisation as they go (a login audits the home
    organisation, then opens a session in the selected one); the database policy is the check.
    """
    org_uuid = bind_session_tenant(db_session, organization_id)
    await apply_tenant_context(db_session)
    RLS_RESOLVED_TENANT_BINDINGS_TOTAL.labels(path=path).inc()
    _rls_logger.debug(
        "rls.tenant_bound",
        path=path,
        organization_id=str(org_uuid) if org_uuid is not None else None,
        mode=effective_rls_mode().value,
    )
    return org_uuid


async def bind_pipeline_session(
    db_session: AsyncSession,
    organization_id: UUID | str | None,
) -> UUID | None:
    """Bind a chat pipeline session to its tenant (R05-02, plan contract 4.2.9).

    Same binding as an authenticated HTTP request: `session.info` and the context
    variable, the ORM guard in `strict`, then the session-context statement for a
    transaction that is already open (a later one gets it from `after_begin`).
    """
    org_uuid = bind_session_tenant(
        db_session,
        organization_id,
        enforce_guard=effective_rls_mode() == RlsEnforcement.strict,
    )
    await apply_tenant_context(db_session)
    return org_uuid


@contextmanager
def tenant_context_scope(organization_id: UUID | str | None) -> Iterator[UUID | None]:
    """Bind the tenant context variable for a block and restore the previous value.

    Tasks created inside the block (for example the parallel retrieval branches of a
    chat run) copy the context and inherit the tenant.
    """
    org_uuid = _coerce_uuid(organization_id)
    token = _CURRENT_TENANT_ID.set(org_uuid)
    try:
        yield org_uuid
    finally:
        _CURRENT_TENANT_ID.reset(token)


@contextmanager
def bind_worker_tenant(organization_id: UUID | str | None) -> Iterator[UUID | None]:
    """Bind a Celery task to the tenant named by its ``organization_id`` (R06-01 part 2).

    Plan contract 4.2.7: every session the task opens inside the block sets
    ``app.current_organization_id`` (``after_begin``), so strict row-level security applies
    to worker writes as it does to requests. ``None`` or an unparsable value binds nothing
    (beat tasks, old messages); those paths use ``maintenance_session()`` or resolve the
    tenant first. The previous binding is restored on exit, so nested tasks (eager chains in
    tests) do not leak their tenant.
    """
    with tenant_context_scope(organization_id) as org_uuid:
        yield org_uuid


def _record_soft_denial(table: str, operation: str) -> None:
    RLS_SOFT_DENIALS_TOTAL.labels(table=table).inc()
    now = time.monotonic()
    last = _soft_denial_last_logged.get(table)
    if last is not None and now - last < SOFT_DENIAL_LOG_INTERVAL_SECONDS:
        return
    _soft_denial_last_logged[table] = now
    _rls_logger.warning("rls.soft_denial", table=table, operation=operation)


def _soft_check_applies(session: Any) -> bool:
    if effective_rls_mode() != RlsEnforcement.soft:
        return False
    if _is_maintenance(session):
        return False
    return _session_tenant(session) is None


def _mapper_table_name(mapper: Any) -> str | None:
    table = getattr(mapper, "local_table", None)
    name = getattr(table, "name", None)
    return name if isinstance(name, str) else None


def _orm_operation(orm_execute_state: ORMExecuteState) -> str:
    if orm_execute_state.is_select:
        return "select"
    if orm_execute_state.is_insert:
        return "insert"
    if orm_execute_state.is_update:
        return "update"
    if orm_execute_state.is_delete:
        return "delete"
    return "other"


def _on_do_orm_execute_soft(orm_execute_state: ORMExecuteState) -> None:
    if not _soft_check_applies(orm_execute_state.session):
        return
    operation = _orm_operation(orm_execute_state)
    seen: set[str] = set()
    for mapper in orm_execute_state.all_mappers:
        name = _mapper_table_name(mapper)
        if name in _STRICT_TABLES and name not in seen:
            seen.add(name)
            _record_soft_denial(name, operation)


def _on_before_flush_soft(session: Session, _flush_context: Any, _instances: Any) -> None:
    if not _soft_check_applies(session):
        return
    pending: list[tuple[str, Any]] = [
        *(("insert", obj) for obj in session.new),
        *(("update", obj) for obj in session.dirty),
        *(("delete", obj) for obj in session.deleted),
    ]
    seen: set[tuple[str, str]] = set()
    for operation, obj in pending:
        name = _mapper_table_name(getattr(type(obj), "__mapper__", None))
        if name in _STRICT_TABLES and (name, operation) not in seen:
            seen.add((name, operation))
            _record_soft_denial(name, operation)


def install_sqlalchemy_tenant_guard() -> None:
    """Idempotently register SQLAlchemy ORM tenant isolation listeners on `Session`."""
    global _GUARD_INSTALLED
    if _GUARD_INSTALLED:
        return
    event.listen(Session, "do_orm_execute", _on_do_orm_execute)
    event.listen(Session, "before_flush", _on_before_flush)
    event.listen(Session, "after_begin", _on_after_begin)
    event.listen(Session, "do_orm_execute", _on_do_orm_execute_soft)
    event.listen(Session, "before_flush", _on_before_flush_soft)
    _GUARD_INSTALLED = True
