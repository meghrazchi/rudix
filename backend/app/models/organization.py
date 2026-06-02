from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    users = relationship("User", back_populates="organization")
    members = relationship(
        "OrganizationMember", back_populates="organization", cascade="all, delete-orphan"
    )
    documents = relationship("Document", back_populates="organization")
    chat_sessions = relationship("ChatSession", back_populates="organization")
    evaluation_sets = relationship("EvaluationSet", back_populates="organization")
    usage_events = relationship("UsageEvent", back_populates="organization")
    audit_logs = relationship("AuditLog", back_populates="organization")
    pipeline_runs = relationship("PipelineRun", back_populates="organization")
    agent_runs = relationship("AgentRun", back_populates="organization")
    agent_steps = relationship("AgentStep", back_populates="organization")
    agent_tool_calls = relationship("AgentToolCall", back_populates="organization")
    agent_approvals = relationship("AgentApproval", back_populates="organization")
    governance_policy = relationship(
        "OrganizationGovernancePolicy",
        back_populates="organization",
        cascade="all, delete-orphan",
        uselist=False,
    )
    collections = relationship(
        "Collection", back_populates="organization", cascade="all, delete-orphan"
    )
    chunking_profiles = relationship(
        "OrganizationChunkingProfile",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
