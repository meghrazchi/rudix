from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

_TOKEN_BYTES = 32
_INVITE_TTL_DAYS = 7
_RESEND_COOLDOWN_SECONDS = 60


def generate_invite_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(days=_INVITE_TTL_DAYS)


def is_token_expired(expires_at: datetime) -> bool:
    now = datetime.now(UTC)
    if expires_at.tzinfo is None:
        return now.replace(tzinfo=None) > expires_at
    return now > expires_at


def can_resend(last_sent_at: datetime | None) -> bool:
    if last_sent_at is None:
        return True
    now = datetime.now(UTC)
    if last_sent_at.tzinfo is None:
        elapsed = (now.replace(tzinfo=None) - last_sent_at).total_seconds()
    else:
        elapsed = (now - last_sent_at).total_seconds()
    return elapsed >= _RESEND_COOLDOWN_SECONDS
