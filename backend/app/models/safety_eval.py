from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

_VIOLATION_TYPES = (
    "injection",
    "cross_tenant_leakage",
    "private_source_exposure",
    "unsupported_claims",
    "malicious_document",
    "unsafe_transform",
)
_RUN_STATUSES = ("queued", "running", "completed", "failed")
_SEVERITIES = ("critical", "high", "medium", "low")


class SafetyEvalCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "safety_eval_cases"
    __table_args__ = (
        CheckConstraint(
            f"violation_type IN ({', '.join(repr(v) for v in _VIOLATION_TYPES)})",
            name="safety_eval_cases_violation_type_allowed",
        ),
        CheckConstraint(
            f"severity IN ({', '.join(repr(s) for s in _SEVERITIES)})",
            name="safety_eval_cases_severity_allowed",
        ),
        Index("idx_safety_eval_cases_org_suite", "organization_id", "suite_name"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    suite_name: Mapped[str] = mapped_column(String(255), nullable=False)
    violation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    prompt_text: Mapped[str] = mapped_column(Text(), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="high")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    results: "list[SafetyEvalResult]" = relationship(
        "SafetyEvalResult",
        back_populates="safety_eval_case",
        cascade="all, delete-orphan",
    )


class SafetyEvalRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "safety_eval_runs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _RUN_STATUSES)})",
            name="safety_eval_runs_status_allowed",
        ),
        Index("idx_safety_eval_runs_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    suite_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    pass_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fail_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    results: "list[SafetyEvalResult]" = relationship(
        "SafetyEvalResult",
        back_populates="safety_eval_run",
        cascade="all, delete-orphan",
    )


class SafetyEvalResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "safety_eval_results"
    __table_args__ = (
        Index("idx_safety_eval_results_run_id", "safety_eval_run_id"),
        Index("idx_safety_eval_results_case_id", "safety_eval_case_id"),
    )

    safety_eval_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("safety_eval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    safety_eval_case_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("safety_eval_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    violation_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    violation_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    safety_eval_run: "SafetyEvalRun" = relationship("SafetyEvalRun", back_populates="results")
    safety_eval_case: "SafetyEvalCase" = relationship("SafetyEvalCase", back_populates="results")
