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


class PipelineRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(
            "pipeline_type IN ('document.process', 'document.reindex', 'document.delete', 'chat.query', 'evaluation.run')",
            name="pipeline_runs_pipeline_type_allowed",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="pipeline_runs_status_allowed",
        ),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="pipeline_runs_duration_non_negative"),
        Index("idx_pipeline_runs_org_created", "organization_id", "created_at"),
        Index("idx_pipeline_runs_document_id", "document_id"),
        Index("idx_pipeline_runs_chat_message_id", "chat_message_id"),
        Index("idx_pipeline_runs_evaluation_run_id", "evaluation_run_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    pipeline_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inputs_json: Mapped[dict] = mapped_column("inputs", JSON, nullable=False, default=dict)
    outputs_json: Mapped[dict] = mapped_column("outputs", JSON, nullable=False, default=dict)
    config_json: Mapped[dict] = mapped_column("config", JSON, nullable=False, default=dict)
    logs_json: Mapped[list] = mapped_column("logs", JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_details_json: Mapped[dict] = mapped_column("error_details", JSON, nullable=False, default=dict)
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    chat_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    evaluation_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization", back_populates="pipeline_runs")
    document = relationship("Document", back_populates="pipeline_runs")
    chat_message = relationship("ChatMessage", back_populates="pipeline_runs")
    evaluation_run = relationship("EvaluationRun", back_populates="pipeline_runs")
    events = relationship("PipelineEvent", back_populates="pipeline_run", cascade="all, delete-orphan")


class PipelineEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pipeline_events"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "sequence"),
        CheckConstraint(
            "status IN ('started', 'completed', 'failed', 'skipped')",
            name="pipeline_events_status_allowed",
        ),
        CheckConstraint("sequence >= 0", name="pipeline_events_sequence_non_negative"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="pipeline_events_duration_non_negative"),
        Index("idx_pipeline_events_run_sequence", "pipeline_run_id", "sequence"),
        Index("idx_pipeline_events_node_status", "node_name", "status"),
    )

    pipeline_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inputs_json: Mapped[dict] = mapped_column("inputs", JSON, nullable=False, default=dict)
    outputs_json: Mapped[dict] = mapped_column("outputs", JSON, nullable=False, default=dict)
    config_json: Mapped[dict] = mapped_column("config", JSON, nullable=False, default=dict)
    logs_json: Mapped[list] = mapped_column("logs", JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_details_json: Mapped[dict] = mapped_column("error_details", JSON, nullable=False, default=dict)

    pipeline_run = relationship("PipelineRun", back_populates="events")
