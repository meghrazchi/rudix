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
Celery tasks; worker pools, time limits, and dead-letter queues (C1, section "Worker
platform"). Out of scope: vector index generations (A2), agent runs (C2), connector sync (D1).

## 3. Assumptions and Constraints

- RabbitMQ with `task_acks_late` and `task_reject_on_worker_lost`: a message whose worker dies
  is delivered again with the same task id and kwargs.
- One dev `worker` consumes every queue in `task_queues`; staging and production run the
  five C1 pools (`worker-ingest`, `-graph`, `-sync`, `-eval`, `-default`).
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
4. Set `KEYWORD_SEARCH_TENANT_COLUMN=on`, or leave `auto`. In `auto` mode each process
   checks for NULL rows once, on its first keyword search, and keeps the answer. API and
   worker processes that started before the backfill finished keep the join path until
   they restart.

Rollback: `deploy/sql/document_chunks_not_null_revert.sql` (drops the policy, disables
RLS, drops `NOT NULL`). Set `KEYWORD_SEARCH_TENANT_COLUMN=auto` or `off` first. The
columns themselves are additive (migration `20261128_0002`) and need no rollback.
Both SQL files are generated by `backend/scripts/render_chunk_not_null_sql.py`; check them
with `--check`.

## Keyword search settings

| Setting | Default | Effect |
|---|---|---|
| `KEYWORD_SEARCH_MULTILINGUAL` | `false` | `true` also matches `fts_vector` with the question's text search configuration (German, Spanish, French, English; others `simple`). The English column stays a second match, so no previous result is lost. |
| `KEYWORD_SEARCH_TENANT_COLUMN` | `auto` | `on`: scope by `document_chunks.organization_id` (index `idx_chunks_org_document`). `off`: scope by the owning document, as before. `auto`: `on` once no NULL row remains, checked once per process (restart processes that started before the backfill finished). Use `on` only after the backfill. |
| `KEYWORD_SEARCH_CANDIDATE_LIMIT` | `1000` | Matches ranked per search (the first ones in index scan order). `0` ranks every match. When more chunks match than the limit, the candidates follow storage order, not relevance: a better-ranked chunk outside them is not returned. Common terms in large organisations are affected first, so compare `1000` with `0` on the staging accuracy gate. |

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

## Worker platform (R06-03, R06-04, R06-05)

Package C1. Settings are in `app/core/settings/workers.py` (`# anchor: C1`), the code in
`app/workers/{time_limits,pools,queues,dead_letter,queue_metrics}.py`. Deployment details
are in [10_DEPLOYMENT_DOCKER.md](./10_DEPLOYMENT_DOCKER.md#worker-pools-and-rabbitmq-060).

### Worker pools

| Pool (service) | Queues | Load |
|---|---|---|
| `ingest` (`worker-ingest`) | `documents.processing` (extract to finalize), `documents.deletion`, `documents.reindex` | CPU-bound (OCR, parsing) |
| `graph` (`worker-graph`) | `documents.graph` | I/O-bound (LLM, Neo4j) |
| `sync` (`worker-sync`) | `connectors.sync` | I/O-bound (provider APIs) |
| `eval` (`worker-eval`) | `evaluations` | Mixed, isolated from uploads |
| `default` (`worker-default`) | `default`, `email`, `agents`; dead-letter consumer; queue depth sampler | Light |

- Start one locally: `cd backend && make run-worker-pool POOL=ingest`; in compose,
  `python -m app.workers.pools <name>`. The command is logged by Celery at start
  (`-Q`, `--concurrency`, node name `<pool>@<host>`).
- Check a pool: `celery -A app.workers.celery_app:celery_app inspect ping -d ingest@<host>`
  and `inspect active_queues -d ingest@<host>`.
- Uploads waiting behind something: `rudix_celery_queue_wait_seconds{queue}` p95 per queue
  (dashboard `07 — Rudix Worker Pools & Queues`). A long wait on one queue with idle others
  means that pool needs concurrency or replicas, not the others.
- A queue that no pool lists keeps its messages: `rudix_celery_queue_consumers{queue} == 0`
  with depth above zero raises `RudixCeleryQueueWithoutConsumers`. Fix
  `WORKER_POOL_<NAME>_QUEUES`.

### Time limits

Every task has a soft limit (Celery raises `SoftTimeLimitExceeded` inside the task, which can
clean up) and a hard limit (the child process is killed). Built-in values:

| Task | Soft / hard (s) |
|---|---|
| `documents.ingest.extract`, `documents.graph_extract`, `documents.process`, `documents.reindex`, `documents.graph_reindex`, `evaluations.run`, `safety_evals.run`, `connectors.sync.run`, `maintenance.retention.purge` | 1500 / 1620 |
| `documents.ingest.embed` | 900 / 960 |
| `documents.ingest.clean_detect`, `.dlp`, `.chunk`, `documents.delete`, `documents.backfill` | 600 / 660 |
| `documents.ingest.index`, `.finalize` | 300 / 360 |
| every other task | `CELERY_TASK_DEFAULT_SOFT_TIME_LIMIT` / `CELERY_TASK_DEFAULT_TIME_LIMIT` (300 / 360) |

Override per task with `CELERY_TASK_TIME_LIMITS='{"evaluations.run": {"soft": 1700, "hard":
1750}}'`; entries merge over the built-in ones. Every hard limit must stay below
`CELERY_BROKER_CONSUMER_TIMEOUT_SECONDS` (1800, equal to `consumer_timeout` in
`infra/rabbitmq/rabbitmq.conf`): RabbitMQ closes the channel of a consumer that keeps a
delivery unacknowledged longer and redelivers the message while the task still runs. At
start a worker logs `worker.time_limit_exceeds_consumer_timeout` for every offending task and,
in staging and production, exits. To run a longer task, raise both timeouts together.

What a limit leaves behind:

- `FailedJob` with `error_code` `task_soft_time_limit` or `task_time_limit` (was the class
  name before 0.6.0), so the dashboard can filter them; retryable as before.
- A document task marks the document `failed` with document error code
  `task_soft_time_limit` / `task_time_limit`, category `infrastructure`, retryable, and the
  stage of the stage task (`unknown` for `documents.process` in inline mode). Existing error
  details on the exception (for example an OCR timeout) are kept.
- Chain stage tasks keep their artifacts on such a failure (retryable), so a dashboard retry
  resumes the run at that stage; the embed stage resumes from its last completed batch.
- `rudix_celery_task_time_limit_total{task,kind}`. Hard limits are counted in the worker's
  main process, which serves the metrics port; soft limits run `on_failure` in the prefork
  child, so use the `FailedJob` rows for those.

Recycling: `CELERY_WORKER_MAX_TASKS_PER_CHILD` (200) and
`CELERY_WORKER_MAX_MEMORY_PER_CHILD_KB` (0 = off) replace a child after its current task. A
new child drops the database pool and event loop it inherited from the main process (which
uses them for the dead-letter consumer and hard-limit failures).

### Dead-letter queue and quorum cut-over

With `CELERY_QUEUE_TYPE=quorum`, RabbitMQ dead-letters a message after
`CELERY_DELIVERY_LIMIT` deliveries without an ack (a task that kills its worker every time, a
payload that crashes the consumer) to `rudix.dlx` -> `rudix.dead_letter`. Every quorum-mode
worker declares that exchange, queue, and binding at start (RabbitMQ drops dead letters that
route nowhere); the queue is never in `task_queues`, so a worker without `-Q` does not execute
dead letters. `worker-default` reads it with a consumer bootstep that never runs the task. Per message it writes one
`FailedJob`: `job_type='dead_letter'`, `error_code='delivery_limit_exceeded'`,
`is_retryable=true`, the tenant of the message's `organization_id`, the task identity a
dashboard retry needs (stage tasks map to `documents.process` / `documents.reindex` with
`metadata.stage` and `run_id`, as for stage failures), and `metadata.dead_letter` (original
task, original queue, reason, death count). Then it acks. A second copy of the same task id
is acked without a second row. A message without a tenant is logged
(`dead_letter.no_tenant`) and acked; a malformed one (`dead_letter.malformed`) is acked and
never requeued; a database error requeues it (`dead_letter.persist_failed`). The failed job
dashboard lists the rows under the job type `Dead letter`; retry them there after fixing the
cause.

Cut-over from classic to quorum (staging first; RabbitMQ 3.8 or later):

1. Choose new names for every task queue, for example with a `.q` suffix:
   `CELERY_TASK_DEFAULT_QUEUE=default.q`, `CELERY_QUEUE_DOCUMENTS_PROCESSING`,
   `_DELETION`, `_REINDEX`, `CELERY_QUEUE_EVALUATIONS`, `CELERY_QUEUE_CONNECTOR_SYNC`,
   `CELERY_QUEUE_EMAIL`, `CELERY_QUEUE_DOCUMENTS_GRAPH` (and `CELERY_QUEUE_DOCUMENTS_EMBEDDING`
   when it is set, `CELERY_QUEUE_AGENTS` once C2 is deployed), each `<old name>.q`. Add
   `CELERY_QUEUE_TYPE=quorum` and, if wanted, `CELERY_DELIVERY_LIMIT`. Unset
   `WORKER_POOL_<NAME>_QUEUES` overrides or rename their entries too.
2. Note the old names and that `rabbitmqctl list_queues name type messages consumers` shows
   them as `classic`.
3. Deploy the new environment to `api`, `beat`, and the five pools. New publications go to
   the new quorum queues through `rudix.tasks`; Celery also declares its `celery_delayed_*`
   exchanges and queues for countdown and ETA retries. Outbox rows are published with the
   queue they stored, and the new configuration would declare a stored old name as a quorum
   queue (`PRECONDITION_FAILED` while the classic queue exists). Deploy when
   `SELECT count(*) FROM outbox_messages WHERE status = 'pending'` is 0; rows left behind can
   be pointed at the new names with `UPDATE outbox_messages SET queue = queue || '.q',
   attempts = 0, available_at = now(), status = 'pending' WHERE status IN ('pending',
   'failed') AND last_error IS DISTINCT FROM 'cancelled' AND queue NOT LIKE '%.q'`. Failed
   job dashboard retries follow the current route of the task, not the queue stored on the
   row, so they reach the new queues.
4. Drain the old classic queues with one temporary worker on the previous configuration
   (classic type, old names, all old queues):

   ```bash
   docker compose -f docker-compose.<env>.yml run --rm --no-deps \
     -e CELERY_QUEUE_TYPE=classic -e CELERY_TASK_DEFAULT_QUEUE=default \
     -e CELERY_QUEUE_DOCUMENTS_PROCESSING=documents.processing \
     -e CELERY_QUEUE_DOCUMENTS_DELETION=documents.deletion \
     -e CELERY_QUEUE_DOCUMENTS_REINDEX=documents.reindex \
     -e CELERY_QUEUE_EVALUATIONS=evaluations -e CELERY_QUEUE_CONNECTOR_SYNC=connectors.sync \
     -e CELERY_QUEUE_EMAIL=email -e CELERY_QUEUE_DOCUMENTS_GRAPH=documents.graph \
     worker-default python -m celery -A app.workers.celery_app:celery_app worker \
     -Q default,documents.processing,documents.deletion,documents.reindex,evaluations,connectors.sync,email,documents.graph \
     --concurrency 2 -n drain@%h
   ```

   Hand-offs and retries of drained tasks stay on the old queues, which this worker consumes.
5. When `rabbitmqctl list_queues name messages messages_unacknowledged` shows 0 and 0 for every
   old queue for a few minutes (and no `pending` outbox row names an old queue:
   `SELECT queue, count(*) FROM outbox_messages WHERE status = 'pending' GROUP BY queue`),
   stop the drain worker and delete the old queues (`rabbitmqctl delete_queue <name>`).
6. Verify: `rabbitmqctl list_queues name type arguments` shows `quorum` with
   `x-delivery-limit` and `x-dead-letter-exchange`; `rudix_celery_queue_depth` reports the new
   names and `rudix.dead_letter`; run the poison-message check in plan section 8.

Rollback to classic: set `CELERY_QUEUE_TYPE=classic` and the previous queue names (or unset
them), deploy, and drain the quorum queues the same way with a temporary worker started with
the quorum environment (`CELERY_QUEUE_TYPE=quorum` and the `.q` names). Messages still in
`rudix.dead_letter` stay there; drain them first with that worker plus
`WORKER_CONSUME_DEAD_LETTER=true`, or leave the queue for later. `FailedJob` rows already
written are kept.

Failure modes:

| Symptom | Cause | Recovery |
|---|---|---|
| `RudixDeadLetterQueueNotEmpty` | `worker-default` not running, not in quorum mode, or `dead_letter.persist_failed` | Start or fix `worker-default` (`WORKER_CONSUME_DEAD_LETTER=true`, `CELERY_QUEUE_TYPE=quorum`); check the database. |
| `FailedJob` rows with `delivery_limit_exceeded` | A task crashed its worker `CELERY_DELIVERY_LIMIT` times | Find the cause in worker logs for the task id (OOM kill, segfault in a parser); fix, then retry from the dashboard. |
| Worker exits at start with `hard time limits must be below ...` | A hard limit is not below the consumer timeout | Lower the limit or raise `consumer_timeout` and `CELERY_BROKER_CONSUMER_TIMEOUT_SECONDS` together. |
| Many `task_soft_time_limit` failures on one stage | Documents larger than the limit allows | Raise that task's limit (within the consumer timeout) or `WORKER_POOL_INGEST_CONCURRENCY` down to free CPU. |
| `PRECONDITION_FAILED - inequivalent arg 'x-queue-type'` in worker logs | `CELERY_QUEUE_TYPE=quorum` with an existing classic queue name | Use new names (step 1); never reuse a classic name for quorum. |
| `RudixCeleryQueueWaitHigh` on one queue | The pool for that queue is saturated or down | Scale that pool; check `inspect active -d <pool>@<host>`. |

Not verified in this repository (no broker in CI): real dead-lettering, `consumer_timeout`,
child recycling, and the load test that an evaluation does not delay uploads. They are the
manual checks in [plan section 8](./roadmap/V0_6_0_IMPLEMENTATION_PLAN.md#8-manual-steps-staging-and-production).
