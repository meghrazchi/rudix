from __future__ import annotations

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
from app.models.enums import ConnectorSyncJobStatus, ConnectorSyncRunStatus


class ConnectorSyncJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_sync_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'disabled')",
            name="connector_sync_jobs_status_allowed",
        ),
        Index("idx_connector_sync_jobs_org_status", "organization_id", "status"),
        Index("idx_connector_sync_jobs_connection_id", "connection_id"),
        Index("idx_connector_sync_jobs_source_id", "external_source_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_source_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConnectorSyncJobStatus.active.value,
    )
    schedule_json: Mapped[dict] = mapped_column("schedule", JSON, nullable=False, default=dict)
    cursor_json: Mapped[dict] = mapped_column("cursor", JSON, nullable=False, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization = relationship("Organization")
    connection = relationship("ConnectorConnection", back_populates="sync_jobs")
    external_source = relationship("ExternalSource", back_populates="sync_jobs")
    collection = relationship("Collection")
    sync_runs = relationship(
        "ConnectorSyncRun",
        back_populates="sync_job",
        cascade="all, delete-orphan",
    )


class ConnectorSyncRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="connector_sync_runs_status_allowed",
        ),
        CheckConstraint("items_seen >= 0", name="connector_sync_runs_items_seen_non_negative"),
        CheckConstraint("items_upserted >= 0", name="connector_sync_runs_upserted_non_negative"),
        CheckConstraint("items_deleted >= 0", name="connector_sync_runs_deleted_non_negative"),
        Index("idx_connector_sync_runs_org_status", "organization_id", "status"),
        Index("idx_connector_sync_runs_job_created", "sync_job_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sync_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_sync_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_source_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConnectorSyncRunStatus.queued.value,
    )
    sync_version: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor_before_json: Mapped[dict] = mapped_column(
        "cursor_before", JSON, nullable=False, default=dict
    )
    cursor_after_json: Mapped[dict] = mapped_column(
        "cursor_after", JSON, nullable=False, default=dict
    )
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details_json: Mapped[dict] = mapped_column(
        "error_details", JSON, nullable=False, default=dict
    )

    organization = relationship("Organization")
    sync_job = relationship("ConnectorSyncJob", back_populates="sync_runs")
    connection = relationship("ConnectorConnection")
    external_source = relationship("ExternalSource")
    source_documents = relationship("SourceDocument", back_populates="sync_run")
    tombstones = relationship("ExternalItemTombstone", back_populates="sync_run")
