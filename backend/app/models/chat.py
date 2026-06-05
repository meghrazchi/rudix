from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ChatRole


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (Index("idx_chat_sessions_user", "user_id", "created_at"),)

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
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    organization = relationship("Organization", back_populates="chat_sessions")
    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="chat_messages_role_allowed",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="chat_messages_latency_non_negative"
        ),
        CheckConstraint(
            "token_input_count IS NULL OR token_input_count >= 0",
            name="chat_messages_input_tokens_non_negative",
        ),
        CheckConstraint(
            "token_output_count IS NULL OR token_output_count >= 0",
            name="chat_messages_output_tokens_non_negative",
        ),
        CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0", name="chat_messages_cost_non_negative"
        ),
        Index("idx_chat_messages_session", "chat_session_id", "created_at"),
        Index("idx_chat_messages_prompt_template_version", "prompt_template_version_id"),
    )

    chat_session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ChatRole.user.value)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_input_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_output_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    prompt_template_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("prompt_template_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    session = relationship("ChatSession", back_populates="messages")
    prompt_template_version = relationship("PromptTemplateVersion", back_populates="chat_messages")
    citations = relationship(
        "Citation", back_populates="chat_message", cascade="all, delete-orphan"
    )
    pipeline_runs = relationship("PipelineRun", back_populates="chat_message")
