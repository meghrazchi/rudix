from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class OrganizationGovernancePolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_governance_policies"
    __table_args__ = (
        CheckConstraint(
            "max_steps IS NULL OR max_steps >= 1",
            name="org_governance_max_steps_positive",
        ),
        CheckConstraint(
            "max_tool_calls_per_run IS NULL OR max_tool_calls_per_run >= 1",
            name="org_governance_max_tool_calls_positive",
        ),
        CheckConstraint(
            "max_tool_timeout_ms IS NULL OR max_tool_timeout_ms >= 100",
            name="org_governance_timeout_min",
        ),
        CheckConstraint(
            "max_tool_input_bytes IS NULL OR max_tool_input_bytes >= 512",
            name="org_governance_input_bytes_min",
        ),
        CheckConstraint(
            "max_tool_output_bytes IS NULL OR max_tool_output_bytes >= 512",
            name="org_governance_output_bytes_min",
        ),
        CheckConstraint(
            "max_tool_retry_attempts IS NULL OR max_tool_retry_attempts >= 0",
            name="org_governance_retry_attempts_non_negative",
        ),
        CheckConstraint(
            "max_total_tokens IS NULL OR max_total_tokens >= 1",
            name="org_governance_total_tokens_positive",
        ),
        CheckConstraint(
            "max_total_cost_usd IS NULL OR max_total_cost_usd >= 0",
            name="org_governance_total_cost_non_negative",
        ),
        Index(
            "idx_org_governance_org_id",
            "organization_id",
            unique=True,
        ),
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
    agentic_mode_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    mcp_exposure_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    allow_side_effect_tools: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    allowed_tool_names_json: Mapped[list[str]] = mapped_column(
        "allowed_tool_names",
        JSON,
        nullable=False,
        default=list,
    )
    max_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tool_calls_per_run: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tool_timeout_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tool_input_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tool_output_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tool_retry_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_total_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )
    external_mcp_servers_json: Mapped[list[dict]] = mapped_column(
        "external_mcp_servers",
        JSON,
        nullable=False,
        default=list,
    )

    organization = relationship("Organization", back_populates="governance_policy")
    updated_by_user = relationship("User", back_populates="governance_policies_updated")
