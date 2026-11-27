"""Transport-neutral rate limit counter shared by HTTP and WebSocket paths."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core.config import RateLimitRedisFailureMode, settings
from app.core.logging import get_logger
from app.core.metrics import record_rate_limit
from app.rate_limit import sliding_window

logger = get_logger("auth.rate_limit")


class RateLimitScope(StrEnum):
    upload = "upload"
    chat = "chat"
    evaluation = "evaluation"
    delete = "delete"
    admin = "admin"
    connector = "connector"


class RateLimitDecision(StrEnum):
    allowed = "allowed"
    limited = "limited"
    unavailable = "unavailable"


class RateLimitedBy(StrEnum):
    user = "user"
    organization = "organization"


@dataclass(frozen=True)
class RateLimitOutcome:
    decision: RateLimitDecision
    limit: int
    remaining: int
    retry_after_seconds: int
    limited_by: RateLimitedBy | None = None


def _scope_limit(scope: RateLimitScope) -> int:
    mapping = {
        RateLimitScope.upload: settings.rate_limit_upload_requests,
        RateLimitScope.chat: settings.rate_limit_chat_requests,
        RateLimitScope.evaluation: settings.rate_limit_evaluation_requests,
        RateLimitScope.delete: settings.rate_limit_delete_requests,
        RateLimitScope.admin: settings.rate_limit_admin_requests,
        RateLimitScope.connector: settings.rate_limit_connector_requests,
    }
    return mapping[scope]


def _build_key(*, scope: RateLimitScope, endpoint: str, user_id: str, organization_id: str) -> str:
    """User counter base key; ``{org:<id>}`` is the cluster hash tag shared with the org key."""
    sanitized_endpoint = endpoint.replace(" ", "_")
    return (
        f"rate_limit:v2:{{org:{organization_id}}}:{scope.value}:{sanitized_endpoint}:user:{user_id}"
    )


def _build_org_key(*, scope: RateLimitScope, endpoint: str, organization_id: str) -> str:
    sanitized_endpoint = endpoint.replace(" ", "_")
    return f"rate_limit:v2:{{org:{organization_id}}}:{scope.value}:{sanitized_endpoint}:org"


def _org_limit(limit: int, organization_id: str | None) -> int:
    if not settings.rate_limit_org_enabled or organization_id is None:
        return 0
    return limit * settings.rate_limit_org_limit_multiplier


def _rate_limit_disabled() -> bool:
    return not settings.is_rate_limit_active


def _record(scope: RateLimitScope, decision: RateLimitDecision, failure_mode: str) -> None:
    record_rate_limit(scope.value, decision.value, failure_mode)


async def consume_rate_limit(
    *, scope: RateLimitScope, endpoint: str, principal: AuthenticatedPrincipal
) -> RateLimitOutcome:
    """Count one request. Returns ``unavailable`` instead of raising in closed mode."""
    limit = _scope_limit(scope)
    if _rate_limit_disabled():
        return RateLimitOutcome(RateLimitDecision.allowed, limit, limit, 0)

    window_seconds = settings.rate_limit_window_seconds
    organization_id = principal.organization_id or "none"
    key = _build_key(
        scope=scope,
        endpoint=endpoint,
        user_id=principal.user_id,
        organization_id=organization_id,
    )
    failure_mode = settings.rate_limit_redis_failure_mode
    closed = failure_mode == RateLimitRedisFailureMode.closed

    redis = redis_module.redis_client
    if redis is None:
        logger.warning(
            "rate_limit.redis_unavailable",
            scope=scope.value,
            endpoint=endpoint,
            user_id=principal.user_id,
            organization_id=organization_id,
            failure_mode=failure_mode.value,
        )
        decision = RateLimitDecision.unavailable if closed else RateLimitDecision.allowed
        _record(scope, decision, failure_mode.value)
        return RateLimitOutcome(decision, limit, limit, 0)

    try:
        result = await sliding_window.check(
            redis,
            user_key=key,
            user_limit=limit,
            window_seconds=window_seconds,
            org_key=_build_org_key(scope=scope, endpoint=endpoint, organization_id=organization_id),
            org_limit=_org_limit(limit, principal.organization_id),
        )
        remaining = result.remaining
        if not result.allowed:
            limited_by = (
                RateLimitedBy.organization
                if result.scope == sliding_window.SCOPE_ORG
                else RateLimitedBy.user
            )
            logger.info(
                "rate_limit.exceeded",
                scope=scope.value,
                endpoint=endpoint,
                user_id=principal.user_id,
                organization_id=organization_id,
                limit=limit,
                limited_by=limited_by.value,
                retry_after_seconds=result.retry_after_seconds,
            )
            _record(scope, RateLimitDecision.limited, "none")
            if limited_by == RateLimitedBy.organization:
                sliding_window.record_org_limited(scope.value)
            return RateLimitOutcome(
                RateLimitDecision.limited,
                limit,
                remaining,
                result.retry_after_seconds,
                limited_by,
            )
    except Exception as exc:
        if closed:
            logger.error(
                "rate_limit.redis_error",
                scope=scope.value,
                endpoint=endpoint,
                user_id=principal.user_id,
                organization_id=organization_id,
                error=exc.__class__.__name__,
            )
            _record(scope, RateLimitDecision.unavailable, failure_mode.value)
            return RateLimitOutcome(RateLimitDecision.unavailable, limit, limit, 0)
        logger.warning(
            "rate_limit.redis_error.degraded",
            scope=scope.value,
            endpoint=endpoint,
            user_id=principal.user_id,
            organization_id=organization_id,
            error=exc.__class__.__name__,
        )
        _record(scope, RateLimitDecision.allowed, failure_mode.value)
        return RateLimitOutcome(RateLimitDecision.allowed, limit, limit, 0)

    _record(scope, RateLimitDecision.allowed, "none")
    return RateLimitOutcome(RateLimitDecision.allowed, limit, remaining, 0)
