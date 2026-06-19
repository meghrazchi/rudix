"""Business logic for quota and rate-limit policy management.

Handles policy upsert/delete with change-log snapshotting, usage tracking,
quota enforcement checks, and override resolution.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.quota.repositories.quota_repository import QuotaRepository
from app.domains.quota.schemas.quota_schemas import (
    OrgQuotaDashboardResponse,
    QuotaCheckResult,
    QuotaType,
    QuotaUsageItem,
    ResetWindow,
)
from app.models.organization_member import OrganizationMember
from app.models.quotas import OrgQuotaPolicy, OrgQuotaUsage

_repo = QuotaRepository()

NEAR_LIMIT_THRESHOLD = 0.80

# System defaults — no limits out of the box; orgs configure their own
SYSTEM_DEFAULT_LIMITS: dict[str, dict] = {
    QuotaType.seats: {
        "soft_limit": None,
        "hard_limit": None,
        "reset_window": ResetWindow.none,
    },
    QuotaType.uploads: {
        "soft_limit": None,
        "hard_limit": None,
        "reset_window": ResetWindow.per_day,
    },
    QuotaType.questions: {
        "soft_limit": None,
        "hard_limit": None,
        "reset_window": ResetWindow.per_day,
    },
    QuotaType.tokens: {
        "soft_limit": None,
        "hard_limit": None,
        "reset_window": ResetWindow.per_month,
    },
    QuotaType.storage_bytes: {
        "soft_limit": None,
        "hard_limit": None,
        "reset_window": ResetWindow.none,
    },
    QuotaType.evaluations: {
        "soft_limit": None,
        "hard_limit": None,
        "reset_window": ResetWindow.per_day,
    },
    QuotaType.api_calls: {
        "soft_limit": None,
        "hard_limit": None,
        "reset_window": ResetWindow.per_minute,
    },
    QuotaType.connectors: {
        "soft_limit": None,
        "hard_limit": None,
        "reset_window": ResetWindow.none,
    },
    QuotaType.agent_runs: {
        "soft_limit": None,
        "hard_limit": None,
        "reset_window": ResetWindow.per_day,
    },
}


def _compute_next_reset(window: str, now: datetime) -> datetime | None:
    """Return when the current usage window ends, or None for permanent caps."""
    if window == ResetWindow.none:
        return None
    if window == ResetWindow.per_minute:
        return now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if window == ResetWindow.per_hour:
        return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if window == ResetWindow.per_day:
        return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    if window == ResetWindow.per_month:
        if now.month == 12:
            return now.replace(
                year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
        return now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def _normalize_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _reset_window_expired(next_reset_at: datetime | None, now: datetime) -> bool:
    normalized_next_reset_at = _normalize_utc(next_reset_at)
    return normalized_next_reset_at is not None and normalized_next_reset_at <= now


def _policy_snapshot(policy: OrgQuotaPolicy) -> dict:
    return {"limits": dict(policy.limits or {})}


async def _current_seat_count(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> int:
    result = await db_session.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == organization_id
        )
    )
    return int(result.scalar_one())


def get_effective_limits(policy: OrgQuotaPolicy | None) -> dict[str, dict]:
    """Merge org policy over system defaults for all quota types."""
    effective: dict[str, dict] = {}
    for qt in QuotaType:
        default = dict(SYSTEM_DEFAULT_LIMITS[qt])
        if policy is not None:
            org_config = (policy.limits or {}).get(qt)
            if org_config is not None:
                effective[qt] = {**default, **org_config}
                continue
        effective[qt] = default
    return effective


def _usage_item(
    quota_type: str,
    usage: OrgQuotaUsage | None,
    limit_config: dict,
) -> QuotaUsageItem:
    current = usage.current_value if usage is not None else 0
    soft = limit_config.get("soft_limit")
    hard = limit_config.get("hard_limit")
    reset_window = limit_config.get("reset_window", ResetWindow.per_day)
    next_reset_at = _normalize_utc(usage.next_reset_at) if usage is not None else None

    near = False
    over_soft = False
    over_hard = False

    ref_limit = hard if hard is not None else soft
    if ref_limit is not None and ref_limit > 0:
        near = current >= (ref_limit * NEAR_LIMIT_THRESHOLD)
    if soft is not None:
        over_soft = current > soft
    if hard is not None:
        over_hard = current > hard

    return QuotaUsageItem(
        quota_type=quota_type,
        current_value=current,
        soft_limit=soft,
        hard_limit=hard,
        reset_window=reset_window,
        next_reset_at=next_reset_at,
        near_limit=near,
        over_soft_limit=over_soft,
        over_hard_limit=over_hard,
    )


async def upsert_policy_with_log(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    limits: dict,
    updated_by_id: UUID | None,
    change_note: str | None,
) -> OrgQuotaPolicy:
    """Upsert org quota policy and append a change-log entry."""
    policy = await _repo.upsert_policy(
        db_session,
        organization_id=organization_id,
        limits=limits,
        updated_by_id=updated_by_id,
        bump_version=True,
    )
    await _repo.create_change_log_entry(
        db_session,
        organization_id=organization_id,
        policy_id=policy.id,
        version_number=policy.version,
        policy_snapshot=_policy_snapshot(policy),
        change_note=change_note,
        changed_by_id=updated_by_id,
    )
    return policy


async def delete_policy_with_log(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    deleted_by_id: UUID | None,
    change_note: str | None,
) -> None:
    """Remove org quota policy (resets org to system defaults)."""
    policy = await _repo.get_policy(db_session, organization_id=organization_id)
    if policy is None:
        return
    await _repo.create_change_log_entry(
        db_session,
        organization_id=organization_id,
        policy_id=policy.id,
        version_number=policy.version + 1,
        policy_snapshot={**_policy_snapshot(policy), "_action": "reset"},
        change_note=change_note or "Reset to system defaults",
        changed_by_id=deleted_by_id,
    )
    await _repo.delete_policy(db_session, policy)


async def get_quota_dashboard(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> OrgQuotaDashboardResponse:
    """Build a dashboard of all quota types with current usage vs limits."""
    now = datetime.now(UTC)
    policy = await _repo.get_policy(db_session, organization_id=organization_id)
    effective = get_effective_limits(policy)
    all_usage = await _repo.list_usage(db_session, organization_id=organization_id)
    usage_map = {u.quota_type: u for u in all_usage}

    items: list[QuotaUsageItem] = []
    has_overages = False

    for qt in QuotaType:
        limit_config = effective.get(qt, SYSTEM_DEFAULT_LIMITS[qt])
        usage = usage_map.get(qt)

        if qt == QuotaType.seats:
            current = await _current_seat_count(db_session, organization_id=organization_id)
            item = _usage_item(
                qt,
                OrgQuotaUsage(
                    organization_id=organization_id,
                    quota_type=qt,
                    current_value=current,
                    period_start=now,
                    next_reset_at=None,
                ),
                limit_config,
            )
            items.append(item)
            if item.over_hard_limit or item.over_soft_limit:
                has_overages = True
            continue

        # Reset expired counters before building the dashboard view
        if _reset_window_expired(usage.next_reset_at if usage is not None else None, now):
            window = limit_config.get("reset_window", ResetWindow.per_day)
            next_reset = _compute_next_reset(window, now)
            await _repo.reset_usage(db_session, usage, next_reset_at=next_reset)

        item = _usage_item(qt, usage, limit_config)
        items.append(item)
        if item.over_hard_limit or item.over_soft_limit:
            has_overages = True

    return OrgQuotaDashboardResponse(
        organization_id=str(organization_id),
        policy_version=policy.version if policy is not None else 0,
        quota_usage=items,
        has_overages=has_overages,
        checked_at=now,
    )


async def check_quota(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    quota_type: QuotaType,
    requested_amount: int = 1,
    current_value_override: int | None = None,
) -> QuotaCheckResult:
    """Check whether the requested action would exceed quota limits."""
    now = datetime.now(UTC)
    policy = await _repo.get_policy(db_session, organization_id=organization_id)
    effective = get_effective_limits(policy)
    limit_config = effective.get(quota_type, SYSTEM_DEFAULT_LIMITS[quota_type])

    window = limit_config.get("reset_window", ResetWindow.per_day)
    next_reset_at: datetime | None = None

    if quota_type == QuotaType.seats:
        current = (
            current_value_override
            if current_value_override is not None
            else await _current_seat_count(db_session, organization_id=organization_id)
        )
    else:
        usage = await _repo.get_usage(
            db_session, organization_id=organization_id, quota_type=quota_type
        )

        # Reset if window has expired
        if _reset_window_expired(usage.next_reset_at if usage is not None else None, now):
            next_reset = _compute_next_reset(window, now)
            await _repo.reset_usage(db_session, usage, next_reset_at=next_reset)
            current = 0
            next_reset_at = next_reset
        else:
            current = usage.current_value if usage is not None else 0
            next_reset_at = (
                _normalize_utc(usage.next_reset_at)
                if usage is not None
                else _compute_next_reset(window, now)
            )

    projected = current + requested_amount
    soft = limit_config.get("soft_limit")
    hard = limit_config.get("hard_limit")

    over_hard = hard is not None and projected > hard
    over_soft = soft is not None and projected > soft

    ref_limit = hard if hard is not None else soft
    near = False
    if ref_limit is not None and ref_limit > 0:
        near = projected >= (ref_limit * NEAR_LIMIT_THRESHOLD)

    return QuotaCheckResult(
        quota_type=quota_type,
        allowed=not over_hard,
        near_limit=near,
        over_soft_limit=over_soft,
        over_hard_limit=over_hard,
        current_value=current,
        effective_hard_limit=hard,
        effective_soft_limit=soft,
        reset_window=window,
        next_reset_at=next_reset_at,
    )


async def increment_quota_usage(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    quota_type: QuotaType,
    amount: int = 1,
) -> None:
    """Increment the usage counter for the given quota type."""
    if quota_type == QuotaType.seats:
        return
    now = datetime.now(UTC)
    policy = await _repo.get_policy(db_session, organization_id=organization_id)
    effective = get_effective_limits(policy)
    limit_config = effective.get(quota_type, SYSTEM_DEFAULT_LIMITS[quota_type])
    window = limit_config.get("reset_window", ResetWindow.per_day)

    usage = await _repo.get_usage(
        db_session, organization_id=organization_id, quota_type=quota_type
    )

    if _reset_window_expired(usage.next_reset_at if usage is not None else None, now):
        # Window has expired — reset before incrementing
        next_reset = _compute_next_reset(window, now)
        await _repo.reset_usage(db_session, usage, next_reset_at=next_reset)

    next_reset_at = _compute_next_reset(window, now) if usage is None else None
    await _repo.increment_usage(
        db_session,
        organization_id=organization_id,
        quota_type=quota_type,
        amount=amount,
        next_reset_at=next_reset_at,
    )
