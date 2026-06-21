from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

CITATION_MODES = ("required", "recommended", "disabled")
NO_ANSWER_BEHAVIORS = ("refuse", "warn", "allow")
STALE_SOURCE_BEHAVIORS = ("warn", "refuse", "ignore")
DISCLAIMER_POSITIONS = ("prepend", "append")
POLICY_DECISION_OUTCOMES = ("allowed", "blocked", "warned")
POLICY_SOURCES = ("org", "collection", "none")


class OrgAiResponsePolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Organisation-scoped AI answer behaviour policy.

    There is at most one active policy per organisation.  A draft policy
    can be tested via the preview endpoint before activation.
    """

    __tablename__ = "org_ai_response_policies"
    __table_args__ = (
        Index(
            "uq_org_ai_policy_one_active",
            "organization_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
            sqlite_where=text("is_active IS 1"),
        ),
        CheckConstraint(
            "citation_mode IN ('required', 'recommended', 'disabled')",
            name="org_ai_policy_citation_mode_allowed",
        ),
        CheckConstraint(
            "no_answer_behavior IN ('refuse', 'warn', 'allow')",
            name="org_ai_policy_no_answer_behavior_allowed",
        ),
        CheckConstraint(
            "stale_source_behavior IN ('warn', 'refuse', 'ignore')",
            name="org_ai_policy_stale_source_behavior_allowed",
        ),
        CheckConstraint(
            "disclaimer_position IN ('prepend', 'append')",
            name="org_ai_policy_disclaimer_position_allowed",
        ),
        CheckConstraint(
            "min_confidence_threshold IS NULL OR (min_confidence_threshold >= 0.0 AND min_confidence_threshold <= 1.0)",
            name="org_ai_policy_confidence_threshold_range",
        ),
        CheckConstraint(
            "min_sources_required IS NULL OR min_sources_required >= 0",
            name="org_ai_policy_min_sources_non_negative",
        ),
        Index("idx_org_ai_policy_org_active", "organization_id", "is_active"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
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

    policy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Citation rules
    citation_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="recommended")

    # Confidence threshold enforcement
    min_confidence_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_answer_behavior: Mapped[str] = mapped_column(String(32), nullable=False, default="warn")
    grounded_verification_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="off"
    )
    grounded_verification_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Source freshness
    stale_source_behavior: Mapped[str] = mapped_column(String(32), nullable=False, default="warn")

    # Topic controls — stored as JSON arrays
    blocked_topics_json: Mapped[list[str] | None] = mapped_column(
        "blocked_topics", JSON, nullable=True
    )
    allowed_topics_json: Mapped[list[str] | None] = mapped_column(
        "allowed_topics", JSON, nullable=True
    )

    # Source quantity gate
    min_sources_required: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Disclaimer injection
    disclaimer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    disclaimer_position: Mapped[str] = mapped_column(String(16), nullable=False, default="prepend")

    # Custom refusal message shown to end users
    refusal_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization = relationship("Organization", back_populates="ai_response_policies")
    collection_overrides = relationship(
        "CollectionAiResponsePolicyOverride",
        back_populates="org_policy",
        cascade="all, delete-orphan",
    )


class CollectionAiResponsePolicyOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-collection overrides on top of the org-level AI response policy.

    Only the fields explicitly set here take precedence over the org policy.
    NULL means "inherit from org policy".
    """

    __tablename__ = "collection_ai_response_policy_overrides"
    __table_args__ = (
        UniqueConstraint(
            "org_policy_id",
            "collection_id",
            name="uq_collection_ai_policy_org_collection",
        ),
        CheckConstraint(
            "citation_mode IS NULL OR citation_mode IN ('required', 'recommended', 'disabled')",
            name="col_ai_policy_citation_mode_allowed",
        ),
        CheckConstraint(
            "no_answer_behavior IS NULL OR no_answer_behavior IN ('refuse', 'warn', 'allow')",
            name="col_ai_policy_no_answer_behavior_allowed",
        ),
        CheckConstraint(
            "stale_source_behavior IS NULL OR stale_source_behavior IN ('warn', 'refuse', 'ignore')",
            name="col_ai_policy_stale_source_behavior_allowed",
        ),
        CheckConstraint(
            "min_confidence_threshold IS NULL OR (min_confidence_threshold >= 0.0 AND min_confidence_threshold <= 1.0)",
            name="col_ai_policy_confidence_threshold_range",
        ),
        Index("idx_col_ai_policy_org", "org_policy_id"),
        Index("idx_col_ai_policy_collection", "collection_id"),
    )

    org_policy_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("org_ai_response_policies.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # All fields are nullable — NULL = inherit from org policy
    citation_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    min_confidence_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_answer_behavior: Mapped[str | None] = mapped_column(String(32), nullable=True)
    grounded_verification_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    grounded_verification_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    stale_source_behavior: Mapped[str | None] = mapped_column(String(32), nullable=True)
    blocked_topics_json: Mapped[list[str] | None] = mapped_column(
        "blocked_topics", JSON, nullable=True
    )
    allowed_topics_json: Mapped[list[str] | None] = mapped_column(
        "allowed_topics", JSON, nullable=True
    )
    min_sources_required: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disclaimer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    refusal_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    org_policy = relationship("OrgAiResponsePolicy", back_populates="collection_overrides")


class PolicyEvaluationLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Audit record of every AI response policy decision."""

    __tablename__ = "policy_evaluation_logs"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('allowed', 'blocked', 'warned')",
            name="policy_eval_log_outcome_allowed",
        ),
        CheckConstraint(
            "policy_source IN ('org', 'collection', 'none')",
            name="policy_eval_log_source_allowed",
        ),
        Index("idx_policy_eval_log_org_created", "organization_id", "created_at"),
        Index("idx_policy_eval_log_org_outcome", "organization_id", "outcome"),
        Index("idx_policy_eval_log_policy", "org_policy_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    org_policy_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("org_ai_response_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    chat_session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    chat_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )

    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="allowed")
    policy_source: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    violated_rules_json: Mapped[list[str] | None] = mapped_column(
        "violated_rules", JSON, nullable=True
    )
    warning_flags_json: Mapped[list[str] | None] = mapped_column(
        "warning_flags", JSON, nullable=True
    )
    question_preview: Mapped[str | None] = mapped_column(String(256), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stale_source_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_preview_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
