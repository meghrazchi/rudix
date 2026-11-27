"""Transactional outbox for Celery dispatches (R06-01 part 2, plan contract 4.2.5).

A row is written in the transaction of the change that needs the task (an upload, a
reindex or delete request), so the dispatch commits or rolls back with it. After commit
the request publishes it immediately; the ``outbox.relay`` beat task publishes whatever is
still ``pending`` (a broker outage, a crash between commit and publish). ``kwargs`` holds
task arguments only (ids, flags, chunking profile), never document text or secrets.
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
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

OUTBOX_STATUSES = ("pending", "published", "failed")


class OutboxMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_messages_dedupe_key"),
        CheckConstraint("status IN ('pending', 'published', 'failed')", name="status_allowed"),
        Index("idx_outbox_messages_org_created", "organization_id", "created_at"),
        # Built concurrently by migration 20261128_0003; mirrored here.
        Index("idx_outbox_pending", "status", "available_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_name: Mapped[str] = mapped_column(String(128), nullable=False)
    queue: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kwargs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Exception class name only, never the message (it may carry broker URLs).
    last_error: Mapped[str | None] = mapped_column(String(128), nullable=True)
