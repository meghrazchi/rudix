from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class OrganizationChunkingProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_chunking_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "slug",
            name="uq_org_chunking_profile_slug",
        ),
        Index("idx_org_chunking_profiles_org_id", "organization_id"),
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
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[dict] = mapped_column(
        "config",
        JSON,
        nullable=False,
        default=dict,
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    organization = relationship("Organization", back_populates="chunking_profiles")
    created_by_user = relationship(
        "User",
        foreign_keys=[created_by_user_id],
        back_populates="chunking_profiles_created",
    )
    updated_by_user = relationship(
        "User",
        foreign_keys=[updated_by_user_id],
        back_populates="chunking_profiles_updated",
    )
