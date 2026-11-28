# 06 — Database Schema

PostgreSQL is the source of truth for application state.

Qdrant stores vector embeddings, but PostgreSQL stores document and chunk metadata.

## Migration baseline

- Alembic baseline revision: `20260507_0001` (`backend/alembic/versions/20260507_0001_initial_schema.py`)
- SQLAlchemy async models are defined in `backend/app/models/`.
- Repositories for core CRUD flows are in `backend/app/repositories/`.
- Local commands:
  - `cd backend && make migrate`
  - `cd backend && make downgrade`
  - `cd backend && make seed-dev`

## Entity relationship diagram

```mermaid
erDiagram
    USERS ||--o{ ORGANIZATION_MEMBERS : belongs_to
    ORGANIZATIONS ||--o{ ORGANIZATION_MEMBERS : has
    ORGANIZATIONS ||--o{ DOCUMENTS : owns
    USERS ||--o{ DOCUMENTS : uploads
    DOCUMENTS ||--o{ DOCUMENT_PAGES : has
    DOCUMENTS ||--o{ DOCUMENT_CHUNKS : has
    DOCUMENT_CHUNKS ||--o{ CITATIONS : cited_by
    USERS ||--o{ CHAT_SESSIONS : starts
    CHAT_SESSIONS ||--o{ CHAT_MESSAGES : contains
    CHAT_MESSAGES ||--o{ CITATIONS : has
    CHAT_MESSAGES ||--o{ PIPELINE_RUNS : links
    ORGANIZATIONS ||--o{ EVALUATION_SETS : owns
    EVALUATION_SETS ||--o{ EVALUATION_QUESTIONS : contains
    EVALUATION_SETS ||--o{ EVALUATION_RUNS : has
    EVALUATION_RUNS ||--o{ EVALUATION_RESULTS : produces
    EVALUATION_RUNS ||--o{ PIPELINE_RUNS : links
    DOCUMENTS ||--o{ PIPELINE_RUNS : links
    PIPELINE_RUNS ||--o{ PIPELINE_EVENTS : contains

    USERS {
        uuid id PK
        string auth_provider_user_id
        string email
        string display_name
        timestamptz created_at
    }

    ORGANIZATIONS {
        uuid id PK
        string name
        timestamptz created_at
    }

    ORGANIZATION_MEMBERS {
        uuid id PK
        uuid organization_id FK
        uuid user_id FK
        string role
        timestamptz created_at
    }

    DOCUMENTS {
        uuid id PK
        uuid organization_id FK
        uuid uploaded_by_user_id FK
        string filename
        string file_type
        string storage_bucket
        string storage_object_key
        string status
        int page_count
        string checksum
        timestamptz created_at
        timestamptz updated_at
    }

    DOCUMENT_PAGES {
        uuid id PK
        uuid document_id FK
        int page_number
        text text
        int char_count
        timestamptz created_at
    }

    DOCUMENT_CHUNKS {
        uuid id PK
        uuid document_id FK
        int page_number
        int chunk_index
        text text
        int token_count
        string qdrant_point_id
        string embedding_model
        string index_version
        timestamptz created_at
    }

    CHAT_SESSIONS {
        uuid id PK
        uuid organization_id FK
        uuid user_id FK
        string title
        timestamptz created_at
    }

    CHAT_MESSAGES {
        uuid id PK
        uuid chat_session_id FK
        string role
        text content
        float confidence_score
        int latency_ms
        string model_name
        timestamptz created_at
    }

    CITATIONS {
        uuid id PK
        uuid chat_message_id FK
        uuid document_id FK
        uuid chunk_id FK
        int page_number
        text text_snippet
        float similarity_score
        float rerank_score
        timestamptz created_at
    }

    EVALUATION_SETS {
        uuid id PK
        uuid organization_id FK
        string name
        text description
        timestamptz created_at
    }

    EVALUATION_QUESTIONS {
        uuid id PK
        uuid evaluation_set_id FK
        text question
        text expected_answer
        uuid expected_document_id
        int expected_page_number
        timestamptz created_at
    }

    EVALUATION_RUNS {
        uuid id PK
        uuid evaluation_set_id FK
        string status
        jsonb config
        timestamptz started_at
        timestamptz completed_at
    }

    EVALUATION_RESULTS {
        uuid id PK
        uuid evaluation_run_id FK
        uuid evaluation_question_id FK
        text generated_answer
        float retrieval_score
        float faithfulness_score
        float citation_accuracy_score
        float answer_relevance_score
        int latency_ms
        jsonb details
        timestamptz created_at
    }

    PIPELINE_RUNS {
        uuid id PK
        uuid organization_id FK
        string pipeline_type
        string status
        timestamptz started_at
        timestamptz completed_at
        int duration_ms
        jsonb inputs
        jsonb outputs
        jsonb config
        jsonb logs
        text error_message
        jsonb error_details
        uuid document_id FK
        uuid chat_message_id FK
        uuid evaluation_run_id FK
        timestamptz created_at
    }

    PIPELINE_EVENTS {
        uuid id PK
        uuid pipeline_run_id FK
        int sequence
        string node_name
        string status
        timestamptz started_at
        timestamptz completed_at
        int duration_ms
        jsonb inputs
        jsonb outputs
        jsonb config
        jsonb logs
        text error_message
        jsonb error_details
        timestamptz created_at
    }
```

## Main tables

### users

Stores internal user mapping.

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    auth_provider_user_id TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### organizations

```sql
CREATE TABLE organizations (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### organization_members

```sql
CREATE TABLE organization_members (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    user_id UUID NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, user_id)
);
```

### documents

```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    uploaded_by_user_id UUID NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'txt', 'docx')),
    storage_bucket TEXT NOT NULL,
    storage_object_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('uploaded', 'processing', 'indexed', 'failed', 'deleting', 'deleted')
    ),
    page_count INTEGER,
    checksum TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### document_pages

```sql
CREATE TABLE document_pages (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, page_number)
);
```

### document_chunks

```sql
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    qdrant_point_id TEXT UNIQUE,
    embedding_model TEXT NOT NULL,
    index_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 0.6.0 (R06-09, migration 20261128_0002; nullable until the operator NOT NULL step)
    organization_id UUID,           -- = documents.organization_id; no foreign key
    fts_config VARCHAR(32),         -- english | german | spanish | french | simple
    fts_vector TSVECTOR,            -- to_tsvector(fts_config, text), written by the app
    UNIQUE (document_id, chunk_index, index_version)
);
```

`text_search_vector` (F293) stays the generated English column. The chunk stage writes
`organization_id`, `fts_config` (from the document language) and `fts_vector` for new
chunks. `documents.chunks.backfill_tenant` fills older rows in primary-key batches.
`deploy/sql/document_chunks_not_null.sql` then sets `organization_id NOT NULL` through a
validated `NOT VALID` check and adds the strict tenant policy (runbook 27). Indexes:
`idx_chunks_org_document (organization_id, document_id)` and the GIN
`idx_chunks_fts_vector`, both from migration `20261128_0003`.

### document_processing_stages

Staged ingestion bookkeeping (`0.6.0`, R06-01, migration `20261128_0001`). One row per
stage of a processing run; `run_id` is the Celery task id that holds the document's
processing claim, so a retry or redelivery of the same task finds its completed stages.
`metrics` holds counts and configuration only, never document text.

```sql
CREATE TABLE document_processing_stages (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    run_id VARCHAR(255) NOT NULL,
    stage VARCHAR(32) NOT NULL,           -- extract, clean_detect, dlp, chunk, graph_extract,
                                          -- embed, index, finalize
    status VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending | running | completed | failed
    attempt INTEGER NOT NULL DEFAULT 0,
    owner_task_id VARCHAR(255),           -- lease owner
    started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,             -- a running row older than INGEST_STAGE_LEASE_SECONDS
                                          -- may be leased by another task
    finished_at TIMESTAMPTZ,
    artifact_ref VARCHAR(512),
    metrics JSON NOT NULL DEFAULT '{}',
    error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, run_id, stage)
);
CREATE INDEX idx_document_processing_stages_org_created
    ON document_processing_stages (organization_id, created_at);
```

### document_stage_artifacts

Stage output a later stage reads: extracted pages (with table blocks), cleaned pages, and
embedding batch summaries (token counts and cost, no vectors), as zlib-compressed UTF-8
JSON. One part per page or per embedding batch; a page larger than
`INGEST_ARTIFACT_MAX_PART_BYTES` is split across consecutive parts. Finalize deletes the
run's artifacts and the stage rows of older runs; document deletion deletes both tables'
rows of the document.

```sql
CREATE TABLE document_stage_artifacts (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    run_id VARCHAR(255) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    part INTEGER NOT NULL,
    content BYTEA NOT NULL,
    content_bytes INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, run_id, stage, part)
);
CREATE INDEX idx_document_stage_artifacts_org_created
    ON document_stage_artifacts (organization_id, created_at);
```

Both tables are in `RLS_STRICT_TABLES_0_6_0` (strict tenant policy) and in
`deploy/sql/force_rls.sql`. Artifacts of runs that failed for good with a retryable error
are kept for the failed-job retry until `documents.stage_artifacts.purge` deletes them
(`INGEST_STAGE_ARTIFACT_TTL_HOURS`, default 72).

### outbox_messages (0.6.0, migration 20261128_0002)

Request-path Celery dispatches written in the transaction of the document change
(transactional outbox). Published after commit; `outbox.relay` publishes the rest.

```sql
CREATE TABLE outbox_messages (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    task_name VARCHAR(128) NOT NULL,
    queue VARCHAR(64),
    kwargs JSON NOT NULL DEFAULT '{}',          -- ids, flags, chunking profile only
    dedupe_key VARCHAR(255) UNIQUE,              -- conflicting enqueue is a no-op
    status VARCHAR(16) NOT NULL DEFAULT 'pending', -- pending | published | failed
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    last_error VARCHAR(128),                     -- exception class name or 'cancelled'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_outbox_messages_org_created ON outbox_messages (organization_id, created_at);
CREATE INDEX CONCURRENTLY idx_outbox_pending ON outbox_messages (status, available_at);
```

### vector_index_generations and vector_index_generation_documents (0.6.0)

Schema for zero-downtime vector index rebuilds (used by chain A). `vector_index_generations`
is global (no tenant column): `alias_name`, unique `collection_name`, `embedding_model`,
`vector_size`, `distance`, `generation` (unique with the alias), `state` (`building`,
`verifying`, `active`, `retired`, `failed`, `dropped`), `build_cursor`, point and document
counters, `error_code`, `activated_at`, `retire_after`.
`vector_index_generation_documents` (`generation_id` CASCADE, `organization_id`,
`document_id` CASCADE, `point_count`, `indexed_at`; unique `(generation_id, document_id)`)
records which documents a generation holds.

### 0.6.0 columns on existing tables (migration 20261128_0002)

All additive and nullable, or `NOT NULL DEFAULT 0`:

| Table | Columns | Used by |
|---|---|---|
| `document_chunks` | `organization_id uuid`, `fts_config varchar(32)`, `fts_vector tsvector` (PostgreSQL only); on the ORM model since B1 (`fts_vector` deferred) | B1 |
| `connector_sync_runs` | `checkpoint_cursor json`, `checkpoint_at`, `heartbeat_at`, `lease_owner varchar(255)`, `pages_committed int default 0` | D1 |
| `connector_sync_jobs` | `next_run_at timestamptz` | D1 |
| `external_items` | `last_seen_sync_run_id uuid` (no foreign key) | D1 |
| `agent_runs` | `lease_owner`, `lease_expires_at`, `request_snapshot json`, `resume_count int default 0` | C2 |

Migration `20261128_0003` builds `idx_chunks_org_document (organization_id, document_id)`,
GIN `idx_chunks_fts_vector (fts_vector)`, `idx_outbox_pending`, `idx_connector_sync_jobs_due
(status, next_run_at)`, `idx_agent_runs_lease (status, lease_expires_at)`, and the non-unique
`idx_agent_tool_calls_run_idem (agent_run_id, idempotency_key_hash)` with
`CREATE INDEX CONCURRENTLY`.

### chat_sessions

```sql
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    user_id UUID NOT NULL REFERENCES users(id),
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### chat_messages

```sql
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY,
    chat_session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    confidence_score DOUBLE PRECISION,
    latency_ms INTEGER,
    model_name TEXT,
    token_input_count INTEGER,
    token_output_count INTEGER,
    cost_usd NUMERIC(12, 6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### citations

```sql
CREATE TABLE citations (
    id UUID PRIMARY KEY,
    chat_message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id),
    chunk_id UUID NOT NULL REFERENCES document_chunks(id),
    page_number INTEGER,
    text_snippet TEXT NOT NULL,
    similarity_score DOUBLE PRECISION,
    rerank_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Evaluation tables

### evaluation_sets

```sql
CREATE TABLE evaluation_sets (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### evaluation_questions

```sql
CREATE TABLE evaluation_questions (
    id UUID PRIMARY KEY,
    evaluation_set_id UUID NOT NULL REFERENCES evaluation_sets(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    expected_answer TEXT,
    expected_document_id UUID REFERENCES documents(id),
    expected_page_number INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### evaluation_runs

```sql
CREATE TABLE evaluation_runs (
    id UUID PRIMARY KEY,
    evaluation_set_id UUID NOT NULL REFERENCES evaluation_sets(id),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    config JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### evaluation_results

```sql
CREATE TABLE evaluation_results (
    id UUID PRIMARY KEY,
    evaluation_run_id UUID NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    evaluation_question_id UUID NOT NULL REFERENCES evaluation_questions(id),
    generated_answer TEXT,
    retrieval_score DOUBLE PRECISION,
    faithfulness_score DOUBLE PRECISION,
    citation_accuracy_score DOUBLE PRECISION,
    answer_relevance_score DOUBLE PRECISION,
    latency_ms INTEGER,
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Pipeline observability tables

### pipeline_runs

```sql
CREATE TABLE pipeline_runs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    pipeline_type TEXT NOT NULL CHECK (
        pipeline_type IN ('document.process', 'document.reindex', 'document.delete', 'chat.query', 'evaluation.run')
    ),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER CHECK (duration_ms >= 0),
    inputs JSONB NOT NULL DEFAULT '{}',
    outputs JSONB NOT NULL DEFAULT '{}',
    config JSONB NOT NULL DEFAULT '{}',
    logs JSONB NOT NULL DEFAULT '[]',
    error_message TEXT,
    error_details JSONB NOT NULL DEFAULT '{}',
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    chat_message_id UUID REFERENCES chat_messages(id) ON DELETE SET NULL,
    evaluation_run_id UUID REFERENCES evaluation_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### pipeline_events

```sql
CREATE TABLE pipeline_events (
    id UUID PRIMARY KEY,
    pipeline_run_id UUID NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    node_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed', 'skipped')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER CHECK (duration_ms >= 0),
    inputs JSONB NOT NULL DEFAULT '{}',
    outputs JSONB NOT NULL DEFAULT '{}',
    config JSONB NOT NULL DEFAULT '{}',
    logs JSONB NOT NULL DEFAULT '[]',
    error_message TEXT,
    error_details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (pipeline_run_id, sequence)
);
```

## Additional production tables

### usage_events

Track cost, tokens, and feature usage.

```sql
CREATE TABLE usage_events (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    user_id UUID REFERENCES users(id),
    event_type TEXT NOT NULL,
    model_name TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd NUMERIC(12, 6),
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### audit_logs

```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    user_id UUID REFERENCES users(id),
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 0.9.0 tables

Migrations `20261129_0001` to `20261129_0003` (0.9.0, S1) add the schema the account,
MFA, and billing work packages build on. Everything is additive: new, empty tables, nullable
columns, and one `NOT NULL` column with a constant default. Nothing in the 0.9.0 foundation
reads or writes them on a request path yet; A1, A2, A3, B1, and B2 do.

| Table | Purpose | RLS class |
|---|---|---|
| `auth_one_time_tokens` | Single-use tokens: email verification, password reset, MFA challenge and enrolment, step-up, SAML request and assertion ids. Only `token_hash` (SHA-256 hex, unique) is stored; `purpose` CHECK; `user_id`, `organization_id` (both nullable, CASCADE), `session_id`, `expires_at`, `consumed_at`, `attempt_count`/`max_attempts`, `created_ip`, `metadata` (never secrets or email text). Purged daily by `auth.tokens.purge_expired` once unusable for `AUTH_ONE_TIME_TOKEN_RETENTION_HOURS` (24). | lookup (read before a tenant is bound) |
| `user_mfa_factors` | One row per MFA enrolment (`factor_type` `totp`, `status` `pending` or `active`); the secret is encrypted (`encrypted_secret`, `secret_key_id`, `secret_algorithm`); `last_used_step` blocks code reuse. Partial unique index: one `active` factor per user and type. | none (no `organization_id`; a factor protects the user everywhere) |
| `user_mfa_recovery_codes` | Keyed hashes (`code_hash`, unique) of single-use recovery codes (`used_at`), per factor. | none (no `organization_id`) |
| `org_login_policies` | One row per organisation: `mfa_required` (false), `mfa_grace_period_days` (7, CHECK 0 to 90), `mfa_required_since`, `updated_by_id`. No row keeps today's behaviour. | lookup (read at login) |
| `billing_plans` | Global plan catalogue: `plan_key` (unique), display name and order, `quota_limits` and `stage_limits` (same shapes as `org_quota_policy`), `provider_prices` (`{"stripe": {"month": "price_x"}}`), `display_prices` (`{"month": {"amount_minor": 2900, "currency": "usd"}}`). | none (no `organization_id`) |
| `billing_customers` | Provider customer per organisation (unique `organization_id`; unique `(provider, provider_customer_id)`). | lookup (webhooks) |
| `billing_subscriptions` | Provider subscription per organisation: `plan_key`, `status` CHECK (Stripe's eight states), interval and period, `cancel_at_period_end`, `grace_until`, `last_event_created_at` (older events are ignored), `last_synced_at`. Unique `(provider, provider_subscription_id)`. | lookup (webhooks) |
| `billing_invoices` | Invoices copied from provider events: number, status, currency, `amount_due_minor`/`amount_paid_minor`, hosted and PDF URLs, period, `issued_at`. Unique `(provider, provider_invoice_id)`; index `(organization_id, issued_at)`. | strict |
| `billing_webhook_events` | One row per provider event (unique `(provider, event_id)`, the deduplication key): type, `event_created_at`, `organization_id` (SET NULL), `status` CHECK (`received`, `processed`, `ignored`, `failed`), `error_code`, `payload_sha256` (never the payload). | lookup (webhooks) |

Columns on existing tables:

| Table | Column | Notes |
|---|---|---|
| `users` | `email_verified_at timestamptz` | NULL: mailbox not proven. Nothing enforces it by default. |
| `auth_refresh_sessions` | `auth_method varchar(16) NOT NULL DEFAULT 'password'` (CHECK `password`, `sso`), `mfa_verified_at timestamptz` | Constant default: metadata only on PostgreSQL 11+; the CHECK is added `NOT VALID` (enforced on every write, not validated in the migration: see below). |
| `org_quota_policy` | `stage_limits json` | NULL means every optional pipeline stage is allowed (the behaviour before 0.9.0). |
| `email_delivery_logs`, `user_notification_preferences` | `event_type` CHECK | Now the full `EmailEventType` list: adds `email_verification`, `password_reset`, and `onboarding_reminder` (in the model since F353, never migrated). Added `NOT VALID` (enforced on every write, not validated in the migration: see below). |

The RLS lists are `RLS_LOOKUP_TABLES_0_9_0` and `RLS_STRICT_TABLES_0_9_0` in
`backend/app/db/rls.py`; the migrations copy them as literals and
`tests/test_rls_coverage.py` checks both. `deploy/sql/force_rls.sql` includes the new policy
tables. Every new foreign key has an index (`tests/test_fk_index_guard.py`).

The two CHECK constraints on large existing tables (`auth_refresh_sessions.auth_method`,
`email_delivery_logs.event_type`, and the `user_notification_preferences` list with it) stay
`NOT VALID` (`pg_constraint.convalidated = false`). Alembic runs the upgrade in one
transaction, so a `VALIDATE CONSTRAINT` there would scan the table while the `ACCESS
EXCLUSIVE` lock of the `ADD COLUMN` or `ADD CONSTRAINT` is still held. No existing row can
violate them (a new column with a constant default; a widened list), and PostgreSQL enforces
a `NOT VALID` CHECK on every insert and update. A later migration may validate them inside
an autocommit block (docs/CONTRIBUTING.md, "Database migrations").

Rollback: `alembic downgrade 20261128_0003` drops the nine tables, the four columns, and the
policies, and puts back the previous `event_type` lists (`NOT VALID`, so rows with the new
event types do not block it). It loses every outstanding token, every MFA enrolment and
recovery code, every organisation login policy, all billing state (the provider keeps the
subscriptions), and every plan stage limit. Run it only before any production use of these
features. `tests/test_migrations_0_9_0_pg.py` runs upgrade, downgrade, and upgrade again.

## Recommended indexes

```sql
CREATE INDEX idx_documents_org_status ON documents(organization_id, status);
CREATE INDEX idx_documents_uploaded_by ON documents(uploaded_by_user_id);
CREATE INDEX idx_chunks_document_id ON document_chunks(document_id);
CREATE INDEX idx_chunks_qdrant_point_id ON document_chunks(qdrant_point_id);
CREATE INDEX idx_chat_sessions_user ON chat_sessions(user_id, created_at DESC);
CREATE INDEX idx_chat_messages_session ON chat_messages(chat_session_id, created_at);
CREATE INDEX idx_citations_message ON citations(chat_message_id);
CREATE INDEX idx_eval_runs_set ON evaluation_runs(evaluation_set_id, created_at DESC);
CREATE INDEX idx_pipeline_runs_org_created ON pipeline_runs(organization_id, created_at DESC);
CREATE INDEX idx_pipeline_events_run_sequence ON pipeline_events(pipeline_run_id, sequence);
CREATE INDEX idx_usage_org_created ON usage_events(organization_id, created_at DESC);
```

### Hot-path and foreign-key indexes (0.4.0, R04-02)

Revisions `20261127_0001`, `20261127_0002`, and `20261127_0003` add these indexes. Each one
has a matching `Index(...)` entry (same name, column order, and direction) in the model's
`__table_args__`.

```sql
-- 20261127_0001
CREATE INDEX idx_chat_sessions_org_created ON chat_sessions(organization_id, created_at DESC);
CREATE INDEX idx_chat_sessions_org_user_updated
    ON chat_sessions(organization_id, user_id, updated_at DESC, id DESC);  -- session list sort
CREATE INDEX idx_activity_timeline_events_org_created
    ON activity_timeline_events(organization_id, created_at DESC);
CREATE INDEX idx_chat_shares_org_created ON chat_shares(organization_id, created_at DESC);
CREATE INDEX idx_notifications_org_created ON notifications(organization_id, created_at DESC);
CREATE INDEX idx_citations_document ON citations(document_id);
CREATE INDEX idx_citations_chunk ON citations(chunk_id);
-- 20261127_0002
CREATE INDEX idx_documents_org_created
    ON documents(organization_id, created_at DESC, id DESC);  -- default document list sort
CREATE INDEX idx_external_items_connection ON external_items(connection_id);
CREATE INDEX idx_source_documents_document ON source_documents(document_id);
CREATE INDEX idx_evaluation_results_question ON evaluation_results(evaluation_question_id);
CREATE INDEX idx_webhook_deliveries_webhook_created
    ON webhook_deliveries(webhook_id, created_at DESC);
CREATE INDEX idx_webhook_deliveries_org_created ON webhook_deliveries(organization_id, created_at);
-- 20261127_0003
CREATE INDEX idx_organization_members_user ON organization_members(user_id);
CREATE INDEX idx_usage_events_user_created ON usage_events(user_id, created_at);
CREATE INDEX idx_audit_logs_user_created ON audit_logs(user_id, created_at);
```

Not added because an index already leads with the column: `citations(chat_message_id)`
(`idx_citations_message`) and `connector_sync_runs(connection_id)`
(`idx_connector_sync_runs_connection_status`).

**Building and rolling back.** On PostgreSQL the migrations build each index with
`CREATE INDEX CONCURRENTLY ... IF NOT EXISTS` inside an autocommit block, with
`statement_timeout = 0` and `lock_timeout = '10s'`, so reads and writes continue during the
build. A failed concurrent build leaves an `INVALID` index; rerunning the upgrade drops an
index of the same name only when `pg_index.indisvalid` is false and builds it again, and it
never rebuilds a valid index. Downgrade drops the indexes with `DROP INDEX CONCURRENTLY IF
EXISTS`. The migrations change no data, and old application code does not depend on the
indexes, so an application rollback without a schema downgrade is safe. Because the build
runs outside a transaction, run these upgrades on their own rather than with other
migrations in a single maintenance window that expects all-or-nothing behaviour.

**Foreign-key index guard.** `backend/tests/test_fk_index_guard.py` fails when a
single-column foreign key is not the leading column of a non-partial index, unique
constraint, or primary key. The foreign keys that were unindexed at 0.4.0 are listed in
`backend/tests/fixtures/fk_index_exemptions.txt`; the list may only shrink (a stale entry
also fails). A new foreign key needs an index, or an exemption line with a justification.
The SQLite test checks the model metadata; a PostgreSQL twin (`requires_postgres`) reads
`pg_constraint` and `pg_index` from the migrated schema, so drift between models and
migrations also fails. Known drift at 0.4.0 is tagged in the file: `@db-only` for
`authorization_conflicts.grant_id`, `deny_id`, and `decision_log_id` (foreign keys only in
the migrations) and `@model-only` for `org_model_provider_change_log.org_model_provider_settings_id`
(declared by the model, not created by any migration).

**Query plans.** `backend/tests/test_query_plans_pg.py` runs `EXPLAIN (FORMAT JSON)` for ten
hot queries (document list, session list, message list, citations by message IDs,
notification list, audit and usage ranges, memberships by user, API key by hash, auth
session by ID) under `SET LOCAL enable_seqscan = off` and fails on a `Seq Scan` of the
target table. The test tables are empty, so this shows each index is usable for the query
shape, not that the planner picks it on production data.

## Row-level security

PostgreSQL row-level security is defense in depth under the application's own
`organization_id` filters (`R04-08`). Migration `20261127_0004` puts one policy,
`tenant_isolation_policy`, on the tables with an `organization_id` column (87 of 90; the
three identity tables below get none). The lists live in `backend/app/db/rls.py`;
`tests/test_rls_coverage.py` fails when a new tenant table is in no list or when the
migration's literal copy differs.

| List | Tables | Unset tenant (`app.current_organization_id` empty) | Bound tenant |
|---|---|---|---|
| `RLS_STRICT_TABLES` | 72 frozen in `RLS_STRICT_TABLES_0_4_0` plus `RLS_STRICT_TABLES_0_6_0` (`document_processing_stages`, `document_stage_artifacts`, migration `20261128_0001`; `outbox_messages`, `vector_index_generation_documents`, migration `20261128_0002`): everything not listed below | all rows, unless `app.rls_mode = 'strict'`: then no rows and no writes | own rows only |
| `RLS_LOOKUP_TABLES` | 15: `api_keys`, `service_accounts`, `service_account_tokens`, `organization_invitations`, `chat_shares`, `answer_shares`, `agent_trace_share_tokens`, `org_sso_configs`, `org_domain_verifications`, `org_scim_configs`, `bot_installations`, `bot_user_mappings`, `connector_oauth_states`, `incidents`, `incident_notes` | all rows (needed before the tenant is known: credential and token lookups, SSO/SCIM discovery, OAuth state, bot inbound, public status) | own rows only |
| `RLS_IDENTITY_TABLES` | 3: `users`, `organization_members`, `auth_refresh_sessions` | no policy, RLS stays disabled | all rows: one user spans organizations, so a request bound to organization B must still read the user (home organization A), list every membership (workspace switcher), and revoke the user's sessions in every organization (logout-all, password change) |

Both conditions apply to `USING` and `WITH CHECK`, so a bound tenant cannot insert or move
a row into another organization. The two settings are transaction-local
(`set_config(..., true)`); the application sets them in one statement per transaction
(marked `/* rudix:session-context */`). See `docs/22_AUTHORIZATION_SYSTEM.md` section 11
for the modes and the roles.

Notes:

- Policies do not apply to the table owner, to superusers, or to roles with `BYPASSRLS`.
  `FORCE ROW LEVEL SECURITY` is not used before `0.5.0`, so isolation takes effect only
  when the application connects as the non-owner `rudix_app` role
  (`deploy/sql/provision_roles.sql`).
- `chat_messages`, `citations`, and `document_pages` have no `organization_id` and are
  not covered; they are reached through covered parent rows. `document_chunks` has the
  column since `0.6.0` but no policy until the backfill and
  `deploy/sql/document_chunks_not_null.sql` (`RLS_PENDING_TABLES`).
- The policy keeps index use: under the policy the document list still uses
  `idx_documents_org_created` (`tests/test_rls_enforcement_pg.py`).
- Migration safety: `ENABLE ROW LEVEL SECURITY` and `CREATE POLICY` take a brief ACCESS
  EXCLUSIVE lock per table and rewrite nothing. The migration sets `lock_timeout = '5s'`
  and fails instead of queueing behind long transactions; run it at low traffic and rerun
  on a lock timeout. Downgrade to `20261127_0003` restores the 12-table policy of
  `20260715_0001` and disables RLS on the other tables.

## Retention and partitioning

`R04-09` adds two things: retention by batched delete for five append-only tables, and
tooling for monthly range partitions. No table is partitioned in `0.4.0`.

### Retention by batched delete

| Table | Setting (days, unset = keep) | Floor |
|---|---|---|
| `usage_events` | `RETENTION_USAGE_EVENTS_DAYS` | 7 |
| `audit_logs` | `RETENTION_AUDIT_LOGS_DAYS`, overridden per organisation by `organization_governance_policies.audit_log_retention_days` | 30 |
| `authorization_decision_logs` | `RETENTION_AUTHORIZATION_DECISION_LOGS_DAYS` | 7 |
| `activity_timeline_events` | `RETENTION_ACTIVITY_TIMELINE_EVENTS_DAYS` | 7 |
| `webhook_deliveries` | `RETENTION_WEBHOOK_DELIVERIES_DAYS` | 7 |

Every default is "keep". Usage events feed quotas and invoices, so set their window only
after billing exports cover the deleted period.

The beat task `maintenance.retention.purge` runs daily at 03:15 UTC on a maintenance
session (`DATABASE_MAINTENANCE_URL` when set). For each table with a window, it walks every
organisation and repeats
`DELETE FROM t WHERE id IN (SELECT id FROM t WHERE organization_id = :org AND created_at < :cutoff ORDER BY created_at LIMIT :batch)`,
committing after each batch. Each batch walks the table's `(organization_id, created_at)`
index.

- `RETENTION_DELETE_BATCH_SIZE` (default 5000, 100..50000) sets the batch size.
- `RETENTION_MAX_BATCHES_PER_RUN` (default 200) caps the non-empty batches per table per
  run. The next run continues where this one stopped.
- `RETENTION_ENABLED=false` stops every delete.

The audit window for an organisation is its override when set, and otherwise the platform
default. The override is set through `PATCH /admin/governance` (30..3650 days, `null`
clears it), and migration `20261127_0005` enforces the floor with
`ck_organization_governance_policies_audit_retention_min`. A rerun with nothing to delete
is a no-op. `authorization_conflicts.decision_log_id` references
`authorization_decision_logs` with `ON DELETE SET NULL`, so purging a decision log clears
that link and keeps the conflict.

### Partition tooling

Partitions follow these conventions:

- A partition is named `<table>_pYYYYMM` and holds `[YYYY-MM-01 00:00 UTC, next month)`.
- There is no default partition, so a row dated in a month without a partition is
  rejected.
- The helpers in `backend/app/db/partitioning.py` act only on tables listed in
  `pg_partitioned_table`.

The beat task `maintenance.partitions.ensure` runs daily at 03:45 UTC. For each retention
table that is already partitioned, it:

- creates this month's and next month's partitions;
- detaches and drops partitions whose upper bound is past the retention window, using plain
  `DETACH` and `DROP` in one short transaction with `lock_timeout` (`DETACH ... CONCURRENTLY`
  cannot run in a transaction block);
- sets `rudix_partition_missing{table}`.

For audit logs, a partition is dropped only past the longest window of any organisation,
and never while the platform default is "keep". Today no table is partitioned, so the task
does nothing.

### Converting a table (deferred, rehearsal required)

Converting the five tables is deferred. None of them is new, and all of them hold
production data. A conversion copies every row and needs these things first:

- a rehearsal on a staging copy at production volume, to measure backfill time and the
  length of the swap lock;
- a maintenance window for the swap, which holds `ACCESS EXCLUSIVE` on the table while it
  copies the delta and counts rows;
- a primary key of `(id, created_at)`, because PostgreSQL requires the partition key in
  every unique constraint. Unique indexes without `created_at` cannot be copied, and no
  foreign key can reference the table by `id` alone. For example,
  `authorization_conflicts.decision_log_id` blocks `authorization_decision_logs` until that
  foreign key is dropped.

The procedure uses `backend/scripts/partition_table.py`. It is never applied
automatically, and each subcommand that changes data accepts `--dry-run`, which prints the
SQL. The connection comes from `DATABASE_MIGRATION_URL`, or `DATABASE_URL` when that is
not set.

1. Set `RETENTION_ENABLED=false` for the whole conversion. Rows deleted after the backfill
   copied them make the swap's count check fail.
2. Run `plan <table>`. It shows the row estimate, the `created_at` range, the partitions,
   the copied and skipped indexes, the policies, and any blockers.
3. Run `create-shadow <table>`. It creates `<table>_partitioned` with the same columns,
   defaults, checks, outbound foreign keys, indexes, RLS policies and grants, the primary
   key `(id, created_at)`, and monthly partitions from the oldest row through next month.
   It also builds `(created_at, id)` on the source table concurrently, as the backfill
   cursor.
4. Run `backfill <table> --batch-size 5000`. It copies rows in `(created_at, id)` order,
   commits each batch, and uses `ON CONFLICT DO NOTHING`. It can be interrupted and resumes
   from the newest row already in the shadow.
5. Run `verify <table>`. It compares per-month row counts and checksums of the source table
   and the shadow.
6. In the window, run `swap <table> --lock-timeout 5s`. This is one transaction. It locks
   both tables, then:
   - copies new rows;
   - copies rows whose `updated_at` is at or after the shadow's creation time minus one
     hour;
   - checks that the row counts are equal;
   - renames `<table>` to `<table>_legacy_<yyyymm>` and the shadow to `<table>`;
   - moves the index and constraint names.
7. Run `verify <table> --against <table>_legacy_<yyyymm>`. Then re-run
   `deploy/sql/provision_roles.sql`, which is idempotent, and set `RETENTION_ENABLED` back.
8. Keep the legacy table for one release, then drop it. Rollback before that is a rename in
   the other direction. Rows written after the swap exist only in the new table and have to
   be copied back.

`tests/test_partitioning_pg.py` runs this procedure on a scratch table,
`rudix_partition_probe`, shaped like `usage_events`. It checks:

- that an interrupted backfill resumes to an exact copy;
- that the swap carries rows inserted and updated after the backfill;
- that `verify` matches;
- that a one-month range query scans one partition in `EXPLAIN`;
- that `ensure` creates next month and flips the gauge;
- that `drop_expired_partitions` removes old months;
- that `ensure` does nothing on the unpartitioned application tables.

## Qdrant payload schema

Qdrant payload should duplicate important metadata for fast filtering.

```json
{
  "organization_id": "uuid",
  "user_id": "uuid",
  "document_id": "uuid",
  "chunk_id": "uuid",
  "filename": "employee_policy.pdf",
  "file_type": "pdf",
  "page_number": 4,
  "chunk_index": 12,
  "text": "Employees are entitled to...",
  "embedding_model": "text-embedding-3-small",
  "index_version": "v1",
  "created_at": "2026-05-07T10:00:00Z"
}
```
