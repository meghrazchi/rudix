from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class Citation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "citations"
    __table_args__ = (Index("idx_citations_message", "chat_message_id"),)

    chat_message_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    text_snippet: Mapped[str] = mapped_column(Text(), nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(nullable=True)
    rerank_score: Mapped[float | None] = mapped_column(nullable=True)

    chat_message = relationship("ChatMessage", back_populates="citations")
    document = relationship("Document", back_populates="citations")
    chunk = relationship("DocumentChunk", back_populates="citations")
