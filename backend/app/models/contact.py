from sqlalchemy import Boolean, CheckConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

_EMAIL_STATUSES = "'pending', 'sent', 'failed', 'skipped'"


class ContactSubmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contact_submissions"
    __table_args__ = (
        CheckConstraint(
            f"email_status IN ({_EMAIL_STATUSES})",
            name="contact_submissions_email_status_allowed",
        ),
        Index("idx_contact_submissions_created", "created_at"),
        Index("idx_contact_submissions_email_status", "email_status", "created_at"),
        Index("idx_contact_submissions_work_email", "work_email"),
    )

    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    work_email: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(120), nullable=False)
    role_title: Mapped[str] = mapped_column(String(120), nullable=False)
    use_case: Mapped[str] = mapped_column(String(160), nullable=False)
    team_size: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    consent_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    receiver_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    email_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
