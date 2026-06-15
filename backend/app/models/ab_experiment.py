from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AbExperimentStatus, AbVariantApprovalStatus

_EXPERIMENT_STATUSES = ("draft", "running", "completed", "failed")
_VARIANT_APPROVAL_STATUSES = ("pending", "approved", "rejected")
_VARIANT_RUN_STATUSES = ("queued", "running", "completed", "failed")


class AbExperiment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An A/B experiment comparing prompt/retrieval profile variants on a fixed dataset."""

    __tablename__ = "ab_experiments"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _EXPERIMENT_STATUSES)})",
            name="ab_experiments_status_allowed",
        ),
        Index("idx_ab_experiments_organization_id", "organization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    evaluation_set_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AbExperimentStatus.draft.value,
    )
    # Metrics tracked in every comparison report (faithfulness, citation_accuracy, etc.)
    metrics_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization", back_populates="ab_experiments")
    evaluation_set = relationship("EvaluationSet")
    created_by = relationship("User", foreign_keys=[created_by_id])
    variants = relationship(
        "AbExperimentVariant",
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="AbExperimentVariant.created_at",
    )
    runs = relationship(
        "AbExperimentRun",
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="AbExperimentRun.created_at.desc()",
    )


class AbExperimentVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single variant in an A/B experiment: a specific RAG profile + optional prompt version."""

    __tablename__ = "ab_experiment_variants"
    __table_args__ = (
        CheckConstraint(
            f"approval_status IN ({', '.join(repr(s) for s in _VARIANT_APPROVAL_STATUSES)})",
            name="ab_experiment_variants_approval_allowed",
        ),
        Index("idx_ab_experiment_variants_experiment_id", "experiment_id"),
    )

    experiment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ab_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # RAG profile version snapshot used for this variant
    rag_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    rag_profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Prompt template version pinned for this variant (None = use org default)
    prompt_template_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("prompt_template_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Optional model profile override (e.g. "local", "cloud_baseline")
    model_profile_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Snapshot of the full config at the time the variant was defined
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approval_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AbVariantApprovalStatus.pending.value,
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approval_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    experiment = relationship("AbExperiment", back_populates="variants")
    rag_profile = relationship("RagProfile")
    prompt_template_version = relationship("PromptTemplateVersion")
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    variant_runs = relationship(
        "AbExperimentVariantRun",
        back_populates="variant",
        cascade="all, delete-orphan",
    )


class AbExperimentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single execution of an A/B experiment — all variants evaluated on the same dataset."""

    __tablename__ = "ab_experiment_runs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _EXPERIMENT_STATUSES)})",
            name="ab_experiment_runs_status_allowed",
        ),
        Index("idx_ab_experiment_runs_experiment_id", "experiment_id", "created_at"),
    )

    experiment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ab_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AbExperimentStatus.running.value,
    )
    # Cached comparison report built after all variant runs complete
    comparison_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    triggered_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    experiment = relationship("AbExperiment", back_populates="runs")
    triggered_by = relationship("User", foreign_keys=[triggered_by_id])
    variant_runs = relationship(
        "AbExperimentVariantRun",
        back_populates="experiment_run",
        cascade="all, delete-orphan",
    )


class AbExperimentVariantRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-variant evaluation run within an A/B experiment run."""

    __tablename__ = "ab_experiment_variant_runs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _VARIANT_RUN_STATUSES)})",
            name="ab_experiment_variant_runs_status_allowed",
        ),
        UniqueConstraint(
            "experiment_run_id",
            "variant_id",
            name="uq_ab_variant_runs_run_variant",
        ),
        Index("idx_ab_variant_runs_experiment_run_id", "experiment_run_id"),
        Index("idx_ab_variant_runs_evaluation_run_id", "evaluation_run_id"),
    )

    experiment_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ab_experiment_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ab_experiment_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Linked evaluation run (one per variant) that stores individual results
    evaluation_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
    )
    # Cached per-variant metric summary extracted from the evaluation run
    metrics_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_detail: Mapped[str | None] = mapped_column(Text(), nullable=True)

    experiment_run = relationship("AbExperimentRun", back_populates="variant_runs")
    variant = relationship("AbExperimentVariant", back_populates="variant_runs")
    evaluation_run = relationship("EvaluationRun")
