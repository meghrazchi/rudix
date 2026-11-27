"""Staged ingestion bookkeeping: one row per stage of a run, plus stage artifacts (R06-01).

``run_id`` is the namespace of one processing run (the claim's Celery task id), so a
redelivery or retry of the same task finds the stages it already finished. Metrics hold
counts and configuration only, never document text. Artifacts hold the intermediate
output a later stage needs (pages, cleaned pages, embedding batch summaries) as
zlib-compressed UTF-8 JSON; they are deleted when the run finishes and with the document.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

STAGE_STATUSES = ("pending", "running", "completed", "failed")


class DocumentProcessingStage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_processing_stages"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "run_id", "stage", name="uq_document_processing_stages_run_stage"
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="status_allowed",
        ),
        Index("idx_document_processing_stages_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    owner_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    artifact_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DocumentStageArtifact(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_stage_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "run_id",
            "stage",
            "part",
            name="uq_document_stage_artifacts_run_stage_part",
        ),
        Index("idx_document_stage_artifacts_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    part: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
