from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
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


class WorkspacePortabilityJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_portability_jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('export', 'import')",
            name="workspace_portability_jobs_type_allowed",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'validated', 'completed', 'failed', "
            "'validation_failed', 'expired')",
            name="workspace_portability_jobs_status_allowed",
        ),
        CheckConstraint(
            "artifact_size_bytes IS NULL OR artifact_size_bytes >= 0",
            name="workspace_portability_jobs_artifact_size_non_negative",
        ),
        CheckConstraint(
            "records_processed >= 0",
            name="workspace_portability_jobs_records_processed_non_negative",
        ),
        CheckConstraint(
            "records_failed >= 0",
            name="workspace_portability_jobs_records_failed_non_negative",
        ),
        Index("idx_workspace_portability_jobs_org_created", "organization_id", "created_at"),
        Index("idx_workspace_portability_jobs_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    requested_sections_json: Mapped[list[str]] = mapped_column(
        "requested_sections",
        JSON,
        nullable=False,
        default=list,
    )
    parameters_json: Mapped[dict] = mapped_column("parameters", JSON, nullable=False, default=dict)
    artifact_json: Mapped[dict | None] = mapped_column("artifact", JSON, nullable=True)
    artifact_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    artifact_mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    artifact_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_errors_json: Mapped[list[dict]] = mapped_column(
        "validation_errors",
        JSON,
        nullable=False,
        default=list,
    )
    warnings_json: Mapped[list[dict]] = mapped_column(
        "warnings", JSON, nullable=False, default=list
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization", back_populates="portability_jobs")
    created_by = relationship("User")
