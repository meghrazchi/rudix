# 17 - Connector Operations Runbook

## Purpose

This runbook covers the operational workflow for connector providers in staging
and production: setup, contract validation, rollout, health monitoring,
troubleshooting, rollback, reconnect, secret rotation, and provider outages.

## Rollout Controls

Connector execution is gated by two settings:

- `FEATURE_ENABLE_CONNECTORS`
- `CONNECTOR_ROLLOUT_STAGE`

Supported rollout stages:

- `off` - disable connector creation, refresh, disconnect, OAuth completion, and sync operations
- `development` - enable only in development deployments
- `staging` - enable only in staging deployments
- `production` - enable only in production deployments
- `all` - enable in every non-test deployment

If the rollout stage is `off`, the runtime treats the connector platform as
disabled even if the feature flag is still set to true.

## Health and Observability

Use the admin health endpoint to inspect connector status:

- `GET /api/v1/admin/connectors/health`

The response includes:

- organization scope
- generated range
- overall connector platform status
- per-provider connection, sync, retry, skip, ingestion, and citation counts
- average latency and top error codes

Provider-specific signals are derived from:

- sync run lifecycle data
- connector audit events
- document and citation provenance
- structured connector logs

Sync runs (0.6.0, R06-11) also report progress while they run:
`GET /api/v1/connectors/sync-runs/{id}` returns `pages_committed` and `checkpoint_at` (the
last page commit), next to `items_seen`, `items_upserted`, and `items_deleted`. A
`running` run whose `checkpoint_at` stops moving is stalled or waiting for a Retry-After.

Worker metrics (on the worker metrics port):

| Metric | Labels | Meaning |
| --- | --- | --- |
| `rudix_connector_sync_pages_total` | `provider`, `mode` | Pages committed (`full`, `incremental`) |
| `rudix_connector_sync_rate_limited_total` | `provider`, `outcome` | Provider rate limits: `inline` (slept, same page retried) or `requeued` (checkpointed, re-enqueued) |
| `rudix_connector_sync_deferred_total` | `reason` | Runs held back or re-enqueued: `org_cap`, `connection_cap`, `lease_held`, `lease_lost`, `rate_limit`, `stale` |
| `rudix_worker_tenant_mismatch_total` | `task` | Items an adapter returned for another organization or connection (skipped) |

Structured logs: `connector.sync.page_committed`, `connector.sync.rate_limited`,
`connector.sync.retry_scheduled`, `connector.sync.cancelled`, `connector.sync.resumed`,
`connector.sync.lease_lost`, `connector.sync.cap_deferred`, `connector.sync.requeued`,
and `connector.sync.stale_runs_requeued` (beat). They carry run, organization, and
provider identifiers and counters, never item content.

## New Provider Checklist

Before merging a new provider:

1. Register the provider in the shared provider registry.
2. Implement the adapter and normalizer behind the shared connector contract.
3. Add provider fixtures and contract tests using the shared harness.
4. Verify sync, delta, download, and ingestion behavior against the fake provider.
5. Document provider-specific setup and limitations in the connector platform docs.
6. Add the provider to the connector contract CI job if it is meant to ship with the default bundle.

## Rollout Checklist

Use this sequence for a new provider or a major connector change:

1. Merge adapter and contract test coverage.
2. Deploy to development with the connector platform enabled.
3. Confirm `/api/v1/admin/connectors/health` shows healthy or expected degraded signals.
4. Roll out to staging with the feature flag enabled and the rollout stage pinned to `staging`.
5. Validate reconnect, refresh, and sync failure handling under a staging dataset.
6. Promote to production by moving `CONNECTOR_ROLLOUT_STAGE` to `production`.
7. Leave the feature flag on and roll back by moving the stage back to `off` if needed.

## Troubleshooting

### No provider appears in the UI

- Confirm the provider registration exists in the shared registry.
- Check that the connector platform rollout is enabled for the deployment.
- Verify the backend logs include the provider key and connection identifier.

### Sync runs are failing

- Check `/api/v1/admin/connectors/health` for provider-specific error codes.
- Inspect the connector sync run and audit logs for rate limits, skipped items,
  ingestion failures, and OAuth refresh failures.
- Verify the provider credential is still valid and scoped correctly.
- A rate limit no longer fails a run (0.6.0). A run that shows `running` with an
  unchanged `checkpoint_at` and `rudix_connector_sync_rate_limited_total{outcome="requeued"}`
  rising is waiting for the provider's Retry-After; it resumes on its own. Lower
  `CONNECTOR_SYNC_MAX_CONCURRENT_PER_CONNECTION` if one connection keeps hitting limits.
- `error_details.code` on a failed run: `auth_error` (token refresh failed; reconnect),
  `permission_denied`, `connection_not_active`, `adapter_not_found`, `sync_error`, or
  `task_terminal_failure` (the task gave up after its retries).
- A run stuck in `queued` with `rudix_connector_sync_deferred_total{reason=~".*_cap"}`
  rising is held back by a concurrency cap and retried every
  `CONNECTOR_SYNC_CAP_RETRY_SECONDS`.
- A run stuck in `running` whose heartbeat is older than `CONNECTOR_SYNC_STALE_SECONDS`
  is re-enqueued by `connectors.sync.reap` (beat, every
  `CONNECTOR_SYNC_REAP_INTERVAL_SECONDS`); check that beat and a worker on the
  connector sync queue are up.

### Cancelling and resuming a large sync

- Cancel from the UI or with `POST /api/v1/connectors/sync-runs/{id}/cancel`. The run
  stops within one cancel-check interval (`CONNECTOR_SYNC_CANCEL_CHECK_ITEMS` items,
  default 50) of the page it is on, keeps every committed page, its counters, and its
  checkpoint, and ends `cancelled`. Documents of committed pages stay and keep
  processing.
- A cancelled run is final. Start a new sync (manual or full resync) when ready: unchanged
  items are cheap (one lookup per page slice), so most of the cost is new and changed
  items.
- A worker restart or crash does not lose progress. The broker redelivers the message (same
  lease owner) or `connectors.sync.reap` re-enqueues the run once its heartbeat is stale;
  either way the run continues from `checkpoint_cursor` with its counters. The page that
  was in flight is rolled back and fetched again; outbox dedupe keys prevent duplicate
  processing messages.
- To stop a run that keeps resuming, cancel it; to stop all syncs of a connection, pause
  or disable its jobs first, then cancel the active run.
- A full sync tombstones unseen items only after its last page. A full sync cancelled
  while paging tombstones nothing; one cancelled during the tombstone phase keeps the
  tombstone batches it already committed (`CONNECTOR_SYNC_TOMBSTONE_BATCH_SIZE` each).

### Scheduled syncs never start

Scheduled connector sync depends on the `beat` service, which enqueues
`connectors.sync.schedule_poll` periodically. If beat is not running, manual syncs still work
but scheduled ones never start.

- Check the service: `docker compose ps beat`.
- Check the log: `docker compose logs beat` should show `beat: Starting...` and
  `Scheduler: Sending due task connector-sync-schedule-poll`.
- Run exactly one beat instance; never scale it.
- Beat alerts (0.8.0): beat enqueues `ops.beat.heartbeat` every
  `BEAT_HEARTBEAT_INTERVAL_SECONDS` (default 60) on the default queue, and each run sets
  `rudix_beat_heartbeat_timestamp_seconds`. `RudixBeatHeartbeatStale` (critical) fires when the
  newest heartbeat is older than 5 minutes for 5 minutes; `RudixBeatHeartbeatMissing` fires
  when worker targets are up but no heartbeat was ever exported for 15 minutes (beat never
  started, or `METRICS_ENABLED` is off on the workers). Either alert means scheduled syncs are
  not being enqueued, or the default pool is not running them: check the beat log first, then
  `worker-default` (`infra/observability/prometheus/rules/beat.yml`).

### OAuth reconnect fails

- Confirm the redirect URI matches the provider configuration.
- Verify the stored OAuth state has not expired.
- Re-run the OAuth connect flow after clearing the existing connection if the
  provider has rotated scopes or changed consent requirements.

### Secret rotation

- Rotate `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY` through the secret manager.
- Update `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_ID` when the active key changes.
- Reconnect any credentials that cannot be decrypted after the rotation.

### Provider outage

- Use the health endpoint to confirm whether the issue is provider-wide.
- Keep the connector platform enabled only if you need to preserve reads or
  inspect existing state.
- Pause or disable sync jobs for the affected provider if repeated retries are
  causing noise or downstream load.

## Rollback

Rollback should be configuration-first:

1. Set `CONNECTOR_ROLLOUT_STAGE=off`.
2. Keep the feature flag on if you need to inspect the existing data model and
   health signals.
3. Disable or pause sync jobs for the affected provider.
4. Reconnect only after the provider issue or adapter regression is resolved.

If the issue is a provider-specific regression, revert the provider adapter and
rerun the contract suite before re-enabling the rollout stage.
