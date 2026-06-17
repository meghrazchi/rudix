from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class AgentToolPolicyOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-tool policy settings that override tool-spec defaults for an organization."""

    __tablename__ = "agent_tool_policy_overrides"
    __table_args__ = (
        UniqueConstraint("organization_id", "tool_name", name="uq_agent_tool_policy_org_tool"),
        CheckConstraint(
            "max_calls_per_run IS NULL OR max_calls_per_run >= 1",
            name="agent_tool_policy_max_calls_positive",
        ),
        CheckConstraint(
            "max_input_bytes IS NULL OR max_input_bytes >= 512",
            name="agent_tool_policy_input_bytes_min",
        ),
        CheckConstraint(
            "max_output_bytes IS NULL OR max_output_bytes >= 512",
            name="agent_tool_policy_output_bytes_min",
        ),
        CheckConstraint(
            "timeout_ms IS NULL OR timeout_ms >= 100",
            name="agent_tool_policy_timeout_min",
        ),
        CheckConstraint(
            "max_retry_attempts IS NULL OR max_retry_attempts >= 0",
            name="agent_tool_policy_retry_non_negative",
        ),
        Index("idx_agent_tool_policy_org", "organization_id"),
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
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Null means "use tool spec default"
    approval_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    required_roles_json: Mapped[list[str] | None] = mapped_column(
        "required_roles", JSON, nullable=True
    )
    max_calls_per_run: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_input_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timeout_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_retry_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)

    organization = relationship("Organization", back_populates="agent_tool_policy_overrides")
    updated_by_user = relationship("User", back_populates="agent_tool_policy_overrides_updated")
