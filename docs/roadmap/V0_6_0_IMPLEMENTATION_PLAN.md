# v0.6.0 — Detailed Implementation Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Planned
- `Last Updated`: 2026-11-27
- `Related Docs`: [V0_6_0_INGESTION_AND_WORKERS.md](./V0_6_0_INGESTION_AND_WORKERS.md),
  [V0_5_0_IMPLEMENTATION_PLAN.md](./V0_5_0_IMPLEMENTATION_PLAN.md),
  [V0_4_0_IMPLEMENTATION_PLAN.md](./V0_4_0_IMPLEMENTATION_PLAN.md),
  [01_EXECUTION_PLAN.md](./01_EXECUTION_PLAN.md), [../03_RAG_WORKFLOW.md](../03_RAG_WORKFLOW.md),
  [../16_CONNECTOR_PLATFORM.md](../16_CONNECTOR_PLATFORM.md),
  [../21_ENTERPRISE_GRAPH_EXTRACTION.md](../21_ENTERPRISE_GRAPH_EXTRACTION.md),
  [../13_AGENTIC_ARCHITECTURE_AND_CAPABILITY_MODEL.md](../13_AGENTIC_ARCHITECTURE_AND_CAPABILITY_MODEL.md)

## 1. Purpose

Turn the `0.6.0` spec into nine work packages with exact files, symbols, tests, and owners of
shared files. Every reference was read on `develop` at `51f61d2f` (`0.2.0` to `0.5.0` merged,
not tagged). Line numbers drift; search for the quoted symbol.

Evidence rule: no RabbitMQ, Redis, Qdrant, MinIO, Neo4j, or load test runs here. Claims rest on
call-count assertions (provider embedding calls, Qdrant and Neo4j round trips, SQL statements),
kill-and-redeliver tests that run task bodies twice with the existing fakes, `tracemalloc`
bounds on synthetic files, and configuration that parses (`docker compose config`). No
throughput or latency figure is written down.

## 2. Plan check: what the code confirmed or changed

| Item | Result |
|---|---|
| R06-01 | **Changed.** `app/workers/document_tasks.py` is 3,261 lines. `_extract_and_store_document_pages_async` (lines 620–1831, about 1,210 lines) holds one `SessionLocal()` session open across MinIO, OCR, graph extraction, embedding, and Qdrant calls. Graph extraction runs inline after chunking and before embedding; with `ENTITY_EXTRACTION_STRICT_MODE` a graph failure fails the document. Evaluation re-ingest calls the same coroutine with `persist_document_state=False`. Seven test files rebind about 20 module globals (`SessionLocal`, `_qdrant_service`, `_embedding_service`, `_chunking_service`, `_graph_service`, `claim_document_for_processing`, `set_document_status`, `mark_document_failed`, `log_document_event`, `_record_worker_audit`, `_run`, ...). The reaper re-queues `documents.process` without kwargs, so a reaped run restarts from scratch. **Resolution:** compatibility facade (contract 4.2.2); stages in `app/workers/ingestion/`; spec columns `(document_id, attempt, stage, ...)` become `run_id` plus an `attempt` counter, lease owner, and heartbeat; text artifacts live in Postgres (`document_stage_artifacts`), not MinIO. S1 keeps graph timing and strict-mode semantics; S2 moves graph to its own task as the spec says. |
| 0.4.0/0.5.0 deferrals | Tenant binding in Celery tasks: S2 (tasks bind from their `organization_id` kwarg; `_persist_failed_job` and terminal-failure hooks bind too). Outbox: S2, for upload, reindex, delete, backfill, connector-created documents (D1), and agent resume (C2). **Changed:** there is no webhook event dispatch in the code (only the admin test delivery in `admin_webhooks.py`), so a webhook outbox has nothing to carry and is deferred. `AsyncQdrantClient`: A1. `organization_id` on `document_chunks`: B1 (column added by S2). RLS for `chat_messages`, `citations`, `document_pages`: still deferred (no column). |
| RLS lists | **Changed.** `tests/test_rls_coverage.py` asserts that migration `20261127_0004` literals equal `RLS_STRICT_TABLES`. New tables go into `RLS_STRICT_TABLES_0_6_0`, appended to the frozen base. A tenant column on `DocumentChunk` would make the ORM guard filter unbackfilled rows and require a policy, so B1 adds `RLS_PENDING_TABLES = ("document_chunks",)` and a guard exemption until the operator `NOT NULL` step. |
| R06-02 | Confirmed: `_read_object_bytes` calls `body.read()`; every extractor takes `bytes` (`fitz.open(stream=...)`); `EmbeddingService.embed_chunks` keeps every vector of a document in one dict. DOCX (`python-docx`) cannot stream and stays bounded by the upload limit. |
| R06-03 | Confirmed: no `soft_time_limit`, `time_limit`, `worker_max_tasks_per_child`, or `worker_max_memory_per_child`. The consumer acknowledgement timeout is RabbitMQ server configuration (`consumer_timeout`), not a Celery setting. `SoftTimeLimitExceeded` is not in `autoretry_for`, so it reaches `on_failure` and `FailedJob` with `error_code="SoftTimeLimitExceeded"`. |
| R06-04 | Confirmed: one `worker` service with no `-Q`, so it consumes every queue in `task_queues`. Compose cannot read app settings; pools are started by `python -m app.workers.pools <name>`, which builds the Celery argv from settings. |
| R06-05 | **Changed.** All queues are classic. Redeclaring an existing queue as quorum fails with `PRECONDITION_FAILED`, so quorum is opt-in with new queue names and a drain runbook. Dead-lettered messages are Celery task messages; a normal worker on the dead-letter queue would execute them, so a consumer bootstep writes `FailedJob` instead. Queue depth and oldest-message age need the broker API: a passive-declare depth sample and a queue-wait histogram from a publish timestamp header stand in. |
| R06-06 | **Changed.** No second copy of vectors: the cache is the vector index. Before embedding a batch, existing points are looked up by `(organization_id, embedding_model, chunk_hash)` in the collection being written (one scroll per batch, new `chunk_hash` payload index). Deletion cascade is the existing point deletion. This needs the per-document point cleanup to move from "delete before chunking" to "delete stale points after upsert" (by an `ingest_run_id` payload marker). |
| R06-07 | **Changed.** `ensure_qdrant_collection()` runs on every upsert and delete (collection check, `get_collection`, four `create_payload_index`). Compose pins no Qdrant server (`qdrant/qdrant:latest`); only `qdrant-client==1.20.0` is pinned, so settings are checked against its models (`HnswConfigDiff.m/ef_construct/payload_m/on_disk`, `ScalarQuantizationConfig.type/quantile/always_ram`, `KeywordIndexParams.is_tenant`, already used for `organization_id`). `search` no longer exists in 1.20; retrieval already uses `query_points`. Parent text is read from the payload by vector retrieval and by a join in keyword retrieval; storing it stays the default until staging measures the change. |
| R06-08 | **Changed.** `QDRANT_COLLECTION` is a real collection, and an alias cannot share a collection's name, so a new alias setting is added and an adoption step points it at the existing collection. There is no platform-admin role: build, swap, and rollback are operator commands; the admin endpoint is read-only and shows the caller's organisation only. |
| R06-09 | **Changed.** `text_search_vector` is a generated column fixed to `'english'`; changing the expression rewrites the table. New nullable `fts_config` and `fts_vector` are written by the chunk stage and the backfill. The accuracy gates (F302 runner, F149) need a live API, so `hybrid_retrieval` and `context_packing` stay off by default; the accuracy smoke runs with both on, and the flip is a staging step. |
| R06-10 | Confirmed: one Neo4j transaction per entity, alias, evidence link, and relation. Entity resolution reads stay per entity (the spec counts writes). |
| R06-11 | **Changed.** `sync_engine.py` is 1,779 lines. A whole run is one transaction (`session.begin()` in `connector_sync_tasks.py`); full-sync tombstoning uses an in-memory set of seen IDs; the due check is Python over `schedule_json` plus one query per job; a rate limit fails the run. **Resolution:** `checkpoint_cursor`, `heartbeat_at`, `lease_owner`, and `pages_committed` on runs, `next_run_at` on jobs, `last_seen_sync_run_id` on items (S2 schema). |
| R06-12 | Confirmed: `evaluation_tasks.py` is 1,838 lines; re-ingest writes eval vectors into the production collection and chunks into `document_chunks` under `eval-` versions. Only vectors move (the spec's scope); eval chunks keep their cleanup. |
| R06-13 | **Changed.** `POST /agents/runs` runs `AgentRuntime.execute` in the request. Approval does not continue a run (clients resubmit with `approval_ids`). Tool calls store `idempotency_key_hash` without uniqueness. The frontend already polls and renders `queued`. Execution moves behind `AGENT_RUN_EXECUTION=inline|worker` (default `inline`). |

## 3. Sequence

| Chain | Order | Task | Items | Model | Review |
|---|---|---|---|---|---|
| S | 1 | S1 | R06-01 part 1: stage modules, stage table, artifacts, inline runner, facade, deletion of artifacts | opus | api |
| S | 2 | S2 | R06-01 part 2: one task per stage, leases, reaper resume, graph task, tenant binding, outbox, 0.6.0 schema | opus | api |
| A | 1 | A1 | R06-02 bounded memory, R06-06 embedding reuse, R06-07 Qdrant client and tuning | opus | api |
| A | 2 | A2 | R06-08 index generations, aliases, zero-downtime reindex, admin progress | opus | api |
| A | 3 | A3 | R06-12 evaluation collection, bounded concurrency, `evaluation_tasks.py` split | opus | api |
| B | 1 | B1 | R06-09 chunk tenant column and multilingual FTS, R06-10 batched graph writes | opus | api |
| C | 1 | C1 | R06-03 task limits, R06-04 worker pools, R06-05 dead-letter queues, queue metrics | opus | api |
| C | 2 | C2 | R06-13 agent runs in workers, stream endpoint, `runtime.py` split | opus | api |
| D | 1 | D1 | R06-11 connector sync at tenant scale, `sync_engine.py` split | opus | api |

S runs first, one package at a time; A, B, C, and D start after S2 is merged. Migrations are
linear and only in S: `20261128_0001` (S1, `down_revision = "20261127_0005"`), `20261128_0002`
and `20261128_0003` (S2). A–D add no migration. If one is unavoidable it goes into chain B as
`20261129_0001` with `down_revision = "20261128_0003"`; any other package stops and reports.

## 4. Shared files and contracts

### 4.1 Owners and anchors

Every task re-reads a shared file before editing it, edits only its anchor with `Edit`, never
rewrites a shared file whole, and re-reads after a failed `Edit`. S1 and S2 create the marker
comments named below (`# anchor: <task>`); a later task inserts directly after its marker.

| File | Task: anchor |
|---|---|
| `app/workers/document_tasks.py` (facade) | S1, S2 only. Later tasks never edit it. |
| `app/workers/ingestion/stages/extract.py`, `embed.py`, `index.py` | S, then chain A only. |
| `app/workers/ingestion/stages/chunk.py` | S; A1 removes the block between `# anchor: A1 index cleanup begin/end`; B1 edits `_chunk_row_values()` only. |
| `app/workers/ingestion/stages/graph_extract.py` | S; then B1. |
| `app/workers/ingestion/options.py` (`IngestionOptions`) | S; A3 only sets `vector_collection` from evaluation code, never edits the file. |
| `app/workers/celery_app.py` | S2 restructures into `INCLUDE`, `TASK_ROUTES`, `BEAT_SCHEDULE` with markers `# anchor: A2`, `# anchor: A3`, `# anchor: B1`, `# anchor: C1`, `# anchor: C2`, `# anchor: D1` in each. C1 owns `celery_app.conf.update` keys other than routes and beat, and moves queue declarations to `app/workers/queues.py`. |
| `app/workers/base_task.py` | S2, then C1 only. |
| `app/workers/document_reaper_tasks.py` | S2 only. |
| `app/core/settings/workers.py` (S1 creates, composed into `Settings` by S1) | Fields after `# anchor: S2`, `# anchor: A1`, `# anchor: A2`, `# anchor: A3`, `# anchor: B1`, `# anchor: C1`, `# anchor: C2`, `# anchor: D1`. `app/core/config.py` is edited by S1 only. |
| `app/core/metrics_workers.py` (S1 creates; same `registry` as `app/core/metrics.py`) | Metrics after the same per-task markers. `app/core/metrics.py` (776 lines) is not edited. |
| `.env.example` | S1 adds a `# --- Ingestion and workers (0.6.0) ---` block with one comment marker per task. |
| `app/db/rls.py`, `deploy/sql/force_rls.sql`, `unforce_rls.sql` | S1, S2 (`RLS_STRICT_TABLES_0_6_0`), B1 (`RLS_PENDING_TABLES`). Regenerate the SQL with `scripts/render_force_rls_sql.py`. |
| `app/db/tenant_context.py` | S2 (worker binding helper), B1 (`_PENDING_TENANT_MODEL_NAMES`). |
| `app/domains/documents/services/qdrant_service.py`, `app/clients/qdrant_client.py`, `app/clients/factory.py` (Qdrant part), `app/domains/chat/services/query_retrieval_service.py` | Chain A only. |
| `app/domains/chat/services/parallel_retrieval_optimizer.py` | A1: the vector branch (`asyncio.to_thread(` in `_run_query`). B1: the two `search_chunks(` calls in `_keyword_search` and the `execute()` signature (`query_language`). |
| `app/domains/chat/services/keyword_retrieval_service.py` | B1 only. |
| `app/domains/graph/**` | B1 only. |
| `app/domains/connectors/**`, `app/workers/connector_sync_tasks.py` | D1 only. |
| `app/domains/agents/**`, `app/interfaces/http/agent_runs.py`, `app/workers/agent_tasks.py` | C2 only. |
| `app/workers/evaluation_tasks.py`, `evaluation_index_cleanup.py`, `app/domains/evaluations/services/eval_index_purge_service.py` | A3 only. |
| `app/application/outbox.py` (S2) | Callers only; the API is contract 4.2.5. |
| `docker-compose.yml`, `deploy/compose/*.yml` | C1 only. Staging and production files need image variables and `deploy/compose/.env`, so C1 adds `deploy/scripts/check_compose_config.sh`, which validates every file from a temporary copy with placeholder values. |
| `frontend/openapi.json`, `frontend/src/lib/api/generated/*` | Regenerated with `npm run api:update-schema` by A2, C2, D1 after API changes. On conflict regenerate; never hand-merge. |
| `docs/27_INGESTION_AND_WORKERS_RUNBOOK.md` (S2 creates) | One `##` section per task, appended in merge order. |
| `docs/03_RAG_WORKFLOW.md` | S1, S2: `### Steps` and the Mermaid diagram under `## Ingestion pipeline`; S2: `## Graph lifecycle`; A1: `## Embedding strategy`; A2: new `### Vector index generations` after `### Index version filter`; B1: `### Retrieval guidance` under `## Multilingual behavior`; A3: `## Evaluation pipeline`. |
| `docs/07_API_DESIGN.md` | A2: new `### GET /admin/vector-index/status`; C2: the agent run and stream sections; D1: connector sync run fields. |
| `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` | S1: `## Data deletion`; S2, C1: `### Workers`; C2: `## Agent tool security`; B1: `### Database`. |
| `docs/12_EVALUATION_AND_MONITORING.md` | One `###` subsection per task, inserted before `## Continuous evaluation`. |
| `backend/README.md` | S1 adds `## Ingestion pipeline` before `## Application cache`; others add bullets at its end. C1, S2, C2, D1 also update `## Scheduled tasks (Celery beat)`. |
| `docs/CHANGELOG.md` | One line per task under `[Unreleased]` `### Added`, directly after the line starting "- `docs/roadmap/V0_6_0_IMPLEMENTATION_PLAN.md`". |

### 4.2 Contracts between chains

1. **Databases and worktrees.** Branch `feat/v0.6.0-<task>` in worktree `../rudix-v060-<task>`
   cut from the current `develop`; `cd backend && make install`. Each chain uses its own
   database (`rudix_test_s`, `_a`, `_b`, `_c`, `_d`) on `127.0.0.1:55432`, created with the
   snippet in the `0.4.0` plan section 4.2 item 1; S2 also uses `rudix_test_migrations` for
   the downgrade round trip. Restore `frontend/AGENTS.md` and `frontend/tsconfig.json` with
   `git checkout --` before each commit after any Next.js command.
2. **Facade (`document_tasks.py`, S1 defines, `tests/test_document_tasks_compat.py` checks).**
   Task names and signatures unchanged (`documents.process`, `.reindex`, `.delete`,
   `.graph_reindex`, `.backfill`). Rebindable globals read at call time through
   `app/workers/ingestion/deps.py::current_deps()`: `SessionLocal`, `_document_repository`,
   `_qdrant_service`, `_embedding_service`, `_chunking_service`, `_graph_service`,
   `_entity_extraction_service`, `_relation_extraction_service`, `_usage_repository`,
   `claim_document_for_processing`, `set_document_status`, `mark_document_failed`,
   `get_document_status`, `log_document_event`, `log_chunking_event`, `_record_worker_audit`,
   `_record_worker_audit_async`, `_update_document_graph_status_async`,
   `_run_document_graph_extraction_async`, `_reindex_document_graph_async`, `_run`.
   Kept callables: `_extract_and_store_document_pages_async` (same signature and return
   value, used by evaluation), `_delete_document_assets_async`, `_backfill_dispatch_async`,
   `_make_chunking_service`, `DocumentPipelinePermanentError`, `DocumentPipelineTransientError`.
   The seven test files above are not edited by S except import paths and `patch` targets,
   each listed in the merge request; no assertion changes, except where S2 changes
   behaviour on purpose (graph failure no longer fails the document), listed with the reason.
3. **Stage contract (S1).** `StageName` = `extract, clean_detect, dlp, chunk, embed, index,
   finalize` plus `graph_extract`. Each stage is `async def run(ctx: StageContext) ->
   StageOutcome` in its own module, opens its own short sessions, holds no session across a
   provider, OCR, MinIO, Neo4j, or Qdrant call, and is a no-op when its row is `completed`.
   Rows: `document_processing_stages(document_id, run_id, stage)` unique; a lease is a
   conditional `UPDATE ... RETURNING` (pending, failed, or running with the same owner or a
   heartbeat older than `INGEST_STAGE_LEASE_SECONDS`). Artifacts:
   `document_stage_artifacts(document_id, run_id, stage, part)` unique, zlib-compressed JSON,
   one part per page (extract, clean) or per batch (embed). `finalize` is the only writer of
   `indexed` and the usage event, in one transaction with its own stage row. A missing
   artifact re-runs the stage that produces it. `StageStore` has a DB and an in-memory
   implementation; evaluation re-ingest uses the in-memory one.
4. **Run identity (S2).** `run_id` (artifact namespace) and `claim_token` (the
   `documents.processing_task_id` holding the claim) travel in every stage task's kwargs with
   `document_id` and `organization_id`. A stage task whose `claim_token` no longer matches
   returns `superseded`. A fresh upload, reindex, or `force` starts a new `run_id`; Celery
   redelivery, `self.retry`, and a reaper re-queue (`resume_run_id`) continue the run.
   Handoff goes through `app/workers/ingestion/dispatch.py::dispatch_stage()` (the task
   object's `apply_async`, never `send_task`), so `task_always_eager` runs a whole chain in
   tests; a publish failure raises `TransientTaskError` so the current message is retried.
5. **Outbox (S2 defines).** `await outbox.enqueue(session, *, organization_id, task_name,
   kwargs, queue, dedupe_key)` inside the caller's transaction; `outbox.publish_after_commit
   (session)` tries immediate publication; the `outbox.relay` beat task publishes the rest
   with `FOR UPDATE SKIP LOCKED` through `maintenance_session()`. Consumers stay idempotent.
6. **Vector collections (S1 seam, A owns).** `QdrantService` methods take an optional
   `collection_name`; `None` means the active write targets from `resolve_write_targets()`
   (S1: `[settings.qdrant_collection]`; A2: the active generation plus a building one).
   Payload fields are additive: A1 adds `ingest_run_id`.
7. **Worker tenant binding (S2 defines).** `RudixTask.__call__` binds
   `tenant_context_scope(organization_id)` from kwargs; a task whose entity belongs to another
   organisation raises `PermanentTaskError("tenant_mismatch")` before any write. Beat tasks use
   `maintenance_session()`.
8. **Queues (S2 names, C1 declares).** Settings `CELERY_QUEUE_DOCUMENTS_GRAPH`
   (`documents.graph`), `CELERY_QUEUE_DOCUMENTS_EMBEDDING` (default
   `documents.processing`), `CELERY_QUEUE_AGENTS` (C2, default `default`). Every new queue is
   added to `task_queues` so the single dev worker keeps consuming everything.

## 5. Steps per item

### R06-01 part 1 — Stages, inline runner, facade (S1)

1. First commit, before any code moves: behaviour fixtures recorded through the current code
   with the existing fakes, for upload, reindex, OCR, DLP warn and quarantine, hierarchical
   and table chunks, connector references, graph strict and lenient, and evaluation
   re-ingest: the final document row, chunk rows, fake Qdrant points, usage events, audit
   actions, and pipeline-explorer events, as JSON in `tests/fixtures/ingestion_golden/`
   (`INGESTION_GOLDEN_UPDATE=1` rewrites; UUIDs and timestamps normalised).
2. Models `DocumentProcessingStage`, `DocumentStageArtifact` (`app/models/document_processing.py`)
   and migration `20261128_0001` with strict RLS policies, `ON DELETE CASCADE` to documents.
3. `app/workers/ingestion/`: `context.py`, `deps.py`, `options.py`, `store.py`, `runner.py`
   (inline: stages in order, skip completed), `recorder.py` (`PipelineRunRecorder`),
   `errors.py`, `storage.py` (MinIO reads), `graph.py`, `deletion.py`, `reindex.py`,
   `backfill.py`, and `stages/<name>.py`. Every file under 500 lines.
4. Embed stage per batch (ordered chunk rows, `EMBEDDING_BATCH_MAX_ITEMS`): embed, upsert,
   record the batch part with token counts; no vectors kept after the upsert. Index stage:
   connector chunk references. Finalize: embedding metadata, status `indexed`, usage event
   (token sums from batch parts), purge of this run's artifacts and older runs' rows.
5. `run_id` is the claim's task id (redelivery and `self.retry` resume; reaper re-queues
   start fresh until S2). Document deletion deletes stage rows and artifacts.
6. Metric `rudix_ingest_stage_seconds{stage,outcome}`. Docs: backend README, docs/03, 06, 11.

### R06-01 part 2 and deferrals — Distributed stages (S2)

1. Migrations `20261128_0002` (outbox and the 0.6.0 schema below) and `20261128_0003`
   (indexes built concurrently, the `20261127_0002` pattern). Schema: `outbox_messages`;
   `vector_index_generations`, `vector_index_generation_documents`; `document_chunks`
   `organization_id uuid`, `fts_config varchar(32)`, `fts_vector tsvector` (all nullable, no
   model attribute until B1); `connector_sync_runs` `checkpoint_cursor`, `checkpoint_at`,
   `heartbeat_at`, `lease_owner`, `pages_committed int default 0`; `connector_sync_jobs`
   `next_run_at`; `external_items.last_seen_sync_run_id`; `agent_runs` `lease_owner`,
   `lease_expires_at`, `request_snapshot`, `resume_count int default 0`. Indexes:
   `(organization_id, document_id)` and GIN `fts_vector` on chunks, outbox `(status,
   available_at)`, jobs `(status, next_run_at)`, runs `(status, lease_expires_at)`, tool calls
   `(agent_run_id, idempotency_key_hash)`. `lock_timeout` on every `ALTER`. S2 adds models
   for the three new tables and attributes for the new columns, except on `DocumentChunk`;
   new tenant tables go into `RLS_STRICT_TABLES_0_6_0` with strict policies.
2. Tasks `documents.ingest.<stage>` and `documents.graph_extract` in
   `app/workers/ingestion/tasks.py`; `documents.process` claims and dispatches the first
   incomplete stage; each stage publishes the next before returning (acks-late keeps the
   message until then). `INGEST_PIPELINE_MODE=chain|inline` (default `chain`; `inline` kept
   one milestone).
3. Heartbeats refresh `processing_started_at` per stage and every
   `INGEST_HEARTBEAT_EVERY_PARTS`; the reaper passes `resume_run_id`. Graph after finalize on
   its own queue; graph failure sets `graph_extraction_status=failed`, never `failed` on the
   document. Failed stage tasks record `FailedJob.task_name="documents.process"` with
   `metadata.stage` and `run_id`, so dashboard retry resumes.
4. Tenant binding (4.2.7), outbox (4.2.5) for every request-path dispatch in
   `application/documents/workflows.py`, `interfaces/http/documents.py`,
   `admin_documents.py`; `documents.stage_artifacts.purge` beat task
   (`INGEST_STAGE_ARTIFACT_TTL_HOURS`, 72).
5. Runbook `docs/27_INGESTION_AND_WORKERS_RUNBOOK.md` and its `docs/README.md` entry.

### R06-02, R06-06, R06-07 — Vector write path (A1)

Stream the object to a temporary file (`INGEST_TEMP_DIR`, chunked copy, `body.read(n)`),
extract PDFs page by page from the file path (extractors accept `bytes | Path`, additive),
write one artifact part per page, OCR per page; TXT in segments; DOCX unchanged. Reuse
before embedding (the R06-06 row in section 2), concurrent batches
(`EMBEDDING_MAX_CONCURRENT_BATCHES`, default 1) with a shared pause on
`ProviderQuotaExceededError`, `rudix_embedding_cache_hits_total`.
`AsyncQdrantClient` from `app/clients/factory.py` with `QDRANT_SEARCH_TIMEOUT_SECONDS`
(= old 2 s) and `QDRANT_WRITE_TIMEOUT_SECONDS` (30); `ensure_qdrant_collection` at API and
worker startup and in `make migrate`; tuning settings default `None` (server defaults) and
apply only when a collection is created; `QDRANT_STORE_PARENT_TEXT=true` with a Postgres
resolver used when the payload lacks parent text.

### R06-08 — Index generations and zero-downtime reindex (A2)

`QDRANT_COLLECTION_ALIAS` (unset = legacy direct collection). `scripts/vector_index.py
adopt|plan|build|status|swap|rollback|drop-retired`; `vector_index.build` task (resumable per
document, `vector_index_generation_documents`), dual writes and deletes during a build, count
verification, one `update_collection_aliases` call per swap, `QDRANT_RETIRED_GRACE_HOURS`.
Query embedding model follows the active generation. A changed model or dimension at startup
registers a `building` generation and logs instead of raising. `GET /admin/vector-index/status`
(owner, admin; own organisation only), `AdminVectorIndexPage`, `rudix_reindex_progress`.

### R06-12 — Evaluation isolation (A3)

`QDRANT_EVALUATION_COLLECTION` (unset = current behaviour); eval re-ingest, retrieval, and
cleanup use it; document deletion also deletes the document's eval points; bounded
per-question concurrency (`EVALUATION_MAX_CONCURRENT_QUESTIONS`, default 1); split into
`app/workers/evaluation/` by run type with `evaluation_tasks.py` as a facade.

### R06-09, R06-10 — Keyword search and graph writes (B1)

Chunk stage writes `organization_id`, `fts_config` (from the document language: `en`
english, `de` german, `es` spanish, `fr` french, else `simple`), and `fts_vector`;
`documents.chunks.backfill_tenant` task in batches by primary key with a resumable cursor;
keyword search filters on the chunk's `organization_id` when the backfill is complete
(`KEYWORD_SEARCH_TENANT_COLUMN=auto|on|off`), queries `fts_vector` with the question's
configuration (`KEYWORD_SEARCH_MULTILINGUAL`, default `false`), and ranks at most
`KEYWORD_SEARCH_CANDIDATE_LIMIT` matches. Operator SQL `deploy/sql/document_chunks_not_null.sql`.
Graph: `UNWIND` batch methods, one write transaction per batch
(`GRAPH_WRITE_BATCH_SIZE`), concurrent extraction batches
(`ENTITY_EXTRACTION_MAX_CONCURRENT_BATCHES`, default 1).

### R06-03, R06-04, R06-05 — Worker platform (C1)

Per-task limits via `task_annotations` from `CELERY_TASK_TIME_LIMITS` (soft and hard per task
name, with a default), `worker_max_tasks_per_child`, `worker_max_memory_per_child`,
`CELERY_BROKER_CONSUMER_TIMEOUT_SECONDS` checked against every hard limit at worker start,
`error_code="task_soft_time_limit"` in `FailedJob`. Pools `ingest`, `graph`, `sync`, `eval`,
`default` (`WORKER_POOL_<NAME>_QUEUES`, `_CONCURRENCY`, `_POOL`) started by `python -m
app.workers.pools <name>`; staging and production compose run five services; dev keeps
`worker` and adds the pools under profile `pools`. `CELERY_QUEUE_TYPE=classic|quorum`
(default `classic`), `CELERY_DELIVERY_LIMIT`, dead-letter exchange `rudix.dlx` and queue
`rudix.dead_letter`, consumer bootstep writing idempotent `FailedJob` rows,
`rudix_celery_queue_depth{queue}`, `rudix_celery_queue_wait_seconds{queue}`, alerts.

### R06-13 — Agent runs in workers (C2)

`AGENT_RUN_EXECUTION=inline|worker` (default `inline`). Worker mode: the API stores the run
(`queued`, `request_snapshot`) and an outbox row, returns `201` at once; `agents.run.execute`
takes a lease, rebuilds the principal from the database (current roles, membership,
organisation), resumes after the last completed step, reuses completed tool calls with the
same idempotency key, and persists state after every step; approval writes an outbox row for
`agents.run.resume`; `agents.runs.reap` re-queues expired leases. `GET
/agents/runs/{run_id}/stream` is SSE with the 0.5.0 framing, Redis buffer and pub/sub, and a
database polling fallback. `runtime.py` split under 500 lines; MCP exposure unchanged.

### R06-11 — Connector sync at tenant scale (D1)

One transaction per page (items, seen markers, checkpoint, counters, heartbeat, outbox rows
for created documents); cancel checks every `CONNECTOR_SYNC_CANCEL_CHECK_ITEMS`; resume from
`checkpoint_cursor`; tombstones by `last_seen_sync_run_id`; due jobs in one `FOR UPDATE SKIP
LOCKED` query on `next_run_at`; caps `CONNECTOR_SYNC_MAX_CONCURRENT_PER_ORG` and
`_PER_CONNECTION` (0 = off); `Retry-After` honoured inside the run up to
`CONNECTOR_SYNC_MAX_INLINE_BACKOFF_SECONDS`, else checkpoint and re-queue with a countdown;
`sync_engine.py` split into planner, fetcher, differ, writer behind `ConnectorSyncEngine`.

## 6. Deferred

- Cross-encoder reranker: not approved; not planned.
- Pinning the Qdrant server image (compose uses `latest`): owner decision on the version
  staging runs; until then tuning is checked against `qdrant-client` 1.20.0 only.
- Defaults that change recall or latency, each after staging evidence and the accuracy gate:
  `hybrid_retrieval` and `context_packing` on, `KEYWORD_SEARCH_MULTILINGUAL=true`, Qdrant HNSW,
  tenant partitioning and quantization, `QDRANT_STORE_PARENT_TEXT=false`, embedding and
  extraction concurrency above 1, connector concurrency caps, `AGENT_RUN_EXECUTION=worker`.
- `NOT NULL` and an RLS policy on `document_chunks.organization_id` (operator step after the
  backfill); RLS for `chat_messages`, `citations`, `document_pages`.
- Webhook event outbox: no webhook event dispatch exists yet.
- Frontend SSE consumer for agent runs (`R07-07`).
- Quorum queue cut-over on staging and production (operator, runbook in docs/27).

## 7. Verification for the release

```bash
cd backend && make check-revisions && make lint && make test && make test-cov
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://rudix:rudix@127.0.0.1:55432/rudix_test make test-postgres
cd backend && DATABASE_URL=<rudix_test_migrations url> .venv/bin/alembic downgrade 20261127_0005 \
  && DATABASE_URL=<same> .venv/bin/alembic upgrade head
cd backend && .venv/bin/pytest -m "isolation or guardrails or accuracy_smoke" tests/test_ingestion_resume.py
cd backend && .venv/bin/python scripts/export_openapi.py --check ../frontend/openapi.json
cd backend && .venv/bin/python scripts/render_force_rls_sql.py --check
deploy/scripts/check_compose_config.sh   # C1: every compose file, placeholder images, temp env
cd frontend && npm run typecheck && npm run lint && npm run test:coverage && npm run build
cd frontend && npm run test:e2e
wc -l backend/app/workers/*.py backend/app/workers/*/*.py backend/app/workers/*/*/*.py
```

Coverage stays at or above the ratchets (backend 79.7; frontend lines 65.8, statements 64.9,
functions 58.8, branches 58.2). `alembic heads` reports `20261128_0003`. No module under
`backend/app/workers/` exceeds 500 lines.

## 8. Manual steps (staging and production)

1. Chaos test per pool: kill `worker-ingest` during `embed`, `worker-graph`, `worker-sync`
   during a page, `worker-eval`, and `worker-default` during an agent step; everything
   completes, nothing duplicates (chunks, points, usage events, tool calls).
2. RabbitMQ: set `consumer_timeout`, cut over to quorum queues by the runbook, send a poison
   message and confirm it reaches `FailedJob` after `CELERY_DELIVERY_LIMIT`.
3. Memory: ingest a 500 MB PDF and confirm worker peak memory stays under the ceiling and
   `worker_max_memory_per_child` recycles.
4. Qdrant: adopt the alias, run a model change end to end (build, verify, swap) under chat
   load with no failed queries, roll back once, and drop the retired collection after the
   grace period; run the accuracy gate before and after any tuning default.
5. Run `documents.chunks.backfill_tenant` to completion, then
   `deploy/sql/document_chunks_not_null.sql`; set `KEYWORD_SEARCH_TENANT_COLUMN=on`.
6. Load test (`R03-09`): ingestion p95 for the reference document, keyword p95 as the table
   grows, upload latency while an evaluation fills `evaluations`.
7. Neo4j: graph extraction with batched writes on a real instance; connector 100,000-item
   sync cancel and resume against a provider sandbox; agent approval resume across a worker
   restart with real Redis.

## 9. Change Notes

- 2026-11-27: Initial version, written after checking the `0.6.0` spec against the code at
  `51f61d2f`.
