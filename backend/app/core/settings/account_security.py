"""Account security settings (0.9.0): verification, recovery, MFA, SAML and SCIM.

S1 adds the module, the token retention window, and the startup validation hook; A1, A2, and
A3 add their fields under their markers and their checks in :func:`validate_account_security`.
Every default keeps the behaviour before 0.9.0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.core.config import Settings


class AccountSecuritySettings(BaseModel):
    # S1: unusable single-use tokens (expired or consumed) are deleted by the daily
    # ``auth.tokens.purge_expired`` task once they are older than this.
    auth_one_time_token_retention_hours: int = Field(default=24, ge=1, le=24 * 90)

    # v090-A1

    # v090-A2

    # v090-A3


def validate_account_security(settings: Settings) -> None:
    """Cross-field checks for account security; called from ``Settings.validate_consistency``."""
    # v090-A1
    # v090-A2
    # v090-A3
