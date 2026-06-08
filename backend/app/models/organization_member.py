from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import OrganizationRole

_ROLE_CHECK = (
    "role IN ("
    "'owner', 'admin', 'member', 'viewer', "
    "'reviewer', 'security_admin', 'billing_admin', 'developer'"
    ")"
)


class OrganizationMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        CheckConstraint(
            _ROLE_CHECK,
            name="organization_members_role_allowed",
        ),
        Index("idx_organization_members_org_role", "organization_id", "role"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OrganizationRole.member.value,
    )
    custom_role_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("custom_roles.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="memberships")
    custom_role = relationship("CustomRole", foreign_keys=[custom_role_id])
