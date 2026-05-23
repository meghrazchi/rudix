from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EvaluationRunStatus


class EvaluationSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_sets"
    __table_args__ = (Index("idx_evaluation_sets_organization_id", "organization_id"),)

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)

    organization = relationship("Organization", back_populates="evaluation_sets")
    questions = relationship(
        "EvaluationQuestion", back_populates="evaluation_set", cascade="all, delete-orphan"
    )
    runs = relationship(
        "EvaluationRun", back_populates="evaluation_set", cascade="all, delete-orphan"
    )


class EvaluationQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_questions"
    __table_args__ = (Index("idx_evaluation_questions_set_id", "evaluation_set_id"),)

    evaluation_set_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text(), nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text(), nullable=True)
    expected_document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    expected_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    evaluation_set = relationship("EvaluationSet", back_populates="questions")
    expected_document = relationship("Document", back_populates="evaluation_questions")
    results = relationship("EvaluationResult", back_populates="evaluation_question")


class EvaluationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="evaluation_runs_status_allowed",
        ),
        Index("idx_eval_runs_set", "evaluation_set_id", "created_at"),
    )

    evaluation_set_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EvaluationRunStatus.queued.value
    )
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    evaluation_set = relationship("EvaluationSet", back_populates="runs")
    results = relationship(
        "EvaluationResult", back_populates="evaluation_run", cascade="all, delete-orphan"
    )
    pipeline_runs = relationship("PipelineRun", back_populates="evaluation_run")


class EvaluationResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (Index("idx_evaluation_results_run_id", "evaluation_run_id"),)

    evaluation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    evaluation_question_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    generated_answer: Mapped[str | None] = mapped_column(Text(), nullable=True)
    retrieval_score: Mapped[float | None] = mapped_column(nullable=True)
    faithfulness_score: Mapped[float | None] = mapped_column(nullable=True)
    citation_accuracy_score: Mapped[float | None] = mapped_column(nullable=True)
    answer_relevance_score: Mapped[float | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    evaluation_run = relationship("EvaluationRun", back_populates="results")
    evaluation_question = relationship("EvaluationQuestion", back_populates="results")
