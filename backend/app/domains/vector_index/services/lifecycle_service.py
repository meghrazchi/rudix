"""Generation lifecycle: adopt, register, verify, swap, rollback, drop-retired (R06-08).

Operator commands (``scripts/vector_index.py``) and the startup reconcile call these.
Every state change commits before the registry cache is invalidated, so a process sees
the new state within ``VECTOR_INDEX_REGISTRY_CACHE_SECONDS``.

States: ``building`` (dual writes on) -> ``verifying`` (counts matched, ready to swap;
dual writes stay on) -> ``active`` -> ``retired`` (rollback target until ``retire_after``)
-> ``dropped`` (collection deleted). A count mismatch sets ``failed`` with ``error_code``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.vector_index.repositories import generations as repo
from app.domains.vector_index.services import qdrant_ops
from app.domains.vector_index.services.generation_service import (
    configured_alias,
    generation_collection_name,
    registry,
)
from app.models.vector_index import VectorIndexGeneration

logger = get_logger("vector_index")


class VectorIndexLifecycleError(RuntimeError):
    """A lifecycle step that cannot run; ``code`` is a stable, safe identifier."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


@dataclass
class VerifyResult:
    generation: int
    expected_points: int
    actual_points: int
    documents_total: int
    documents_done: int
    passed: bool
    error_code: str | None = None


@dataclass
class SwapPlan:
    action: str
    alias: str
    from_generation: int | None
    to_generation: int
    to_collection: str
    applied: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def _session() -> Any:
    from app.db import session as db_session_module

    return db_session_module.SessionLocal()


def _maintenance() -> Any:
    """Cross-tenant reads (counts across organisations), resolved at call time."""
    from app.db import session as db_session_module

    return db_session_module.maintenance_session()


def require_alias() -> str:
    alias = configured_alias()
    if alias is None:
        raise VectorIndexLifecycleError(
            "legacy_mode", "QDRANT_COLLECTION_ALIAS is not set (legacy mode)"
        )
    return alias


def now_utc() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def list_rows(alias: str) -> list[VectorIndexGeneration]:
    async with _session() as session:
        rows = await repo.list_generations(session, alias_name=alias)
        session.expunge_all()
    return rows


async def adopt(*, embedding_model: str | None = None) -> VectorIndexGeneration:
    """Register ``QDRANT_COLLECTION`` as generation 1 and point the alias at it (no copy)."""
    alias = require_alias()
    rows = await list_rows(alias)
    active = repo.pick(rows, ("active",))
    if active is not None:
        return active
    if rows:
        raise VectorIndexLifecycleError("already_registered", "generations exist but none active")
    legacy = settings.qdrant_collection
    params = await qdrant_ops.vector_params(legacy)
    if params is None:
        raise VectorIndexLifecycleError("collection_missing", f"collection {legacy} not found")
    if await qdrant_ops.vector_params(alias) is not None:
        raise VectorIndexLifecycleError("alias_conflict", "a collection already has the alias name")
    current = await qdrant_ops.alias_target(alias)
    if current is not None and current != legacy:
        raise VectorIndexLifecycleError("alias_points_elsewhere", f"alias points at {current}")
    if current is None:
        await qdrant_ops.create_alias(alias, legacy)
    model = (embedding_model or settings.openai_embedding_model).strip()
    async with _session() as session, session.begin():
        row = await repo.create_generation(
            session,
            alias_name=alias,
            collection_name=legacy,
            embedding_model=model,
            vector_size=params[0],
            distance=params[1] or settings.qdrant_distance.value,
            generation=1,
            state="active",
            activated_at=now_utc(),
        )
    registry.invalidate()
    logger.info(
        "vector_index.adopted",
        alias=alias,
        collection=legacy,
        embedding_model=model,
        vector_size=params[0],
    )
    return row


async def register_building(
    *,
    embedding_model: str | None = None,
    vector_size: int | None = None,
    distance: str | None = None,
    reason: str = "operator",
) -> VectorIndexGeneration:
    """A building generation for the model; returns the existing one when it matches."""
    alias = require_alias()
    model = (embedding_model or settings.openai_embedding_model).strip()
    size = int(vector_size or settings.qdrant_vector_size)
    metric = distance or settings.qdrant_distance.value
    rows = await list_rows(alias)
    if repo.pick(rows, ("active",)) is None:
        raise VectorIndexLifecycleError("not_adopted", "run adopt first")
    building = repo.pick(rows, repo.BUILDING_STATES)
    if building is not None:
        if (building.embedding_model, building.vector_size) == (model, size):
            return building
        raise VectorIndexLifecycleError(
            "building_exists", f"generation {building.generation} is still building"
        )
    number = max(row.generation for row in rows) + 1
    name = generation_collection_name(model, number)
    await qdrant_ops.create_collection(name, vector_size=size, distance=metric)
    async with _session() as session, session.begin():
        row = await repo.create_generation(
            session,
            alias_name=alias,
            collection_name=name,
            embedding_model=model,
            vector_size=size,
            distance=metric,
            generation=number,
            state="building",
        )
    registry.invalidate()
    logger.info(
        "vector_index.generation.registered",
        alias=alias,
        generation=number,
        collection=name,
        embedding_model=model,
        vector_size=size,
        reason=reason,
    )
    return row


async def set_state(row_id: Any, **values: Any) -> None:
    async with _session() as session, session.begin():
        row = await repo.get_by_id(session, row_id)
        if row is None:
            raise VectorIndexLifecycleError("generation_missing")
        for key, value in values.items():
            setattr(row, key, value)
    registry.invalidate()


async def verify(*, generation: int | None = None) -> VerifyResult:
    """Compare the generation's point count with the expected embeddable chunk rows."""
    alias = require_alias()
    rows = await list_rows(alias)
    if generation is not None:
        target = next((r for r in rows if r.generation == generation), None)
    else:
        target = repo.pick(rows, (*repo.BUILDING_STATES, "failed"))
    if target is None or target.state not in (*repo.BUILDING_STATES, "failed"):
        raise VectorIndexLifecycleError("nothing_to_verify")
    await set_state(target.id, state="verifying", error_code=None)
    versions = settings.active_index_versions
    async with _maintenance() as session:
        expected = await repo.expected_points(session, index_versions=versions)
        total = await repo.count_indexed_documents(session)
        done, _ = await repo.generation_progress(session, generation_id=target.id)
        await session.rollback()
    actual = await qdrant_ops.count_points(target.collection_name, index_versions=versions)
    error_code = None
    if actual != expected:
        error_code = "point_count_mismatch"
    elif done < total:
        error_code = "documents_missing"
    await set_state(
        target.id,
        state="verifying" if error_code is None else "failed",
        error_code=error_code,
        expected_points=expected,
        indexed_points=actual,
        documents_total=total,
        documents_done=done,
    )
    result = VerifyResult(
        generation=target.generation,
        expected_points=expected,
        actual_points=actual,
        documents_total=total,
        documents_done=done,
        passed=error_code is None,
        error_code=error_code,
    )
    log = logger.info if result.passed else logger.warning
    log(
        "vector_index.generation.verified",
        generation=target.generation,
        expected_points=expected,
        actual_points=actual,
        documents_total=total,
        documents_done=done,
        error_code=error_code,
    )
    return result


async def _move_alias(
    *, alias: str, to_row: VectorIndexGeneration, from_row: VectorIndexGeneration
) -> None:
    """One alias call, then the state change; the alias moves back if the commit fails."""
    await qdrant_ops.swap_alias(alias, to_row.collection_name)
    moment = now_utc()
    try:
        async with _session() as session, session.begin():
            old = await repo.get_by_id(session, from_row.id)
            new = await repo.get_by_id(session, to_row.id)
            if old is None or new is None:
                raise VectorIndexLifecycleError("generation_missing")
            old.state = "retired"
            old.retire_after = moment + timedelta(hours=settings.qdrant_retired_grace_hours)
            new.state = "active"
            new.activated_at = moment
            new.retire_after = None
            new.error_code = None
    except BaseException:
        await qdrant_ops.swap_alias(alias, from_row.collection_name)
        raise
    finally:
        registry.invalidate()


async def swap(*, dry_run: bool = True) -> SwapPlan:
    """Point the alias at the verified generation; the active one becomes retired."""
    alias = require_alias()
    rows = await list_rows(alias)
    active = repo.pick(rows, ("active",))
    target = repo.pick(rows, ("verifying",))
    if active is None or target is None:
        raise VectorIndexLifecycleError("not_verified", "no verified generation to swap to")
    plan = SwapPlan(
        action="swap",
        alias=alias,
        from_generation=active.generation,
        to_generation=target.generation,
        to_collection=target.collection_name,
    )
    if dry_run:
        return plan
    result = await verify(generation=target.generation)
    if not result.passed:
        raise VectorIndexLifecycleError(result.error_code or "verify_failed")
    await _move_alias(alias=alias, to_row=target, from_row=active)
    plan.applied = True
    logger.info(
        "vector_index.alias.swapped",
        alias=alias,
        from_generation=active.generation,
        to_generation=target.generation,
        grace_hours=settings.qdrant_retired_grace_hours,
    )
    return plan


async def rollback(*, dry_run: bool = True) -> SwapPlan:
    """Point the alias back at the newest retired generation."""
    alias = require_alias()
    rows = await list_rows(alias)
    active = repo.pick(rows, ("active",))
    target = repo.pick([r for r in rows if active is None or r.id != active.id], ("retired",))
    if active is None or target is None:
        raise VectorIndexLifecycleError("nothing_to_roll_back")
    plan = SwapPlan(
        action="rollback",
        alias=alias,
        from_generation=active.generation,
        to_generation=target.generation,
        to_collection=target.collection_name,
    )
    if dry_run:
        return plan
    await _move_alias(alias=alias, to_row=target, from_row=active)
    plan.applied = True
    logger.info(
        "vector_index.alias.rolled_back",
        alias=alias,
        from_generation=active.generation,
        to_generation=target.generation,
    )
    return plan


async def drop_retired(*, dry_run: bool = True, now: datetime | None = None) -> list[int]:
    """Delete collections of retired generations whose grace period has passed.

    Never in legacy mode, never the active generation or the alias's current target.
    """
    alias = require_alias()
    moment = now or now_utc()
    rows = await list_rows(alias)
    active = repo.pick(rows, ("active",))
    protected = {await qdrant_ops.alias_target(alias)}
    if active is not None:
        protected.add(active.collection_name)
    due = [
        row
        for row in rows
        if row.state == "retired"
        and (retire_after := _aware(row.retire_after)) is not None
        and retire_after <= moment
        and row.collection_name not in protected
    ]
    if dry_run:
        return [row.generation for row in due]
    for row in due:
        await qdrant_ops.delete_collection(row.collection_name)
        await set_state(row.id, state="dropped")
        logger.info(
            "vector_index.generation.dropped",
            alias=alias,
            generation=row.generation,
            collection=row.collection_name,
        )
    return [row.generation for row in due]


def describe(row: VectorIndexGeneration) -> dict[str, Any]:
    """Operator view of one generation (CLI output; never returned by the admin API)."""
    return {
        "generation": row.generation,
        "state": row.state,
        "collection": row.collection_name,
        "embedding_model": row.embedding_model,
        "vector_size": row.vector_size,
        "documents_total": row.documents_total,
        "documents_done": row.documents_done,
        "expected_points": row.expected_points,
        "indexed_points": row.indexed_points,
        "error_code": row.error_code,
        "activated_at": row.activated_at.isoformat() if row.activated_at else None,
        "retire_after": row.retire_after.isoformat() if row.retire_after else None,
    }
