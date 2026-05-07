from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_organization_id", "organization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_auth_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    organization = relationship("Organization", back_populates="users")
    memberships = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="uploader")
    chat_sessions = relationship("ChatSession", back_populates="user")
    usage_events = relationship("UsageEvent", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")
