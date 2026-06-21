"""Org-level freshness threshold configuration (F311).

Each organisation can override when documents are considered stale or
unreviewed for the purpose of freshness warnings in answers.  Rows are
created on first PATCH — no row means all defaults apply.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class OrgFreshnessPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-org admin-configurable freshness thresholds.

    All fields are nullable — None means "use system default" so the
    service falls back gracefully without any row present.
    """

    __tablename__ = "org_freshness_policies"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_org_freshness_policy_org"),
        CheckConstraint(
            "warn_stale_after_days IS NULL OR warn_stale_after_days >= 1",
            name="ck_ofp_stale_days_min",
        ),
        CheckConstraint(
            "warn_stale_after_days IS NULL OR warn_stale_after_days <= 3650",
            name="ck_ofp_stale_days_max",
        ),
        CheckConstraint(
            "warn_unreviewed_after_days IS NULL OR warn_unreviewed_after_days >= 1",
            name="ck_ofp_unreviewed_days_min",
        ),
        CheckConstraint(
            "warn_unreviewed_after_days IS NULL OR warn_unreviewed_after_days <= 3650",
            name="ck_ofp_unreviewed_days_max",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Days since last review before a 'current' doc is promoted to 'stale'
    # warning.  Overrides the per-document stale_after_days when set at org
    # level.  None → use per-document value or system default (90 days).
    warn_stale_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Days since last review before an 'unreviewed' warning fires.
    # None → system default (180 days).
    warn_unreviewed_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Whether deprecated/superseded/archived sources are excluded from
    # retrieval by default.  When False, they are included with a warning.
    auto_exclude_deprecated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Whether expired sources are excluded from retrieval by default.
    auto_exclude_expired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Optional label for this policy config (admin notes only).
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
