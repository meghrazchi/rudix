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

### Vector writes and memory

R06-02, R06-06, R06-07.

**Temporary files.** The `extract` stage streams the stored object to a temporary file in
`INGEST_TEMP_DIR` (unset: the system temporary directory) with reads of
`INGEST_DOWNLOAD_CHUNK_BYTES` (1 MiB) and removes it when the stage ends, also on failure.
Size the directory for the largest accepted upload (`MAX_UPLOAD_SIZE_MB`) times the number of
ingestion tasks that run at once on the host (worker concurrency of the processing queue), plus
headroom; use local disk, not a network mount. A full disk fails the stage as transient
`SOURCE_OBJECT_READ_FAILED` (log `Ingestion temporary file write failed`). Leftover
`rudix-ingest-*` files after a hard kill (SIGKILL, OOM) can be deleted when no worker runs.

**Memory.** PDF pages are extracted one at a time from the file and written to the stage
artifacts as they are produced; TXT is decoded in `INGEST_TEXT_SEGMENT_CHARS` sections. Text
blocks are read through `get_text("dict")` because PyMuPDF 1.28's `get_text("blocks")` keeps
the objects it returns alive (`tests/test_ingestion_memory_bounds.py` checks both the bound
and that the blocks are identical). `INGEST_MEMORY_CEILING_MB` (512) is the documented design
bound for one extract run; it is not enforced. `clean_detect`, `dlp`, and `chunk` still hold
the text of every page, and DOCX is still loaded whole, so the upload limit stays the bound for
those.

**Reuse and cleanup.** `embed` reuses stored vectors by `(organization_id, embedding_model,
chunk_hash)` and marks every point with `ingest_run_id`; `index` deletes the document's points of
other runs and requires the point count to match the embeddable chunks. A
`QDRANT_POINT_COUNT_MISMATCH` failure is transient: the retry resumes at `index`; if it
persists, check for concurrent writers of the same document or a partially applied delete,
then reindex the document. Reuse needs the `chunk_hash` payload index, which
`python -m app.clients.qdrant_bootstrap` adds to an existing collection.

**Qdrant clients and bootstrap.** Writes use `AsyncQdrantClient` with
`QDRANT_WRITE_TIMEOUT_SECONDS` (30), chat retrieval one with `QDRANT_SEARCH_TIMEOUT_SECONDS`
(unset: `QDRANT_TIMEOUT_SECONDS`, 2 s). `ensure_qdrant_collection()` runs at API startup, at
worker process start (both gated by `QDRANT_BOOTSTRAP_COLLECTION`), and in the deploy step
`python -m app.clients.qdrant_bootstrap` (`make migrate-qdrant`), not on the write path. A write
that gets 404 for the configured collection bootstraps it once and retries
(`qdrant.collection.missing_on_write`).

**Settings to evaluate on staging before changing.** Every tuning setting defaults to unset
(the server default) and applies only when a collection is created; an existing collection
only logs `qdrant.collection.tuning_differs`. Change them only after the accuracy gate
(`make eval-smoke`, the nightly suite, `docs/12`) passes on a staging collection built with the
new values, and compare recall and latency there:

| Setting | What to evaluate |
|---|---|
| `QDRANT_HNSW_M`, `QDRANT_HNSW_EF_CONSTRUCT` | Graph density and build effort; recall against index size and build time. |
| `QDRANT_HNSW_M=0` with `QDRANT_HNSW_PAYLOAD_M` (e.g. 16) | Tenant-partitioned HNSW from Qdrant's multitenancy guide: per-tenant graphs on the `organization_id` tenant index instead of one global graph. Every Rudix search filters by organisation; measure recall for small and large tenants. |
| `QDRANT_SCALAR_QUANTIZATION`, `QDRANT_QUANTIZATION_QUANTILE`, `QDRANT_QUANTIZATION_ALWAYS_RAM` | int8 vectors (about 4x less vector memory); recall loss and rescoring cost. |
| `QDRANT_VECTORS_ON_DISK`, `QDRANT_HNSW_ON_DISK`, `QDRANT_ON_DISK_PAYLOAD` | RAM against latency. qdrant-client 1.20 marks the `on_disk` flags deprecated in favour of `memory`; the server image is not pinned (`qdrant/qdrant:latest`), so check them against the deployed server version. |
| `QDRANT_SHARD_NUMBER`, `QDRANT_REPLICATION_FACTOR` | Only for a Qdrant cluster; a single node keeps 1. |
| `QDRANT_STORE_PARENT_TEXT=false` | Smaller payloads; chat retrieval then reads parent text from `document_chunks` in one query per search. Measure retrieval latency first. Points written while it is false have no parent text: setting it back to true needs a reindex of those documents. Evaluation and safety scoring use the payload only. |

Applying a new value to an existing deployment means building a new collection (reindex)
with it; 0.6.0 package A2 adds index generations for that.

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
