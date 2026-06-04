from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class RagProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_profiles"
    __table_args__ = (
        Index("idx_rag_profiles_organization_id", "organization_id"),
        Index("idx_rag_profiles_org_default", "organization_id", "is_default"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # Retrieval and generation config stored as JSONB
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Bumped on every config change; used as the version_number for new snapshots
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization", back_populates="rag_profiles")
    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    versions = relationship(
        "RagProfileVersion",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="RagProfileVersion.version_number.desc()",
    )
    collection_overrides = relationship(
        "RagProfileCollectionOverride",
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class RagProfileVersion(UUIDPrimaryKeyMixin, Base):
    """Immutable config snapshot for a RAG profile at a given version number."""

    __tablename__ = "rag_profile_versions"
    __table_args__ = (
        UniqueConstraint(
            "rag_profile_id",
            "version_number",
            name="uq_rag_profile_versions_profile_version",
        ),
        Index("idx_rag_profile_versions_profile_id", "rag_profile_id"),
    )

    rag_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    changed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    profile = relationship("RagProfile", back_populates="versions")
    changed_by = relationship("User", foreign_keys=[changed_by_id])


class RagProfileCollectionOverride(UUIDPrimaryKeyMixin, Base):
    """Associates a specific RAG profile with a collection, overriding the org default."""

    __tablename__ = "rag_profile_collection_overrides"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "collection_id",
            name="uq_rag_profile_collection_overrides_org_collection",
        ),
        Index(
            "idx_rag_profile_collection_overrides_org",
            "organization_id",
            "collection_id",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=False,
    )
    rag_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    profile = relationship("RagProfile", back_populates="collection_overrides")
    created_by = relationship("User", foreign_keys=[created_by_id])
