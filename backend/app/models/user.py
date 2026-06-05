from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("idx_users_organization_id", "organization_id"),)

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_auth_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # SCIM / lifecycle fields
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 'manual' | 'sso' | 'scim'
    provisioned_by: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual"
    )
    scim_external_id: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )

    organization = relationship("Organization", back_populates="users")
    memberships = relationship(
        "OrganizationMember", back_populates="user", cascade="all, delete-orphan"
    )
    documents = relationship("Document", back_populates="uploader")
    chat_sessions = relationship("ChatSession", back_populates="user")
    usage_events = relationship("UsageEvent", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")
    agent_runs = relationship("AgentRun", back_populates="user")
    agent_steps = relationship("AgentStep", back_populates="user")
    agent_tool_calls = relationship("AgentToolCall", back_populates="user")
    agent_approvals_requested = relationship(
        "AgentApproval",
        foreign_keys="AgentApproval.requested_by_user_id",
        back_populates="requested_by_user",
    )
    agent_approvals_decided = relationship(
        "AgentApproval",
        foreign_keys="AgentApproval.decided_by_user_id",
        back_populates="decided_by_user",
    )
    governance_policies_updated = relationship(
        "OrganizationGovernancePolicy",
        back_populates="updated_by_user",
    )
    owned_collections = relationship("Collection", back_populates="owner")
    chunking_profiles_created = relationship(
        "OrganizationChunkingProfile",
        foreign_keys="OrganizationChunkingProfile.created_by_user_id",
        back_populates="created_by_user",
    )
    chunking_profiles_updated = relationship(
        "OrganizationChunkingProfile",
        foreign_keys="OrganizationChunkingProfile.updated_by_user_id",
        back_populates="updated_by_user",
    )
