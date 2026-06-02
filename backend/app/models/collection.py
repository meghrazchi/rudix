from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class Collection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collections"
    __table_args__ = (
        CheckConstraint(
            "access_policy IN ('org_wide', 'admin_only', 'selected_roles', 'selected_members')",
            name="collections_access_policy_allowed",
        ),
        CheckConstraint("length(trim(name)) >= 1", name="collections_name_not_blank"),
        Index("idx_collections_org_id", "organization_id"),
        Index("idx_collections_owner_id", "owner_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="org_wide"
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    organization = relationship("Organization", back_populates="collections")
    owner = relationship("User", back_populates="owned_collections")
    document_memberships = relationship(
        "CollectionDocument",
        back_populates="collection",
        cascade="all, delete-orphan",
    )
    access_grants = relationship(
        "CollectionAccessGrant",
        back_populates="collection",
        cascade="all, delete-orphan",
    )


class CollectionDocument(TimestampMixin, Base):
    __tablename__ = "collection_documents"
    __table_args__ = (
        UniqueConstraint("collection_id", "document_id", name="uq_collection_documents_pair"),
        Index("idx_collection_documents_collection_id", "collection_id"),
        Index("idx_collection_documents_document_id", "document_id"),
    )

    collection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    collection = relationship("Collection", back_populates="document_memberships")
    document = relationship("Document", back_populates="collection_memberships")


class CollectionAccessGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collection_access_grants"
    __table_args__ = (
        CheckConstraint(
            "grantee_type IN ('role', 'member')",
            name="collection_access_grants_grantee_type_allowed",
        ),
        UniqueConstraint(
            "collection_id",
            "grantee_type",
            "grantee_value",
            name="uq_collection_access_grants",
        ),
        Index("idx_collection_access_grants_collection_id", "collection_id"),
    )

    collection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=False,
    )
    grantee_type: Mapped[str] = mapped_column(String(32), nullable=False)
    grantee_value: Mapped[str] = mapped_column(String(255), nullable=False)
    granted_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    collection = relationship("Collection", back_populates="access_grants")
