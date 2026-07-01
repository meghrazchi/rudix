from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    sample_docs_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    onboarding_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
    agent_tool_policy_overrides = relationship(
        "AgentToolPolicyOverride",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    agent_trace_retention_policy = relationship(
        "AgentTraceRetentionPolicy",
        back_populates="organization",
        uselist=False,
        cascade="all, delete-orphan",
    )
    agent_trace_share_tokens = relationship(
        "AgentTraceShareToken",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
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
    quality_gates = relationship(
        "QualityGate", back_populates="organization", cascade="all, delete-orphan"
    )
    rag_profiles = relationship(
        "RagProfile", back_populates="organization", cascade="all, delete-orphan"
    )
    prompt_templates = relationship(
        "PromptTemplate", back_populates="organization", cascade="all, delete-orphan"
    )
    failed_jobs = relationship(
        "FailedJob", back_populates="organization", cascade="all, delete-orphan"
    )
    incidents = relationship(
        "Incident", back_populates="organization", cascade="all, delete-orphan"
    )
    sso_config = relationship(
        "OrgSSOConfig",
        back_populates="organization",
        cascade="all, delete-orphan",
        uselist=False,
    )
    scim_config = relationship(
        "OrgSCIMConfig",
        back_populates="organization",
        cascade="all, delete-orphan",
        uselist=False,
    )
    domain_verifications = relationship(
        "OrgDomainVerification",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    ab_experiments = relationship(
        "AbExperiment", back_populates="organization", cascade="all, delete-orphan"
    )
    mcp_policy = relationship(
        "OrgMCPPolicy",
        back_populates="organization",
        cascade="all, delete-orphan",
        uselist=False,
    )
    knowledge_gaps = relationship(
        "KnowledgeGap", back_populates="organization", cascade="all, delete-orphan"
    )
    ai_response_policies = relationship(
        "OrgAiResponsePolicy",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    portability_jobs = relationship(
        "WorkspacePortabilityJob",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
