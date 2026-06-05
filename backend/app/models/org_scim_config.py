from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class OrgSCIMConfig(Base):
    __tablename__ = "org_scim_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_org_scim_configs_org_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # SHA-256 hex digest of the bearer token (never stored in plaintext)
    token_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    # Last 4 characters of the raw token, shown in the UI so admins can identify it
    token_hint: Mapped[str] = mapped_column(String(8), nullable=False)

    last_sync_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    provisioned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deprovisioned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(  # noqa: F821
        "Organization",
        back_populates="scim_config",
        foreign_keys=[organization_id],
    )
