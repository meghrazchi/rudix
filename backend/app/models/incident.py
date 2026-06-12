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
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class Incident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('investigating','identified','monitoring','resolved')",
            name="incidents_status_check",
        ),
        CheckConstraint(
            "severity IN ('critical','high','medium','low')",
            name="incidents_severity_check",
        ),
        Index("idx_incidents_org_status", "organization_id", "status"),
        Index("idx_incidents_org_started_at", "organization_id", "started_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="investigating"
    )
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    affected_services: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization", back_populates="incidents")
    notes: Mapped[list[IncidentNote]] = relationship(
        "IncidentNote", back_populates="incident", cascade="all, delete-orphan"
    )


class IncidentNote(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "incident_notes"
    __table_args__ = (
        Index("idx_incident_notes_incident_id", "incident_id"),
        Index("idx_incident_notes_org_created", "organization_id", "created_at"),
    )

    incident_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    status_change: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    incident = relationship("Incident", back_populates="notes")
