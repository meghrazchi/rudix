# DR: broker loss

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Active (0.8.0, R08-13); not yet exercised in a drill
- `Last Updated`: 2026-11-28
- `Related Docs`: [../27_INGESTION_AND_WORKERS_RUNBOOK.md](../27_INGESTION_AND_WORKERS_RUNBOOK.md)
  "Outbox", "Resume and reaper", "Dead-letter queue and quorum cut-over",
  [../28_KUBERNETES_HELM_DEPLOYMENT.md](../28_KUBERNETES_HELM_DEPLOYMENT.md)
  "Data stores, backups, and restore"

Scope: RabbitMQ is unreachable, a node of the cluster is lost, or queues and their messages
are gone (a lost volume, a recreated broker, a deleted vhost). The broker is not backed up:
work is recovered from PostgreSQL by the outbox relay and the reapers.

What survives depends on the queue type (`CELERY_QUEUE_TYPE`):

| Queue type | One node lost (3-node cluster) | Whole broker or its data lost |
|---|---|---|
| `classic` (default) | Messages on that node's queues are unavailable until it returns, or lost if its disk is lost | Every queued message is lost |
| `quorum` (after the docs/27 cut-over) | Queues keep serving from the other two nodes; acknowledged publishes are not lost | Every queued message is lost |

Recovery paths that do not need the broker's data:

- **Outbox relay** (`outbox.relay`, every `OUTBOX_RELAY_INTERVAL_SECONDS`): upload, delete,
  retry-delete, reindex, graph reindex, and OCR retry are written to `outbox_messages` in the
  same transaction as the change and stay `pending` until published; while the broker is down
  the relay retries with backoff and marks rows `failed` after `OUTBOX_MAX_ATTEMPTS`.
- **Document reaper** (`documents.reap_stale`, every `DOCUMENT_REAPER_INTERVAL_SECONDS`):
  documents silent in `processing` for `DOCUMENT_PROCESSING_STALE_SECONDS` are released and
  re-queued with the latest unfinished run, so a lost stage message resumes at its stage.
- **Other reapers**: `agents.runs.reap` (agent runs) and `connectors.sync.reap` (sync jobs).
- **Dead-letter consumer** (quorum mode only): messages over `CELERY_DELIVERY_LIMIT` go to
  `rudix.dead_letter` and become `FailedJob` rows (`job_type='dead_letter'`) that the failed
  job dashboard retries.
- Tasks published without the outbox (emails, evaluations, safety evaluations, connector sync
  runs triggered by hand) are lost with the queue; users or admins trigger them again.

## Detection

- `/api/v1/ready` reports `rabbitmq` down; uploads answer `deferred` or `503`.
- The RabbitMQ exporter stops reporting (`rabbitmq_queue_messages_ready`, used by
  `RudixCeleryQueueBacklog`, disappears); worker pods restart in a loop on connection errors.
- `outbox_messages` rows stay `pending` and their `attempts` grow:
  `SELECT task_name, status, count(*), min(created_at) FROM outbox_messages WHERE status <> 'published' GROUP BY 1, 2;`
- Logs: `outbox.publish_deferred` (right after commit), `outbox.relay_gave_up` (a row marked
  `failed`), `outbox.relay_completed` with `retried` above 0, and Celery
  `consumer: Cannot connect to amqp://...` (that line can carry the broker URL; never paste
  it into tickets).

## Decision owner

- On-call engineer: restores the broker and runs the checks.
- Incident commander: decides on recreating a broker with empty queues (accepts the loss of
  non-outbox tasks) and on customer communication if uploads were refused.
- Platform owner: the RabbitMQ cluster, its storage, and the quorum cut-over schedule.

## Steps

1. Keep the API up: uploads keep their outbox rows and answer as designed while the broker is
   down; nothing needs to be stopped.
2. One node lost, cluster still has a majority (quorum queues): replace the node through the
   provider or the operator, let it rejoin, and confirm with
   `rabbitmqctl list_queues name type messages` that every queue is `quorum` and online. No
   application step is needed.
3. Broker down but data intact: restart or fail over the broker. Workers reconnect on their
   own; `task_acks_late` with `task_reject_on_worker_lost` redelivers unacknowledged tasks,
   and every task is idempotent.
4. Broker data lost (empty broker):
   1. Bring up an empty broker with the same vhost, users, and `RABBITMQ_URL`. Workers declare
      their queues (and, in quorum mode, `rudix.dlx` and `rudix.dead_letter`) on start; restart
      the worker pools and beat so they reconnect cleanly.
   2. Do not change `CELERY_QUEUE_TYPE` during the incident. If the lost broker used quorum
      queues, keep `quorum` and the same queue names (`.q` suffix, docs/27); if it was
      classic, stay classic and plan the cut-over later.
   3. Outbox rows still `pending` are published by the relay within one interval. Rows marked
      `failed` during the outage are not retried automatically: after the broker is back,
      reset them (`UPDATE outbox_messages SET status = 'pending', attempts = 0, available_at = now() WHERE status = 'failed' AND created_at > '<outage start>';`)
      with the maintenance role, after the incident commander approves.
   4. Wait one `DOCUMENT_PROCESSING_STALE_SECONDS` plus one reaper interval: documents whose
      stage messages were lost are re-queued (`documents.reap_stale` logs the count).
   5. Ask admins to re-run evaluations, safety evaluations, or manual syncs that were queued
      during the outage, and check the email delivery log for messages that were never sent.
5. Review `FailedJob` rows created during the outage on the failed job dashboard and retry the
   retryable ones.

## Verification

- `/api/v1/ready` reports `rabbitmq` up; `rudix_celery_queue_depth` drains to its normal level.
- No `outbox_messages` row is `pending` older than a few relay intervals, and none is `failed`
  from the outage window.
- No document stays in `processing` longer than `DOCUMENT_PROCESSING_STALE_SECONDS`
  (`SELECT count(*) FROM documents WHERE status = 'processing' AND processing_started_at < now() - interval '1 hour';`
  returns 0 after the reaper ran).
- A new upload reaches `indexed`; a beat task (for example `usage.touch.flush`) runs on schedule.
- With quorum queues: `rabbitmqctl list_queues name type` shows `quorum` for every Rudix queue.
