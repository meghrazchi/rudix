# Ingestion and Workers Runbook

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Review
- `Last Updated`: 2026-11-27
- `Related Docs`: [03_RAG_WORKFLOW.md](./03_RAG_WORKFLOW.md),
  [11_SECURITY_AND_PRODUCTION_CHECKLIST.md](./11_SECURITY_AND_PRODUCTION_CHECKLIST.md),
  [12_EVALUATION_AND_MONITORING.md](./12_EVALUATION_AND_MONITORING.md),
  [06_DATABASE_SCHEMA.md](./06_DATABASE_SCHEMA.md),
  [roadmap/V0_6_0_IMPLEMENTATION_PLAN.md](./roadmap/V0_6_0_IMPLEMENTATION_PLAN.md)

## 1. Purpose

How document ingestion runs on the Celery workers in `0.6.0`, and what an operator does when
a run stalls, fails, or is dispatched twice. Later `0.6.0` work packages append their own
section here.

## 2. Scope

In scope: the staged ingestion chain (R06-01), run identity and resume, the reaper, the
transactional outbox for request-path dispatch, failed stage retries, and tenant binding of
Celery tasks. Out of scope: vector index generations (A2), worker pools and dead-letter
queues (C1), agent runs (C2), connector sync (D1).

## 3. Assumptions and Constraints

- RabbitMQ with `task_acks_late` and `task_reject_on_worker_lost`: a message whose worker dies
  is delivered again with the same task id and kwargs.
- One dev `worker` consumes every queue in `task_queues`; production pools come with C1.
- `INGEST_PIPELINE_MODE=inline` is kept for one milestone and then removed.

## 4. Design or Procedure

### Stages and queues

`INGEST_PIPELINE_MODE=chain` (default) runs each stage as its own task:

| Task | Queue setting (default) |
|---|---|
| `documents.ingest.extract`, `.clean_detect`, `.dlp`, `.chunk` | `CELERY_QUEUE_DOCUMENTS_PROCESSING` (`documents.processing`) |
| `documents.ingest.embed`, `.index`, `.finalize` | `CELERY_QUEUE_DOCUMENTS_EMBEDDING` (`documents.processing`) |
| `documents.graph_extract` | `CELERY_QUEUE_DOCUMENTS_GRAPH` (`documents.graph`) |

`documents.process` (and `documents.reindex`) claim the document exactly as before, choose the
run, and dispatch the first stage that is not completed. Each stage task:

1. checks the document belongs to its `organization_id` kwarg (else `tenant_mismatch`);
2. returns `superseded` when `documents.processing_task_id` is no longer its `claim_token`;
3. on a completed stage row, dispatches the next stage again (idempotent) and returns;
4. leases its row in `document_processing_stages` with its own message id (a live lease of
   another message returns `lease_held`), runs, marks the row completed, and publishes the
   next stage **before** it returns, so the broker keeps the message until the hand-off is out.

`finalize` is the only writer of `indexed` and of the embedding usage event; its task then
writes the completion audit and notification once, and dispatches `documents.graph_extract`.
`INGEST_PIPELINE_MODE=inline` runs the same stages in the claiming task.

### Resume and reaper

- A fresh claim starts a run whose id is derived from the document and the claiming task id,
  so a redelivered `documents.process` reaches the same run, not a second chain.
- A redelivered stage message continues its stage (completed embed batches are skipped).
- Each stage start, and every `INGEST_HEARTBEAT_EVERY_PARTS` artifact parts or embed batches,
  refreshes `documents.processing_started_at` while the run holds the claim.
- `documents.reap_stale` releases documents silent for `DOCUMENT_PROCESSING_STALE_SECONDS` and
  re-queues `documents.process` with `resume_run_id` = the latest unfinished run, so the run
  continues after its last completed stage (extraction and OCR are not redone). A stage row
  still `running` is taken over once its heartbeat is older than `INGEST_STAGE_LEASE_SECONDS`.
- `documents.stage_artifacts.purge` (daily, 04:05 UTC) deletes artifacts older than
  `INGEST_STAGE_ARTIFACT_TTL_HOURS` (72) of documents that are not processing.

### Outbox

Upload, delete, retry-delete, reindex, graph reindex, and OCR retry write their task as an
`outbox_messages` row in the transaction of the document change, then publish it right after
commit. When the broker is down the response is unchanged (`deferred` or `503`) and the row
stays `pending`; `outbox.relay` (every `OUTBOX_RELAY_INTERVAL_SECONDS`, batches of
`OUTBOX_RELAY_BATCH_SIZE`, `FOR UPDATE SKIP LOCKED`) publishes it with backoff and marks it
`failed` after `OUTBOX_MAX_ATTEMPTS`. The relay claims its batch in a short transaction
(attempts counted, `available_at` moved forward by a 300-second claim lease), publishes with
no transaction open, then records the outcomes in a second short transaction, so a slow or
unreachable broker never holds row locks that a request or another relay would wait on; a
relay that dies mid-batch releases its rows after the lease. A reindex whose publication
failed restores the previous status and cancels its row (`last_error = cancelled`). Publishing a row twice is harmless:
the second `documents.process` finds the claim held and skips.

```sql
-- Pending and failed dispatches by task.
SELECT task_name, status, count(*), min(created_at)
FROM outbox_messages WHERE status <> 'published' GROUP BY 1, 2;
```

### Failed stage retry

A stage task that fails for good records a `FailedJob` with `task_name = documents.process`
(`documents.reindex` for reindex runs) and `metadata = {"stage", "run_id"}`. The failed-job
dashboard retry sends `documents.process` with `job_id`; the task reads the run id from the job
and resumes that run at the failed stage. Retryable failures keep their artifacts for that
retry (the purge removes them after the TTL); permanent ones (DLP block, validation) drop them.
A `documents.graph_extract` infrastructure failure records `documents.graph_reindex`.

### Tenant binding

`RudixTask.__call__` binds `tenant_context_scope(organization_id)` for the task, and
`on_failure` binds it again for the `FailedJob` write and the terminal-failure hook, so strict
row-level security applies to worker writes. Document tasks and stage tasks compare the
document's organisation with the kwarg before any write and raise `tenant_mismatch` (no
`FailedJob`, no status change; counted in `rudix_worker_tenant_mismatch_total`). A
`documents.process` message without `organization_id` (published before `0.6.0`) resolves it
with one `maintenance_session()` read. Beat tasks use `maintenance_session()`.

## Failure Modes and Recovery

| Symptom | Cause | Recovery |
|---|---|---|
| Document `processing` for long, stage rows `running` with an old heartbeat | Worker died; message lost or broker restarted | Wait for `documents.reap_stale`; it re-queues with `resume_run_id`. Check `document.processing.reaped` logs. |
| Stage task logs `ingestion.stage_task.lease_held` repeatedly | Another delivery holds a fresh lease (duplicate message) | None: the live delivery finishes the stage. If its worker died, the lease expires after `INGEST_STAGE_LEASE_SECONDS`. |
| `ingestion.stage_task.superseded` | A newer claim (reindex, force, reaper) owns the document | None: the newer run continues. |
| `ingestion.stage.dispatch_failed` | Broker unavailable during a hand-off | The current stage message is retried; its stage is completed, so the retry only publishes the next stage. |
| Rows `pending` in `outbox_messages` | Broker outage at request time | `outbox.relay` publishes them; check `rudix_outbox_messages_total{outcome="relayed"}`. |
| Rows `failed` in `outbox_messages` (not `cancelled`) | Broker down for `OUTBOX_MAX_ATTEMPTS` relay attempts | Fix the broker, then `UPDATE outbox_messages SET status='pending', attempts=0, available_at=now() WHERE status='failed' AND last_error <> 'cancelled';` |
| `graph_extraction_status = failed`, document `indexed` | Graph extraction failed (strict modes included) | `POST /api/v1/documents/{id}/graph/reindex`. |
| `task.tenant_mismatch` warning | A message named another organisation than the document's | Investigate the publisher; nothing was written. |
| `FailedJob` for `documents.process` with `metadata.stage` | Stage failed after retries | Dashboard retry resumes the run at that stage. |

Rollback: set `INGEST_PIPELINE_MODE=inline` to run all stages in one task (in-flight stage
messages still finish). Drain the outbox before downgrading migration `20261128_0002`.

## 6. Security Considerations

- Stage artifacts are copies of document text: they are deleted when a run finishes, when a
  permanent failure ends it, by the TTL purge, and with the document.
- Outbox kwargs hold ids, flags, and the chunking profile only; `last_error` stores the
  exception class name, never broker URLs or messages.
- Worker logs carry document, organisation, and run ids, never document text.

## Chunk tenant backfill and NOT NULL

`0.6.0` (R06-09) gives `document_chunks` a tenant column (`organization_id`) and a
language-aware full-text vector (`fts_config`, `fts_vector`). The chunk stage writes them
for every new chunk. Rows written before `0.6.0` stay NULL until the backfill. Until the
operator step below, the table has no RLS policy (`RLS_PENDING_TABLES`), and the ORM
tenant guard does not filter it, so unbackfilled rows stay visible.

1. Point `DATABASE_MAINTENANCE_URL` at the `BYPASSRLS` role (`rudix_maintenance`), so
   documents are visible under strict RLS.
2. Run the backfill, either as a task or synchronously:
   - task: `celery -A app.workers.celery_app call documents.chunks.backfill_tenant`
     (reindex queue). It runs up to 20 batches, then re-enqueues itself with its cursor;
   - script: `cd backend && .venv/bin/python scripts/backfill_chunk_tenant.py`
     (`--dry-run` prints `remaining=N` and changes nothing; `--batch-size`, `--cursor`,
     `--max-batches`). It prints one line per batch.

   Each batch updates `CHUNK_BACKFILL_BATCH_SIZE` rows (default 1000) by primary-key
   order in its own short transaction, with `SET LOCAL lock_timeout`
   (`CHUNK_BACKFILL_LOCK_TIMEOUT_MS`, default 2000) and `statement_timeout`
   (`CHUNK_BACKFILL_STATEMENT_TIMEOUT_MS`, default 30000). It only touches rows whose
   `organization_id` is NULL, so a rerun is a no-op on finished rows. A lock or statement
   timeout retries the task from the same cursor. Progress:
   `rudix_chunk_backfill_rows_total` and `documents.chunks.backfill_tenant.progress` logs.
3. When `scripts/backfill_chunk_tenant.py --dry-run` prints `remaining=0`, apply the
   operator SQL. Run it without `psql -1`, because each step must commit on its own:

   ```bash
   psql "$DATABASE_MIGRATION_URL_PSQL" -v ON_ERROR_STOP=1 -f deploy/sql/document_chunks_not_null.sql
   ```

   It refuses to run while any NULL remains. It then adds
   `CHECK (organization_id IS NOT NULL) NOT VALID` and validates it (the scan does not
   block reads or writes). Next it sets `NOT NULL`, which uses the validated check instead
   of a second scan, and drops the check. Last, it enables RLS with the strict tenant
   policy. Each statement waits at most 5 s for its lock, and the script is safe to
   rerun. If `deploy/sql/force_rls.sql` is already applied, also run
   `ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;`.
4. Set `KEYWORD_SEARCH_TENANT_COLUMN=on` (or leave `auto`: it switches once a process
   finds no NULL row).

Rollback: `deploy/sql/document_chunks_not_null_revert.sql` (drops the policy, disables
RLS, drops `NOT NULL`). Set `KEYWORD_SEARCH_TENANT_COLUMN=auto` or `off` first. The
columns themselves are additive (migration `20261128_0002`) and need no rollback.
Both SQL files are generated by `backend/scripts/render_chunk_not_null_sql.py`; check them
with `--check`.

## Keyword search settings

| Setting | Default | Effect |
|---|---|---|
| `KEYWORD_SEARCH_MULTILINGUAL` | `false` | `true` also matches `fts_vector` with the question's text search configuration (German, Spanish, French, English; others `simple`). The English column stays a second match, so no previous result is lost. |
| `KEYWORD_SEARCH_TENANT_COLUMN` | `auto` | `on`: scope by `document_chunks.organization_id` (index `idx_chunks_org_document`). `off`: scope by the owning document, as before. `auto`: `on` once no NULL row remains, checked once per process. Use `on` only after the backfill. |
| `KEYWORD_SEARCH_CANDIDATE_LIMIT` | `1000` | Matches ranked per search (the first ones in index scan order). `0` ranks every match. |

Staging step, after the backfill and the NOT NULL step: turn on
`FEATURE_ENABLE_HYBRID_RETRIEVAL`, `FEATURE_ENABLE_CONTEXT_PACKING` and
`KEYWORD_SEARCH_MULTILINGUAL`. Then run the live accuracy gate
(`ci/scripts/accuracy_eval_runner.py`, nightly `accuracy-eval.yml`) before and after the
change, and keep them on only if the gate passes. The defaults stay off in `0.6.0`. The
deterministic accuracy smoke (`pytest -m accuracy_smoke`) already passes with all three
on. Run the keyword p95 load check as the table grows (R03-09) on staging, with
`KEYWORD_SEARCH_CANDIDATE_LIMIT` at its default.

Graph writes (R06-10): `GRAPH_WRITE_BATCH_SIZE` (default 200) sets the rows per Neo4j write
transaction. `ENTITY_EXTRACTION_MAX_CONCURRENT_BATCHES` and
`RELATION_EXTRACTION_MAX_CONCURRENT_BATCHES` (default 1) set the LLM batches in flight
per document. Watch `rudix_graph_write_batches_total{outcome="failed"}`. Run graph
extraction once against a real Neo4j instance on staging before you raise the
concurrency.
