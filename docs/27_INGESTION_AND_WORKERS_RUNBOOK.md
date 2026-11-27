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

## Connector sync

R06-11 (0.6.0). Design: `docs/16_CONNECTOR_PLATFORM.md` (Sync Lifecycle and Checkpoints);
operator steps: `docs/17_CONNECTOR_OPERATIONS_RUNBOOK.md`.

- **Tasks.** `connectors.sync.run` (connector sync queue) runs or resumes one run;
  `connectors.sync.schedule_poll` (beat) claims due jobs with one `FOR UPDATE SKIP LOCKED`
  query on `connector_sync_jobs.next_run_at`; `connectors.sync.reap` (beat, every
  `CONNECTOR_SYNC_REAP_INTERVAL_SECONDS`, `maintenance_session()`) releases and re-enqueues
  `running` runs whose heartbeat is older than `CONNECTOR_SYNC_STALE_SECONDS`.
- **Transactions.** A lease transaction, then one transaction per provider page; no
  transaction is open during the provider call. Each page commit carries its checkpoint, its
  counters, the heartbeat, and the outbox rows of the documents it created, and is published
  right after the commit. The lease owner is the Celery request id, so a redelivery of the
  same message re-takes its lease; a page commit by a worker that lost its lease is rolled
  back.
- **Resume.** Broker redelivery after a crash, a reap, or a long Retry-After continue from
  `checkpoint_cursor` with the persisted counters. Full-sync tombstones use
  `external_items.last_seen_sync_run_id`, written per page, so a resume never tombstones what
  an earlier attempt saw.
- **Settings.** `CONNECTOR_SYNC_STALE_SECONDS` (600), `CONNECTOR_SYNC_CANCEL_CHECK_ITEMS`
  (50), `CONNECTOR_SYNC_PAGE_SIZE` (100), `CONNECTOR_SYNC_POLL_BATCH_SIZE` (100),
  `CONNECTOR_SYNC_MAX_CONCURRENT_PER_ORG` and `_PER_CONNECTION` (0 = off),
  `CONNECTOR_SYNC_CAP_RETRY_SECONDS` (60), `CONNECTOR_SYNC_MAX_INLINE_BACKOFF_SECONDS` (60),
  `CONNECTOR_SYNC_MAX_INLINE_RETRIES` (5), `CONNECTOR_SYNC_TOMBSTONE_BATCH_SIZE` (500),
  `CONNECTOR_SYNC_REAP_INTERVAL_SECONDS` (120). Set the stale threshold above the longest
  page (provider call plus downloads), or a slow page is taken over and rolled back.
- **Tenancy.** The task runs bound to its `organization_id`; every query is scoped by the
  run's organization and connection; adapter items naming another organization or
  connection are skipped and counted in `rudix_worker_tenant_mismatch_total`.

| Symptom | Cause | Recovery |
|---|---|---|
| Run `running`, `checkpoint_at` not moving, `lease_owner` empty | Waiting for a provider Retry-After (`heartbeat_at` is the resume time) | None; it is re-enqueued with the countdown. |
| Run `running`, heartbeat old, `lease_owner` set | Worker died | `connectors.sync.reap` re-enqueues it; check beat and the connector sync worker. |
| Run `queued`, `rudix_connector_sync_deferred_total{reason=~".*_cap"}` rising | Concurrency cap | Wait, or raise the cap. |
| `connector.sync.lease_lost` | A slow page outlived `CONNECTOR_SYNC_STALE_SECONDS` and another worker took over | Raise the stale threshold; the page is rolled back and done again by the new owner. |
| Documents of a sync stay `pending_scan` | Outbox rows pending (broker outage) | `outbox.relay` publishes them (`rudix_outbox_messages_total{task="documents.process"}`). |

Rollback: none is needed for data (no migration in R06-11; the columns came with
`20261128_0002`). An older worker build ignores the checkpoint columns and runs a whole sync
in one transaction; runs left `running` by the new build are then picked up only after a
manual retry.
