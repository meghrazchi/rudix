from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import QualityGateVerdict

_GATE_VERDICTS = ("passed", "failed", "overridden")
_RUN_STATUSES = ("pending", "passed", "failed", "overridden", "error")


class QualityGate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quality_gates"
    __table_args__ = (Index("idx_quality_gates_organization_id", "organization_id"),)

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # JSON thresholds: retrieval_hit_rate_min, citation_accuracy_score_min, etc.
    thresholds: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Baseline run IDs stored for regression tracking
    baseline_evaluation_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    baseline_safety_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("safety_eval_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization", back_populates="quality_gates")
    created_by = relationship("User", foreign_keys=[created_by_id])
    runs = relationship(
        "QualityGateRun", back_populates="quality_gate", cascade="all, delete-orphan"
    )


class QualityGateRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quality_gate_runs"
    __table_args__ = (
        CheckConstraint(
            f"verdict IN ({', '.join(repr(v) for v in _GATE_VERDICTS)})",
            name="quality_gate_runs_verdict_allowed",
        ),
        Index("idx_quality_gate_runs_gate", "quality_gate_id", "created_at"),
        Index("idx_quality_gate_runs_eval_run", "evaluation_run_id"),
    )

    quality_gate_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("quality_gates.id", ondelete="CASCADE"),
        nullable=False,
    )
    evaluation_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    safety_eval_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("safety_eval_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    verdict: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=QualityGateVerdict.failed.value,
    )
    # Full structured report stored as JSON for CI artifact retrieval
    report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    triggered_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    overridden_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    override_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    overridden_at: Mapped[datetime | None] = mapped_column(nullable=True)

    quality_gate = relationship("QualityGate", back_populates="runs")
    triggered_by = relationship("User", foreign_keys=[triggered_by_id])
    overridden_by = relationship("User", foreign_keys=[overridden_by_id])
