"""Org workflow memory and user memory preferences (F343)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

_WORKFLOW_TYPES = (
    "audit_evidence_pack",
    "policy_comparison",
    "contract_review",
    "onboarding_faq",
    "custom",
)
_WORKFLOW_STATUSES = ("active", "archived")
_SCOPE_VALUES = ("all", "collection", "docs", "none")


class OrgWorkflow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Saved reusable workflow template stored at organization scope.

    Steps are stored as a JSON array in the ``steps`` column. Each step is a
    plain dict with ``label``, ``query_template`` (optional), ``scope``, and
    ``collection_ids`` (list).  No raw document text or secrets are stored.
    """

    __tablename__ = "org_workflows"
    __table_args__ = (
        CheckConstraint(
            "workflow_type IN ({})".format(", ".join(f"'{t}'" for t in _WORKFLOW_TYPES)),
            name="org_workflows_type_allowed",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="org_workflows_status_allowed",
        ),
        Index("idx_org_workflows_org_status", "organization_id", "status"),
        Index("idx_org_workflows_org_type", "organization_id", "workflow_type"),
        Index("idx_org_workflows_created_by", "created_by_id"),
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # JSON array of step objects. Validated in service layer.
    steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    # CSV of role names that can access this workflow; NULL means all roles.
    role_scope: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # JSON array of collection UUID strings; NULL means no collection restriction.
    collection_scope_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional link to a verified knowledge card.
    verified_knowledge_card_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("verified_answers.id", ondelete="SET NULL"),
        nullable=True,
    )
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by = relationship("User", foreign_keys=[created_by_id])
    verified_knowledge_card = relationship(
        "VerifiedAnswer", foreign_keys=[verified_knowledge_card_id]
    )


class UserMemoryPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user RAG defaults and source scope preferences (org-scoped)."""

    __tablename__ = "user_memory_preferences"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_user_memory_preferences_org_user",
        ),
        CheckConstraint(
            "preferred_scope IS NULL OR preferred_scope IN ({})".format(
                ", ".join(f"'{s}'" for s in _SCOPE_VALUES)
            ),
            name="user_memory_preferences_scope_allowed",
        ),
        Index("idx_user_memory_preferences_org_user", "organization_id", "user_id"),
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
    # Preferred chat scope: all / collection / docs / none
    preferred_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # JSON array of preferred collection UUID strings.
    preferred_collection_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional default RAG profile override.
    rag_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    answer_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # JSON map for future-proofing (non-sensitive key/value pairs only).
    extra_defaults: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", foreign_keys=[user_id])
