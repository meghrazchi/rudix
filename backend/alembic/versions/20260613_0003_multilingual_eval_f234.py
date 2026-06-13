"""Multilingual evaluation datasets and regression gates (F234)

Adds language metadata to evaluation questions and results so that
quality metrics can be sliced by locale (en/de/es/fr).

evaluation_questions:
  question_language        – ISO 639-1 code of the question text
  expected_answer_language – ISO 639-1 code of the expected response
  source_language          – ISO 639-1 code of the reference document(s)
  translation_notes        – free-text notes for cross-language cases

evaluation_results:
  detected_answer_language – ISO 639-1 code detected in the generated answer
  language_match_score     – 0.0 or 1.0: does the answer language match expected?

Revision ID: 20260613_0003
Revises: 20260613_0002
Create Date: 2026-06-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260613_0003"
down_revision: str | None = "20260613_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_questions",
        sa.Column("question_language", sa.String(8), nullable=True),
    )
    op.add_column(
        "evaluation_questions",
        sa.Column("expected_answer_language", sa.String(8), nullable=True),
    )
    op.add_column(
        "evaluation_questions",
        sa.Column("source_language", sa.String(8), nullable=True),
    )
    op.add_column(
        "evaluation_questions",
        sa.Column("translation_notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_evaluation_questions_question_language",
        "evaluation_questions",
        ["question_language"],
    )

    op.add_column(
        "evaluation_results",
        sa.Column("detected_answer_language", sa.String(8), nullable=True),
    )
    op.add_column(
        "evaluation_results",
        sa.Column("language_match_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluation_results", "language_match_score")
    op.drop_column("evaluation_results", "detected_answer_language")
    op.drop_index(
        "idx_evaluation_questions_question_language",
        table_name="evaluation_questions",
    )
    op.drop_column("evaluation_questions", "translation_notes")
    op.drop_column("evaluation_questions", "source_language")
    op.drop_column("evaluation_questions", "expected_answer_language")
    op.drop_column("evaluation_questions", "question_language")
