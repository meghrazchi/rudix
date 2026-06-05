from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class PromptTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "template_key",
            name="uq_prompt_templates_org_key",
        ),
        Index("idx_prompt_templates_organization_id", "organization_id"),
        Index("idx_prompt_templates_org_key", "organization_id", "template_key"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    latest_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    organization = relationship("Organization", back_populates="prompt_templates")
    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    versions = relationship(
        "PromptTemplateVersion",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="PromptTemplateVersion.version_number.desc()",
    )


class PromptTemplateVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "prompt_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "prompt_template_id",
            "version_number",
            name="uq_prompt_template_versions_template_version",
        ),
        CheckConstraint(
            "state IN ('draft', 'review', 'published')",
            name="prompt_template_versions_state_allowed",
        ),
        CheckConstraint("version_number >= 1", name="prompt_template_versions_version_positive"),
        Index("idx_prompt_template_versions_template_id", "prompt_template_id"),
        Index("idx_prompt_template_versions_state", "prompt_template_id", "state"),
    )

    prompt_template_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    variables_json: Mapped[list[dict]] = mapped_column("variables", JSONB, nullable=False)
    variable_schema_json: Mapped[dict] = mapped_column("variable_schema", JSONB, nullable=False)
    preview_context_json: Mapped[dict] = mapped_column("preview_context", JSONB, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        server_onupdate=func.now(),
        nullable=False,
    )

    template = relationship("PromptTemplate", back_populates="versions")
    created_by = relationship("User", foreign_keys=[created_by_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
    published_by = relationship("User", foreign_keys=[published_by_id])
    chat_messages = relationship("ChatMessage", back_populates="prompt_template_version")
    evaluation_runs = relationship("EvaluationRun", back_populates="prompt_template_version")
    agent_runs = relationship("AgentRun", back_populates="prompt_template_version")
