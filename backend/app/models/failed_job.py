from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
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


class FailedJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "failed_jobs"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="failed_jobs_attempt_count_non_negative"),
        Index("idx_failed_jobs_org_created", "organization_id", "created_at"),
        Index("idx_failed_jobs_org_status", "organization_id", "status"),
        Index("idx_failed_jobs_task_id", "task_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(String(255), nullable=False)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="failed")
    queue_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization = relationship("Organization", back_populates="failed_jobs")
    audit_logs: Mapped[list[FailedJobAuditLog]] = relationship(
        "FailedJobAuditLog", back_populates="failed_job", cascade="all, delete-orphan"
    )


class FailedJobAuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "failed_job_audit_logs"
    __table_args__ = (
        Index("idx_failed_job_audit_logs_job_id", "failed_job_id"),
        Index("idx_failed_job_audit_logs_org_created", "organization_id", "created_at"),
    )

    failed_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("failed_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    performed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    failed_job = relationship("FailedJob", back_populates="audit_logs")
    performed_by = relationship("User")
