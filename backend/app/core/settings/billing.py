"""Billing and plan settings (0.9.0).

S1 adds the module with the provider selector (``none`` keeps the usage-derived billing of
earlier releases); B1 and B2 add their fields under their markers and their checks in
:func:`validate_billing`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.core.config import Settings


class BillingSettings(BaseModel):
    # ``none``: no payment provider (manual plans, usage-derived invoices); ``stripe``: B1.
    billing_provider: Literal["none", "stripe"] = "none"

    # v090-B1

    # v090-B2


def validate_billing(settings: Settings) -> None:
    """Cross-field checks for billing; called from ``Settings.validate_consistency``."""
    # v090-B1
    # v090-B2
