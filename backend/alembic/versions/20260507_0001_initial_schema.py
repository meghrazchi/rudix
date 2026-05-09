"""initial schema

Revision ID: 20260507_0001
Revises: None
Create Date: 2026-05-07 15:30:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260507_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("name", name=op.f("uq_organizations_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )

    op.create_table(
        "users",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("external_auth_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_users_organization_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("external_auth_id", name=op.f("uq_users_external_auth_id")),
    )
    op.create_index("idx_users_organization_id", "users", ["organization_id"], unique=False)

    op.create_table(
        "organization_members",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'viewer')", name=op.f("ck_organization_members_organization_members_role_allowed")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_organization_members_organization_id_organizations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_organization_members_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_members")),
        sa.UniqueConstraint("organization_id", "user_id", name=op.f("uq_organization_members_organization_id")),
    )
    op.create_index("idx_organization_members_org_role", "organization_members", ["organization_id", "role"], unique=False)

    op.create_table(
        "documents",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("storage_bucket", sa.String(length=255), nullable=False),
        sa.Column("storage_object_key", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("file_type IN ('pdf', 'txt', 'docx')", name=op.f("ck_documents_documents_file_type_allowed")),
        sa.CheckConstraint("page_count IS NULL OR page_count >= 0", name=op.f("ck_documents_documents_page_count_non_negative")),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'indexed', 'failed', 'deleting', 'deleted')",
            name=op.f("ck_documents_documents_status_allowed"),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_documents_organization_id_organizations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], name=op.f("fk_documents_uploaded_by_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index("idx_documents_org_status", "documents", ["organization_id", "status"], unique=False)
    op.create_index("idx_documents_uploaded_by", "documents", ["uploaded_by_user_id"], unique=False)

    op.create_table(
        "chat_sessions",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_chat_sessions_organization_id_organizations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_chat_sessions_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
    )
    op.create_index("idx_chat_sessions_user", "chat_sessions", ["user_id", "created_at"], unique=False)

    op.create_table(
        "document_pages",
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_count >= 0", name=op.f("ck_document_pages_document_pages_char_count_non_negative")),
        sa.CheckConstraint("page_number >= 1", name=op.f("ck_document_pages_document_pages_page_number_positive")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_document_pages_document_id_documents"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_pages")),
        sa.UniqueConstraint("document_id", "page_number", name=op.f("uq_document_pages_document_id")),
    )
    op.create_index("idx_document_pages_document_id", "document_pages", ["document_id"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("qdrant_point_id", sa.String(length=128), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("index_version", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("chunk_index >= 0", name=op.f("ck_document_chunks_document_chunks_chunk_index_non_negative")),
        sa.CheckConstraint("page_number IS NULL OR page_number >= 1", name=op.f("ck_document_chunks_document_chunks_page_number_positive")),
        sa.CheckConstraint("token_count >= 0", name=op.f("ck_document_chunks_document_chunks_token_count_non_negative")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_document_chunks_document_id_documents"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint("document_id", "chunk_index", "index_version", name=op.f("uq_document_chunks_document_id")),
        sa.UniqueConstraint("qdrant_point_id", name=op.f("uq_document_chunks_qdrant_point_id")),
    )
    op.create_index("idx_chunks_document_id", "document_chunks", ["document_id"], unique=False)
    op.create_index("idx_chunks_qdrant_point_id", "document_chunks", ["qdrant_point_id"], unique=False)

    op.create_table(
        "evaluation_sets",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_evaluation_sets_organization_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_sets")),
    )
    op.create_index("idx_evaluation_sets_organization_id", "evaluation_sets", ["organization_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("chat_session_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("token_input_count", sa.Integer(), nullable=True),
        sa.Column("token_output_count", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name=op.f("ck_chat_messages_chat_messages_cost_non_negative")),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name=op.f("ck_chat_messages_chat_messages_latency_non_negative")),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system')", name=op.f("ck_chat_messages_chat_messages_role_allowed")),
        sa.CheckConstraint("token_input_count IS NULL OR token_input_count >= 0", name=op.f("ck_chat_messages_chat_messages_input_tokens_non_negative")),
        sa.CheckConstraint("token_output_count IS NULL OR token_output_count >= 0", name=op.f("ck_chat_messages_chat_messages_output_tokens_non_negative")),
        sa.ForeignKeyConstraint(["chat_session_id"], ["chat_sessions.id"], name=op.f("fk_chat_messages_chat_session_id_chat_sessions"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )
    op.create_index("idx_chat_messages_session", "chat_messages", ["chat_session_id", "created_at"], unique=False)

    op.create_table(
        "evaluation_questions",
        sa.Column("evaluation_set_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        sa.Column("expected_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("expected_page_number", sa.Integer(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_set_id"], ["evaluation_sets.id"], name=op.f("fk_evaluation_questions_evaluation_set_id_evaluation_sets"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["expected_document_id"], ["documents.id"], name=op.f("fk_evaluation_questions_expected_document_id_documents"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_questions")),
    )
    op.create_index("idx_evaluation_questions_set_id", "evaluation_questions", ["evaluation_set_id"], unique=False)

    op.create_table(
        "evaluation_runs",
        sa.Column("evaluation_set_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name=op.f("ck_evaluation_runs_evaluation_runs_status_allowed"),
        ),
        sa.ForeignKeyConstraint(["evaluation_set_id"], ["evaluation_sets.id"], name=op.f("fk_evaluation_runs_evaluation_set_id_evaluation_sets"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
    )
    op.create_index("idx_eval_runs_set", "evaluation_runs", ["evaluation_set_id", "created_at"], unique=False)

    op.create_table(
        "pipeline_runs",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("pipeline_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("logs", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("chat_message_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("evaluation_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name=op.f("ck_pipeline_runs_pipeline_runs_duration_non_negative"),
        ),
        sa.CheckConstraint(
            "pipeline_type IN ('document.process', 'document.reindex', 'document.delete', 'chat.query', 'evaluation.run')",
            name=op.f("ck_pipeline_runs_pipeline_runs_pipeline_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name=op.f("ck_pipeline_runs_pipeline_runs_status_allowed"),
        ),
        sa.ForeignKeyConstraint(["chat_message_id"], ["chat_messages.id"], name=op.f("fk_pipeline_runs_chat_message_id_chat_messages"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_pipeline_runs_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluation_run_id"], ["evaluation_runs.id"], name=op.f("fk_pipeline_runs_evaluation_run_id_evaluation_runs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_pipeline_runs_organization_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_runs")),
    )
    op.create_index("idx_pipeline_runs_chat_message_id", "pipeline_runs", ["chat_message_id"], unique=False)
    op.create_index("idx_pipeline_runs_document_id", "pipeline_runs", ["document_id"], unique=False)
    op.create_index("idx_pipeline_runs_evaluation_run_id", "pipeline_runs", ["evaluation_run_id"], unique=False)
    op.create_index("idx_pipeline_runs_org_created", "pipeline_runs", ["organization_id", "created_at"], unique=False)

    op.create_table(
        "pipeline_events",
        sa.Column("pipeline_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("logs", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name=op.f("ck_pipeline_events_pipeline_events_duration_non_negative")),
        sa.CheckConstraint("sequence >= 0", name=op.f("ck_pipeline_events_pipeline_events_sequence_non_negative")),
        sa.CheckConstraint(
            "status IN ('started', 'completed', 'failed', 'skipped')",
            name=op.f("ck_pipeline_events_pipeline_events_status_allowed"),
        ),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], name=op.f("fk_pipeline_events_pipeline_run_id_pipeline_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_events")),
        sa.UniqueConstraint("pipeline_run_id", "sequence", name=op.f("uq_pipeline_events_pipeline_run_id")),
    )
    op.create_index("idx_pipeline_events_node_status", "pipeline_events", ["node_name", "status"], unique=False)
    op.create_index("idx_pipeline_events_run_sequence", "pipeline_events", ["pipeline_run_id", "sequence"], unique=False)

    op.create_table(
        "usage_events",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name=op.f("ck_usage_events_usage_events_cost_non_negative")),
        sa.CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name=op.f("ck_usage_events_usage_events_input_tokens_non_negative")),
        sa.CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name=op.f("ck_usage_events_usage_events_output_tokens_non_negative")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_usage_events_organization_id_organizations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_usage_events_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_index("idx_usage_org_created", "usage_events", ["organization_id", "created_at"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_audit_logs_organization_id_organizations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_audit_logs_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("idx_audit_logs_org_created", "audit_logs", ["organization_id", "created_at"], unique=False)

    op.create_table(
        "evaluation_results",
        sa.Column("evaluation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evaluation_question_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("generated_answer", sa.Text(), nullable=True),
        sa.Column("retrieval_score", sa.Float(), nullable=True),
        sa.Column("faithfulness_score", sa.Float(), nullable=True),
        sa.Column("citation_accuracy_score", sa.Float(), nullable=True),
        sa.Column("answer_relevance_score", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_question_id"], ["evaluation_questions.id"], name=op.f("fk_evaluation_results_evaluation_question_id_evaluation_questions"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluation_run_id"], ["evaluation_runs.id"], name=op.f("fk_evaluation_results_evaluation_run_id_evaluation_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_results")),
    )
    op.create_index("idx_evaluation_results_run_id", "evaluation_results", ["evaluation_run_id"], unique=False)

    op.create_table(
        "citations",
        sa.Column("chat_message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("text_snippet", sa.Text(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chat_message_id"], ["chat_messages.id"], name=op.f("fk_citations_chat_message_id_chat_messages"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], name=op.f("fk_citations_chunk_id_document_chunks"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_citations_document_id_documents"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_citations")),
    )
    op.create_index("idx_citations_message", "citations", ["chat_message_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_citations_message", table_name="citations")
    op.drop_table("citations")

    op.drop_index("idx_pipeline_events_run_sequence", table_name="pipeline_events")
    op.drop_index("idx_pipeline_events_node_status", table_name="pipeline_events")
    op.drop_table("pipeline_events")

    op.drop_index("idx_pipeline_runs_org_created", table_name="pipeline_runs")
    op.drop_index("idx_pipeline_runs_evaluation_run_id", table_name="pipeline_runs")
    op.drop_index("idx_pipeline_runs_document_id", table_name="pipeline_runs")
    op.drop_index("idx_pipeline_runs_chat_message_id", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")

    op.drop_index("idx_evaluation_results_run_id", table_name="evaluation_results")
    op.drop_table("evaluation_results")

    op.drop_index("idx_audit_logs_org_created", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("idx_usage_org_created", table_name="usage_events")
    op.drop_table("usage_events")

    op.drop_index("idx_eval_runs_set", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")

    op.drop_index("idx_evaluation_questions_set_id", table_name="evaluation_questions")
    op.drop_table("evaluation_questions")

    op.drop_index("idx_chat_messages_session", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("idx_evaluation_sets_organization_id", table_name="evaluation_sets")
    op.drop_table("evaluation_sets")

    op.drop_index("idx_chunks_qdrant_point_id", table_name="document_chunks")
    op.drop_index("idx_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index("idx_document_pages_document_id", table_name="document_pages")
    op.drop_table("document_pages")

    op.drop_index("idx_chat_sessions_user", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.drop_index("idx_documents_uploaded_by", table_name="documents")
    op.drop_index("idx_documents_org_status", table_name="documents")
    op.drop_table("documents")

    op.drop_index("idx_organization_members_org_role", table_name="organization_members")
    op.drop_table("organization_members")

    op.drop_index("idx_users_organization_id", table_name="users")
    op.drop_table("users")

    op.drop_table("organizations")
