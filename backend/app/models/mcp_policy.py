from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class OrgMCPPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Org-scoped MCP server policy: toggles, capability overrides, and rate limits."""

    __tablename__ = "org_mcp_policies"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_org_mcp_policies_org"),
        CheckConstraint(
            "rate_limit_requests >= 1", name="mcp_policy_rate_limit_requests_min"
        ),
        CheckConstraint(
            "rate_limit_requests <= 10000", name="mcp_policy_rate_limit_requests_max"
        ),
        CheckConstraint(
            "rate_limit_window_seconds >= 1", name="mcp_policy_rate_limit_window_min"
        ),
        CheckConstraint(
            "rate_limit_window_seconds <= 3600", name="mcp_policy_rate_limit_window_max"
        ),
        Index("idx_org_mcp_policies_org", "organization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # JSON arrays; None means "use env/server defaults"
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    capabilities_owner: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    capabilities_admin: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    capabilities_member: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    capabilities_viewer: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    rate_limit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rate_limit_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    rate_limit_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    organization = relationship("Organization", back_populates="mcp_policy")
    updated_by_user = relationship("User", back_populates="mcp_policy_updates")
