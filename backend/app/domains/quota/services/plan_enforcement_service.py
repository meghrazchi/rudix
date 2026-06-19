from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.quota.schemas.quota_schemas import QuotaCheckResult, QuotaType
from app.domains.quota.services.quota_service import check_quota, increment_quota_usage


@dataclass(frozen=True, slots=True)
class PlanLimitContext:
    quota_type: QuotaType
    current_value: int
    requested_amount: int
    soft_limit: int | None
    hard_limit: int | None
    reset_window: str
    next_reset_at: datetime | None
    resource: str
    guidance: str
    retryable: bool


class PlanEnforcementService:
    async def ensure_within_limit(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        quota_type: QuotaType,
        requested_amount: int = 1,
        current_value_override: int | None = None,
        resource: str | None = None,
        guidance: str | None = None,
    ) -> QuotaCheckResult:
        result = await check_quota(
            db_session,
            organization_id=organization_id,
            quota_type=quota_type,
            requested_amount=requested_amount,
            current_value_override=current_value_override,
        )
        if not result.allowed:
            raise self._build_exception(
                organization_id=organization_id,
                quota_type=quota_type,
                requested_amount=requested_amount,
                check=result,
                resource=resource or quota_type.value.replace("_", " "),
                guidance=guidance,
            )
        return result

    async def record_usage(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        quota_type: QuotaType,
        amount: int = 1,
    ) -> None:
        await increment_quota_usage(
            db_session,
            organization_id=organization_id,
            quota_type=quota_type,
            amount=amount,
        )

    def _build_exception(
        self,
        *,
        organization_id: UUID,
        quota_type: QuotaType,
        requested_amount: int,
        check: QuotaCheckResult,
        resource: str,
        guidance: str | None,
    ) -> HTTPException:
        next_reset_at = check.next_reset_at
        retryable = next_reset_at is not None and check.reset_window != "none"
        default_guidance = (
            f"Reduce {resource} usage or upgrade your plan."
            if quota_type != QuotaType.seats
            else "Remove a member or upgrade your plan."
        )
        detail = {
            "code": "plan_limit_exceeded",
            "message": self._build_message(
                quota_type=quota_type,
                resource=resource,
                hard_limit=check.effective_hard_limit,
                current_value=check.current_value,
                requested_amount=requested_amount,
            ),
            "quota_type": quota_type.value,
            "resource": resource,
            "current_value": check.current_value,
            "requested_amount": requested_amount,
            "soft_limit": check.effective_soft_limit,
            "hard_limit": check.effective_hard_limit,
            "reset_window": check.reset_window,
            "next_reset_at": next_reset_at.isoformat() if next_reset_at else None,
            "retryable": retryable,
            "action": guidance or default_guidance,
            "organization_id": str(organization_id),
        }
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    @staticmethod
    def _build_message(
        *,
        quota_type: QuotaType,
        resource: str,
        hard_limit: int | None,
        current_value: int,
        requested_amount: int,
    ) -> str:
        if quota_type == QuotaType.seats:
            return (
                "Your plan seat limit has been reached."
                if hard_limit is not None
                else "Your current seat allocation is not available."
            )
        if hard_limit is None:
            return f"{resource.title()} usage is over the configured plan limit."
        projected = current_value + requested_amount
        return f"{resource.title()} usage would exceed the plan limit ({projected}/{hard_limit})."


plan_enforcement_service = PlanEnforcementService()
