from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class BotInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bot_installations"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('slack', 'teams')",
            name="bot_installations_provider_allowed",
        ),
        CheckConstraint(
            "status IN ('enabled', 'disabled')",
            name="bot_installations_status_allowed",
        ),
        UniqueConstraint(
            "provider",
            "external_workspace_id",
            "external_tenant_id",
            "external_team_id",
            name="uq_bot_installations_external_scope",
        ),
        Index("idx_bot_installations_org_provider", "organization_id", "provider"),
        Index("idx_bot_installations_external", "provider", "external_workspace_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    external_workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    external_team_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")
    default_source_scope_json: Mapped[dict] = mapped_column(
        "default_source_scope",
        JSON,
        nullable=False,
        default=dict,
    )
    config_json: Mapped[dict] = mapped_column("config", JSON, nullable=False, default=dict)
    encrypted_bot_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_token_key_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bot_token_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bot_token_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bot_token_scopes_json: Mapped[list] = mapped_column(
        "bot_token_scopes",
        JSON,
        nullable=False,
        default=list,
    )
    bot_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    installed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    user_mappings = relationship(
        "BotUserMapping",
        back_populates="installation",
        cascade="all, delete-orphan",
    )


class BotUserMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bot_user_mappings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="bot_user_mappings_status_allowed",
        ),
        UniqueConstraint(
            "installation_id",
            "external_user_id",
            name="uq_bot_user_mappings_external_user",
        ),
        Index("idx_bot_user_mappings_org_user", "organization_id", "rudix_user_id"),
        Index("idx_bot_user_mappings_installation", "installation_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    installation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bot_installations.id", ondelete="CASCADE"),
        nullable=False,
    )
    rudix_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    installation = relationship("BotInstallation", back_populates="user_mappings")
