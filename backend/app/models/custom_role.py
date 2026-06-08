from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class CustomRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "custom_roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_custom_roles_org_name"),
        Index("idx_custom_roles_org_id", "organization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization")
    created_by = relationship("User", foreign_keys=[created_by_id])
    permissions: Mapped[list["CustomRolePermission"]] = relationship(
        "CustomRolePermission",
        back_populates="custom_role",
        cascade="all, delete-orphan",
    )


class CustomRolePermission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "custom_role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "custom_role_id", "permission", name="uq_custom_role_permissions_role_perm"
        ),
        Index("idx_custom_role_permissions_role_id", "custom_role_id"),
    )

    custom_role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("custom_roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    permission: Mapped[str] = mapped_column(String(64), nullable=False)

    custom_role: Mapped["CustomRole"] = relationship(
        "CustomRole", back_populates="permissions"
    )
