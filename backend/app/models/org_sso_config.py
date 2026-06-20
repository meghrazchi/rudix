from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.organization import Organization


class OrgSSOConfig(Base):
    __tablename__ = "org_sso_configs"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_org_sso_configs_org_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sso_type: Mapped[str] = mapped_column(String(16), nullable=False, default="saml")
    domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # IdP configuration — URL takes priority over raw XML when both provided
    idp_metadata_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    idp_metadata_xml: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Parsed / derived from IdP metadata
    idp_sso_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    idp_entity_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    idp_certificate: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SP identifiers (generated once, stable per org)
    sp_entity_id: Mapped[str] = mapped_column(String(2048), nullable=False)
    sp_acs_url: Mapped[str] = mapped_column(String(2048), nullable=False)

    # Optional SAML attribute → user-field mapping
    attribute_mapping: Mapped[dict] = mapped_column(
        JSONB(astext_type=Text()),
        nullable=False,
        server_default="{}",
    )

    # Test connection state
    last_test_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    organization: Mapped[Organization] = relationship(  # noqa: F821
        "Organization",
        back_populates="sso_config",
        foreign_keys=[organization_id],
    )
