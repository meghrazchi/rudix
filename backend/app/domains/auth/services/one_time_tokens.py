"""Single-use account tokens: issue, consume once, count failures, revoke, purge (0.9.0, S1).

Contract (plan 5.2.2): a raw token is 32 random bytes, URL-safe base64, returned once by
:func:`issue` and never stored or logged; only its SHA-256 hex digest is persisted.
:func:`consume` is one conditional ``UPDATE ... RETURNING`` (see the repository), so a race
consumes a token at most once. Callers own the transaction: nothing here commits.

``raw_token`` lets a caller register an identifier generated elsewhere (a SAML request or
assertion id); registering the same value twice raises :class:`DuplicateToken`, which makes
replay detection atomic through the unique ``token_hash`` constraint.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.metrics_account import record_one_time_token
from app.domains.auth.repositories.one_time_tokens import OneTimeTokenRepository
from app.domains.auth.schemas.one_time_tokens import OneTimeTokenPurpose
from app.models.auth_one_time_token import AuthOneTimeToken

RAW_TOKEN_BYTES = 32
MAX_TTL_SECONDS = 30 * 24 * 3600

_logger = get_logger("events.auth.tokens")
_repository = OneTimeTokenRepository()

# Indirection so tests can pin the clock.
clock: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


class DuplicateToken(Exception):
    """The token (its hash) is already registered; for SAML ids this means a replay."""

    def __init__(self, purpose: str) -> None:
        super().__init__(f"one-time token already registered for purpose {purpose}")
        self.purpose = purpose


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest stored in ``auth_one_time_tokens.token_hash``."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _purpose(value: OneTimeTokenPurpose | str) -> str:
    return OneTimeTokenPurpose(value).value


def _id(value: UUID | None) -> str | None:
    return None if value is None else str(value)


async def issue(
    session: AsyncSession,
    *,
    purpose: OneTimeTokenPurpose | str,
    user_id: UUID | None,
    organization_id: UUID | None,
    ttl_seconds: int,
    session_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    max_attempts: int = 1,
    created_ip: str | None = None,
    raw_token: str | None = None,
) -> str:
    """Store a new token and return the raw value (the only time it exists in clear)."""
    purpose_value = _purpose(purpose)
    if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if raw_token is not None and not raw_token:
        raise ValueError("raw_token must not be empty")
    raw = raw_token or secrets.token_urlsafe(RAW_TOKEN_BYTES)
    now = clock()
    inserted = await _repository.insert(
        session,
        {
            "purpose": purpose_value,
            "token_hash": hash_token(raw),
            "user_id": user_id,
            "organization_id": organization_id,
            "session_id": session_id,
            "expires_at": now + timedelta(seconds=ttl_seconds),
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "created_ip": created_ip,
            "metadata_json": dict(metadata or {}),
            "created_at": now,
        },
    )
    if not inserted:
        record_one_time_token(purpose_value, "duplicate")
        _logger.warning(
            "auth.token.duplicate",
            purpose=purpose_value,
            user_id=_id(user_id),
            organization_id=_id(organization_id),
        )
        raise DuplicateToken(purpose_value)
    record_one_time_token(purpose_value, "issued")
    _logger.info(
        "auth.token.issued",
        purpose=purpose_value,
        user_id=_id(user_id),
        organization_id=_id(organization_id),
        ttl_seconds=ttl_seconds,
    )
    return raw


async def consume(
    session: AsyncSession,
    *,
    purpose: OneTimeTokenPurpose | str,
    raw_token: str,
    user_id: UUID | None = None,
    session_id: UUID | None = None,
) -> AuthOneTimeToken | None:
    """Mark a usable token consumed and return it; ``None`` for every other case.

    Unknown, expired, already consumed, wrong purpose, exhausted, and (when given) wrong user
    or session all return ``None`` alike, so callers answer one error for all of them.
    """
    purpose_value = _purpose(purpose)
    if not raw_token:
        record_one_time_token(purpose_value, "rejected")
        return None
    token = await _repository.consume(
        session,
        token_hash=hash_token(raw_token),
        purpose=purpose_value,
        now=clock(),
        user_id=user_id,
        session_id=session_id,
    )
    if token is None:
        record_one_time_token(purpose_value, "rejected")
        _logger.info("auth.token.rejected", purpose=purpose_value)
        return None
    record_one_time_token(purpose_value, "consumed")
    _logger.info(
        "auth.token.consumed",
        purpose=purpose_value,
        user_id=_id(token.user_id),
        organization_id=_id(token.organization_id),
    )
    return token


async def record_failed_attempt(
    session: AsyncSession,
    *,
    purpose: OneTimeTokenPurpose | str,
    raw_token: str,
) -> int | None:
    """Count a failed use (wrong MFA code); the token is invalid once it reaches the limit.

    Returns the new attempt count, or ``None`` when no usable token matched.
    """
    purpose_value = _purpose(purpose)
    if not raw_token:
        return None
    count = await _repository.record_failed_attempt(
        session, token_hash=hash_token(raw_token), purpose=purpose_value, now=clock()
    )
    if count is not None:
        record_one_time_token(purpose_value, "failed_attempt")
        _logger.info("auth.token.failed_attempt", purpose=purpose_value, attempt_count=count)
    return count


async def revoke_for_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    purpose: OneTimeTokenPurpose | str,
) -> int:
    """Mark every unconsumed token of ``purpose`` for the user consumed; return the count."""
    purpose_value = _purpose(purpose)
    revoked = await _repository.revoke_for_user(
        session, user_id=user_id, purpose=purpose_value, now=clock()
    )
    record_one_time_token(purpose_value, "revoked", revoked)
    _logger.info("auth.token.revoked", purpose=purpose_value, user_id=str(user_id), count=revoked)
    return revoked


async def purge_expired(session: AsyncSession, older_than: datetime) -> int:
    """Delete tokens that expired, or were consumed, before ``older_than``."""
    if older_than.tzinfo is None:
        raise ValueError("older_than must be timezone-aware")
    purged = await _repository.purge(session, cutoff=older_than)
    record_one_time_token("all", "purged", purged)
    _logger.info("auth.token.purged", count=purged)
    return purged
