"""evaluation dataset builder

Revision ID: 20260604_0003
Revises: 20260604_0002
Create Date: 2026-06-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_0003"
down_revision: str | None = "20260604_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_sets",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(
        "evaluation_sets",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "evaluation_sets",
        sa.Column(
            "owner_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "evaluation_sets",
        sa.Column(
            "scope",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_foreign_key(
        "fk_evaluation_sets_owner_id_users",
        "evaluation_sets",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "evaluation_questions",
        sa.Column(
            "difficulty",
            sa.String(length=16),
            nullable=True,
        ),
    )
    op.add_column(
        "evaluation_questions",
        sa.Column(
            "owner_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_evaluation_questions_owner_id_users",
        "evaluation_questions",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "evaluation_dataset_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evaluation_set_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_set_id"],
            ["evaluation_sets.id"],
            name="fk_eval_dataset_versions_evaluation_set_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"],
            ["users.id"],
            name="fk_evaluation_dataset_versions_published_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_dataset_versions"),
        sa.UniqueConstraint(
            "evaluation_set_id",
            "version_number",
            name="uq_evaluation_dataset_versions_set_version",
        ),
    )
    op.create_index(
        "idx_eval_dataset_versions_set_id",
        "evaluation_dataset_versions",
        ["evaluation_set_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_eval_dataset_versions_set_id", table_name="evaluation_dataset_versions")
    op.drop_table("evaluation_dataset_versions")

    op.drop_constraint(
        "fk_evaluation_questions_owner_id_users",
        "evaluation_questions",
        type_="foreignkey",
    )
    op.drop_column("evaluation_questions", "owner_id")
    op.drop_column("evaluation_questions", "difficulty")

    op.drop_constraint(
        "fk_evaluation_sets_owner_id_users",
        "evaluation_sets",
        type_="foreignkey",
    )
    op.drop_column("evaluation_sets", "scope")
    op.drop_column("evaluation_sets", "owner_id")
    op.drop_column("evaluation_sets", "version")
    op.drop_column("evaluation_sets", "status")
