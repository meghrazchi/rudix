# v0.6.0 — Ingestion and Workers

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../03_RAG_WORKFLOW.md](../03_RAG_WORKFLOW.md),
  [../16_CONNECTOR_PLATFORM.md](../16_CONNECTOR_PLATFORM.md),
  [../21_ENTERPRISE_GRAPH_EXTRACTION.md](../21_ENTERPRISE_GRAPH_EXTRACTION.md)

## 1. Purpose

Make background work resumable, isolated, and bounded: staged ingestion that does not redo
finished stages, a worker pool per workload, a tuned and migratable vector index, and
connector, evaluation, and agent work that cannot starve user uploads.

## 2. Work items

### R06-01 — Staged, resumable ingestion (L)

- **Problem:** One 1,500-line coroutine performs every stage in one DB session. Any retry
  repeats OCR and embedding.
- **Change:** Split `document_tasks.py` into a chain of tasks, one module each under
  `app/workers/ingestion/`:
  `extract -> clean_detect -> dlp -> chunk -> embed -> index -> finalize`, then
  `graph_extract` as a separate task on its own queue.
  - New table `document_processing_stages(document_id, attempt, stage, status, started_at,
    finished_at, artifact_ref, error_code)`.
  - Each stage writes its output to an artifact (extracted pages and chunks in Postgres or
    MinIO) and marks itself done. A stage that finds itself done returns immediately.
  - `finalize` is the only place that sets `indexed`. `graph_extract` failure does not fail
    the document.
  - Each stage opens short sessions and holds no connection across provider calls.
- **Done when:** Killing the worker during `embed` and redelivering resumes at `embed`, with
  no duplicate chunks, vectors, or usage events. The lifecycle in `AGENTS.md` is preserved.

### R06-02 — Bounded memory for large files (M)

- **Change:** Stream the MinIO object to a temporary file instead of `body.read()`. Process
  PDFs page by page. Embed and upsert in batches as chunks are produced.
- **Done when:** Worker peak memory for a 500 MB file stays under a configured ceiling.

### R06-03 — Task limits and worker recycling (S)

- **Change:** Set `soft_time_limit` and `time_limit` per task from settings, plus
  `worker_max_tasks_per_child` and `worker_max_memory_per_child`. Keep each stage shorter
  than the broker's consumer acknowledgement timeout, and configure that timeout explicitly.
- **Done when:** A task that exceeds its soft limit is recorded in `FailedJob` with a
  timeout code.

### R06-04 — Worker pools per queue (M)

- **Change:** Replace the single worker with services `worker-ingest`, `worker-graph`,
  `worker-sync`, `worker-eval`, and `worker-default`, each with `-Q` and `--concurrency` from
  settings. Document which pools are CPU-bound (OCR) and which are I/O-bound.
- **Done when:** An evaluation run that fills its queue does not delay a user upload in the
  load test.

### R06-05 — Dead-letter queues (S)

- **Change:** Declare queues as quorum queues with a dead-letter exchange and a delivery
  limit. A consumer on the dead-letter queue writes a `FailedJob` row. The existing failed
  job dashboard (F156) lists them.
- **Done when:** A poison message lands in `FailedJob` after the delivery limit and never
  blocks the queue.

### R06-06 — Embedding throughput and reuse (M)

- **Change:** Run embedding batches concurrently with a bounded semaphore and provider
  rate-limit awareness. Add an embedding cache keyed by `(embedding_model, chunk_hash)` so
  reindexing unchanged content does not call the provider.
- **Done when:** Reindexing an unchanged document makes zero embedding calls.

### R06-07 — Qdrant client and collection tuning (M)

- **Change:**
  - Call `ensure_qdrant_collection()` once at startup and in the migrate job, not on every
    upsert and delete.
  - Use `AsyncQdrantClient`. Raise the 2 s timeout for writes and keep a short one for
    searches.
  - Make HNSW, quantization, on-disk vectors and payload, shard number, and replication
    factor configurable. Evaluate the tenant-partitioned HNSW settings that Qdrant documents
    for multitenancy, and scalar quantization, against the accuracy gate before changing
    defaults. Check the settings against the documentation for the pinned Qdrant version.
  - Stop storing `parent_text` on every point; resolve parent text from Postgres by ID.
    Measure the retrieval latency change before removing it.
- **Done when:** Upsert makes one round trip per batch, and recall on the evaluation set is
  unchanged after tuning.

### R06-08 — Index versions and zero-downtime reindex (L)

- **Change:**
  - Collections are named `{base}_{embedding_model_slug}_v{n}` and addressed through an
    alias. Production retrieval reads the alias.
  - A reindex writes a new collection in the background, verifies point counts, then swaps
    the alias. The old collection is kept for a configurable grace period.
  - A changed embedding model or dimension creates a new collection instead of failing at
    startup.
  - Admin endpoint and UI show reindex progress.
- **Done when:** An embedding model change completes on staging with no failed queries.

### R06-09 — Scalable multilingual keyword search (M)

- **Change:**
  - Add `organization_id` to `document_chunks` (additive, backfilled in batches, then
    `NOT NULL`) with a composite index, so keyword search needs no join for tenant scoping.
  - Build the `tsvector` with the document's detected language configuration (F230), falling
    back to `simple`. Query with the question's language configuration.
  - Rank a bounded candidate set instead of every match.
  - Filter on `index_version` (already done in `R02-05`).
- **Done when:** German, Spanish, and French keyword recall improves on the evaluation set,
  and keyword search p95 stays flat as the table grows in the load test.
- **Flag:** `hybrid_retrieval` and `context_packing` default to on after this item.

### R06-10 — Batched graph writes (M)

- **Change:** Write entities, aliases, and relations with `UNWIND` batches in one transaction
  per batch. Run extraction LLM calls for chunk groups concurrently with a bound.
- **Done when:** Graph write round trips per document drop from one per entity to one per
  batch.

### R06-11 — Connector sync at tenant scale (L)

- **Change:**
  - Commit per page of items and persist the checkpoint in the same transaction. Dispatch
    document processing as each page commits.
  - Poll due jobs with `FOR UPDATE SKIP LOCKED` in one query; remove the per-job check.
  - Per-organisation and per-connection concurrency caps.
  - On a provider rate limit, honour `Retry-After` and back off inside the run instead of
    failing it.
  - Split `sync_engine.py` (1,779 lines) into planner, fetcher, differ, and writer modules.
- **Done when:** A sync of 100,000 items can be cancelled within seconds and resumes from the
  last checkpoint after a worker restart.

### R06-12 — Evaluation isolation (M)

- **Change:** Evaluations run on `worker-eval` only, with bounded per-question concurrency,
  and write to the evaluation collection (`R02-05`). Split `evaluation_tasks.py` (1,770
  lines) by run type.
- **Done when:** A full evaluation run causes no measurable change in chat or ingestion
  latency in the load test.

### R06-13 — Agent runs in workers (L)

- **Change:**
  - Run agent steps in a Celery task, with run state persisted after every step.
  - Approval enqueues a resume task. A run is `running` only while a task owns it.
  - Implement `GET /agents/runs/{run_id}/stream` (currently 501) by relaying step events
    through Redis pub/sub, reusing the event protocol from `R05-03`.
  - Budgets and policy checks from `docs/13_AGENTIC_ARCHITECTURE_AND_CAPABILITY_MODEL.md`
    stay in the runtime. Split `runtime.py` (1,291 lines).
- **Done when:** A run that needs approval continues after approval, survives a worker
  restart, and the API request that started it returns immediately.

## 3. Exit criteria

- Chaos test: kill each worker pool during work; everything completes, nothing duplicates.
- Ingestion p95 for the reference document meets the master-plan target.
- Accuracy gates pass with `hybrid_retrieval` and `context_packing` on.
- No worker module exceeds 500 lines.

## 4. Failure Modes and Recovery

| Failure | Recovery |
|---|---|
| Stage artifact missing on resume | Stage re-runs from the previous artifact |
| Alias swap to a bad collection | Swap the alias back; the old collection is retained |
| `organization_id` backfill is slow | Batched and resumable; the join path remains until the column is complete |
| Dead-letter queue grows | Alert on depth; bulk retry from the failed job dashboard |

## 5. Security Considerations

The evaluation collection and stage artifacts contain document text and need the same
organisation scoping and deletion cascade as production data. Document deletion (F143) must
also delete stage artifacts and embedding cache entries. Agent steps in workers keep the role
and organisation checks from the runtime.

## 6. Observability and Operations

Metrics: `rudix_ingest_stage_seconds{stage}`, queue depth and oldest-message age per queue,
`rudix_embedding_cache_hits_total`, `rudix_reindex_progress`, dead-letter depth. Update
`docs/17_CONNECTOR_OPERATIONS_RUNBOOK.md` and add an ingestion runbook.

## 7. Change Notes

- 2026-11-26: Initial version.
