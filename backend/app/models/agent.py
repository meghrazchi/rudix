from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'planning', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled')",
            name="agent_runs_status_allowed",
        ),
        CheckConstraint("surface IN ('api', 'mcp')", name="agent_runs_surface_allowed"),
        CheckConstraint(
            "max_steps IS NULL OR max_steps >= 0", name="agent_runs_max_steps_non_negative"
        ),
        CheckConstraint(
            "max_parallel_tool_calls IS NULL OR max_parallel_tool_calls >= 0",
            name="agent_runs_max_parallel_tool_calls_non_negative",
        ),
        CheckConstraint(
            "total_cost_usd IS NULL OR total_cost_usd >= 0",
            name="agent_runs_total_cost_non_negative",
        ),
        Index("idx_agent_runs_org_status", "organization_id", "status"),
        Index("idx_agent_runs_org_user_created", "organization_id", "user_id", "created_at"),
        Index("idx_agent_runs_trace_request_id", "trace_request_id"),
        Index("idx_agent_runs_prompt_template_version", "prompt_template_version_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    surface: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    objective: Mapped[str | None] = mapped_column(Text(), nullable=True)
    prompt_template_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("prompt_template_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    max_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_parallel_tool_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_json: Mapped[dict] = mapped_column("budget", JSON, nullable=False, default=dict)
    costs_json: Mapped[dict] = mapped_column("costs", JSON, nullable=False, default=dict)
    outcome_json: Mapped[dict] = mapped_column("outcome", JSON, nullable=False, default=dict)
    observations_json: Mapped[dict] = mapped_column(
        "observations", JSON, nullable=False, default=dict
    )
    total_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trace_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_details_json: Mapped[dict] = mapped_column(
        "error_details", JSON, nullable=False, default=dict
    )

    organization = relationship("Organization", back_populates="agent_runs")
    user = relationship("User", back_populates="agent_runs")
    prompt_template_version = relationship("PromptTemplateVersion", back_populates="agent_runs")
    steps = relationship("AgentStep", back_populates="agent_run", cascade="all, delete-orphan")
    tool_calls = relationship(
        "AgentToolCall", back_populates="agent_run", cascade="all, delete-orphan"
    )
    approvals = relationship(
        "AgentApproval", back_populates="agent_run", cascade="all, delete-orphan"
    )


class AgentStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence"),
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'completed', 'failed', 'skipped', 'cancelled')",
            name="agent_steps_status_allowed",
        ),
        CheckConstraint("sequence >= 0", name="agent_steps_sequence_non_negative"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="agent_steps_duration_non_negative"
        ),
        Index("idx_agent_steps_org_status", "organization_id", "status"),
        Index("idx_agent_steps_run_sequence", "agent_run_id", "sequence"),
    )

    agent_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    inputs_json: Mapped[dict] = mapped_column("inputs", JSON, nullable=False, default=dict)
    outputs_json: Mapped[dict] = mapped_column("outputs", JSON, nullable=False, default=dict)
    metrics_json: Mapped[dict] = mapped_column("metrics", JSON, nullable=False, default=dict)
    observation_json: Mapped[dict] = mapped_column(
        "observation", JSON, nullable=False, default=dict
    )
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_details_json: Mapped[dict] = mapped_column(
        "error_details", JSON, nullable=False, default=dict
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    agent_run = relationship("AgentRun", back_populates="steps")
    organization = relationship("Organization", back_populates="agent_steps")
    user = relationship("User", back_populates="agent_steps")
    tool_calls = relationship("AgentToolCall", back_populates="agent_step")
    approvals = relationship("AgentApproval", back_populates="agent_step")


class AgentToolCall(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("call_id"),
        CheckConstraint("surface IN ('api', 'mcp')", name="agent_tool_calls_surface_allowed"),
        CheckConstraint(
            "effect_policy IN ('read_only', 'side_effect')",
            name="agent_tool_calls_effect_policy_allowed",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="agent_tool_calls_status_allowed",
        ),
        CheckConstraint("attempt_number >= 1", name="agent_tool_calls_attempt_number_positive"),
        CheckConstraint(
            "input_size_bytes IS NULL OR input_size_bytes >= 0",
            name="agent_tool_calls_input_size_non_negative",
        ),
        CheckConstraint(
            "output_size_bytes IS NULL OR output_size_bytes >= 0",
            name="agent_tool_calls_output_size_non_negative",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="agent_tool_calls_latency_non_negative"
        ),
        Index("idx_agent_tool_calls_org_status", "organization_id", "status"),
        Index("idx_agent_tool_calls_run_status", "agent_run_id", "status"),
        Index("idx_agent_tool_calls_tool_name", "tool_name"),
    )

    agent_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_step_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    surface: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    effect_policy: Mapped[str] = mapped_column(String(16), nullable=False, default="read_only")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    arguments_json: Mapped[dict] = mapped_column("arguments", JSON, nullable=False, default=dict)
    output_json: Mapped[dict] = mapped_column("output", JSON, nullable=False, default=dict)
    error_json: Mapped[dict] = mapped_column("error", JSON, nullable=False, default=dict)
    input_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent_run = relationship("AgentRun", back_populates="tool_calls")
    agent_step = relationship("AgentStep", back_populates="tool_calls")
    organization = relationship("Organization", back_populates="agent_tool_calls")
    user = relationship("User", back_populates="agent_tool_calls")
    approvals = relationship("AgentApproval", back_populates="tool_call")


class AgentApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name="agent_approvals_status_allowed",
        ),
        Index("idx_agent_approvals_org_status", "organization_id", "status"),
        Index("idx_agent_approvals_run_status", "agent_run_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_step_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_call_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_tool_calls.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    request_summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    request_payload_json: Mapped[dict] = mapped_column(
        "request_payload", JSON, nullable=False, default=dict
    )
    decision_payload_json: Mapped[dict] = mapped_column(
        "decision_payload", JSON, nullable=False, default=dict
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization", back_populates="agent_approvals")
    agent_run = relationship("AgentRun", back_populates="approvals")
    agent_step = relationship("AgentStep", back_populates="approvals")
    tool_call = relationship("AgentToolCall", back_populates="approvals")
    requested_by_user = relationship(
        "User", foreign_keys=[requested_by_user_id], back_populates="agent_approvals_requested"
    )
    decided_by_user = relationship(
        "User", foreign_keys=[decided_by_user_id], back_populates="agent_approvals_decided"
    )
