from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.organization import Organization


class OrgDomainVerification(Base):
    __tablename__ = "org_domain_verifications"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "domain", name="uq_org_domain_verifications_org_domain"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    # 'pending' | 'verified' | 'failed'
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # Random hex token admins paste as a DNS TXT record
    verification_token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    verified_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[UUID | None] = mapped_column(
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

    organization: Mapped[Organization] = relationship(  # noqa: F821
        "Organization",
        back_populates="domain_verifications",
        foreign_keys=[organization_id],
    )
