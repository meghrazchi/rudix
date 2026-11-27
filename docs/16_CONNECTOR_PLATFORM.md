# 16 — Connector Platform

## Objective

The connector platform gives Confluence, Google Drive, and future providers
one shared source model, lifecycle, ingestion handoff, and security boundary.
Provider adapters are responsible for fetching and normalizing external data;
RAG, document lifecycle, chat, and citation services consume provider-neutral
records only.

## Domain Model

Core tables:

| Table | Purpose |
| --- | --- |
| `connector_providers` | Global provider metadata, auth type, capabilities, config schema, rate limits, export formats |
| `connector_connections` | Organization-owned provider accounts, optional collection scope, auth config metadata |
| `external_sources` | Provider containers such as Confluence spaces, Drive folders, or shared drives |
| `external_items` | Normalized issues, pages, files, folders, comments, and attachments |
| `connector_sync_jobs` | Durable sync configuration and cursor state |
| `connector_sync_runs` | Per-run lifecycle, counters, cursors, and safe error details |
| `source_documents` | Mapping from normalized external items to Rudix `documents` rows |
| `source_references` | Provider-neutral citation/source locators tied to documents and optional chunks with provider/title/section/deep-link snapshots |
| `external_item_tombstones` | Deleted or inaccessible provider items retained for deletion lifecycle and delta sync |

Every operational row carries `organization_id`. Connections, sources, items,
jobs, and source documents may also carry `collection_id` when the provider
scope is narrower than the whole organization.

## Provider Registry

Provider metadata lives in `backend/app/domains/connectors/services/provider_registry.py`.
Each provider registers:

- stable key and display name
- auth type: `none`, `oauth2`, `api_token`, `service_account`, or `basic`
- capabilities: webhooks, attachments, comments, folders, ACLs, delta sync,
  rate limits, and export formats
- JSON object config schema
- optional rate-limit and export-format descriptors

The default registry includes Confluence and Google Drive. New providers
can be registered by constructing a `ProviderRegistration` and calling
`ProviderRegistry.register()` or `ConnectorPlatformService.register_provider()`.

## Credential Vault and OAuth Lifecycle

Connector credentials are separated from normal connection metadata:

- `connector_credentials` stores encrypted credential payloads plus rotation-ready
  metadata: auth type, status, version, key ID, algorithm, fingerprint, scopes,
  issue/expiry times, refresh timestamps, usage timestamps, and revocation time.
- `connector_connections.auth_config` is metadata-only and must never contain raw
  access tokens, refresh tokens, API tokens, client secrets, or service-account
  material.
- `connector_oauth_states` stores hashed OAuth state values with organization,
  provider, optional collection/connection, requested scopes, redirect URI,
  expiry, and one-time consumption metadata.
- `ConnectorOAuthLifecycleService` owns OAuth state validation, callback handling,
  shared token refresh, revoke/disconnect, and safe diagnostics for all OAuth
  providers.
- `ConnectorCredentialVault` owns encryption/decryption and returns plaintext
  only to connector adapter code that is about to call the provider.

Production deployments should configure `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY`
from a secret manager. Non-production can fall back to `APP_AUTH_SECRET`, but
that fallback is not intended for staging or production. `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_ID`
identifies the active key for future rotation. `CONNECTOR_OAUTH_CLIENTS` stores
provider OAuth client metadata as a JSON array; config snapshots expose only
presence booleans, never client secrets.

Default least-privilege OAuth scope policy:

| Provider | Required scopes | Optional/default refresh scopes |
| --- | --- | --- |
| Confluence | `read:confluence-content.all` | `read:confluence-space.summary`, `offline_access` |
| Google Drive | `https://www.googleapis.com/auth/drive.readonly` | `https://www.googleapis.com/auth/drive.metadata.readonly` |

Requested scopes must include required scopes and must be a subset of the
provider allowlist. Unsupported broad scopes are rejected before an OAuth state
is issued.

## Normalized Item Contract

Adapters must emit `NormalizedExternalItem` records with:

- `organization_id`
- `provider_key`
- `provider_item_id`
- `item_type`
- `source_url`
- `content_hash`
- provider `updated_at`
- integer `sync_version`
- optional source, collection, parent, root, MIME, ACL, metadata, and permission fields

The same contract represents:

- Confluence pages, comments, and attachments
- Google Drive files and folders

Comments and attachments must include `provider_parent_id`. Collection-visible
items must include `collection_id`.

## Extension Pattern

To add a provider:

1. Define the provider registration with capabilities and config schema.
2. Register it through the shared registry or service.
3. Implement an adapter that fetches provider data and emits `NormalizedExternalItem`.
4. Persist connections, sources, sync jobs, sync runs, items, tombstones, and
   source-document links through `ConnectorRepository` or `ConnectorPlatformService`.
5. Hand connector content to the shared document ingestion path by creating or
   updating a `documents` row and linking it through `source_documents`.
6. Store provider provenance in `source_references` without adding provider
   branches to chat, citation, retrieval, or prompt services. Snapshot provider
   key, source title/key, section, ACL metadata, sync version, last synced
   timestamp, and trust status at ingest time so citations stay stable after
   source updates or tombstones.

## Sync Lifecycle and Checkpoints

Since 0.6.0 (R06-11) a sync run is many short transactions instead of one. The engine
(`app/domains/connectors/services/sync_engine.py`) is a facade over
`app/domains/connectors/services/sync/`: `planner` (jobs, triggers, runs), `schedule`
(due-job polling), `runner` (run lifecycle), `pages` (the page loop), `fetcher`
(provider paging, Retry-After, OAuth refresh), `differ` (change detection, conflicts,
tombstones), `writer` (file ingestion, run outcomes, audit), `lease` (leases, caps, the
stale-run sweep), and `scope` (transaction scopes).

1. **Schedule.** `connectors.sync.schedule_poll` claims due jobs with one query: active
   jobs with `next_run_at` NULL or past and no queued or running run (`NOT EXISTS`),
   ordered `next_run_at NULLS FIRST`, limited to `CONNECTOR_SYNC_POLL_BATCH_SIZE`, locked
   `FOR UPDATE SKIP LOCKED` on PostgreSQL. A NULL `next_run_at` (jobs from before 0.6.0)
   is decided once with the 0.5 rule (`last_run_at + interval`) and stored. After a queued
   run is created, `next_run_at = now + interval` (5 to 10,080 minutes). `manual_only`
   jobs get `9999-01-01` and are never polled again; manual and full-resync triggers do
   not read `next_run_at`.
2. **Lease.** `connectors.sync.run` leases the run with a conditional `UPDATE`: the run is
   `queued`, or `running` with no owner, the same owner (Celery redelivery or retry of the
   same message, whose request id is the owner), or a `heartbeat_at` older than
   `CONNECTOR_SYNC_STALE_SECONDS`. The lease transaction also loads and refreshes the
   credential. A finished or cancelled run is not run again.
3. **Pages.** The provider call runs with no transaction open. Then one transaction per
   page writes the items, sets `external_items.last_seen_sync_run_id = run.id` for every
   item the page returned (one `UPDATE`, unchanged items included), creates documents for
   changed file items with one outbox row each (`documents.process`, dedupe key
   `connector:{run_id}:{document_id}`), and moves `checkpoint_cursor` (the cursor of the
   next page), `checkpoint_at`, `pages_committed`, the counters, and `heartbeat_at`
   forward. The update is conditional on the lease owner, so a worker that lost its lease
   rolls its page back and stops. The outbox rows are published right after the commit
   (`outbox.relay` publishes any left pending).
4. **Finish.** A full sync tombstones, in batches of `CONNECTOR_SYNC_TOMBSTONE_BATCH_SIZE`,
   live items of the connection whose `last_seen_sync_run_id` is not this run (and whose
   `sync_version` is not newer). Nothing is kept in memory, so a resumed run never
   tombstones what an earlier attempt saw. Incremental syncs keep their delta semantics:
   deletes and permission revocations are tombstoned as they arrive. Completion writes
   `cursor_after`, `job.cursor_json`, and the success audit.

**Resume.** A `running` run with a checkpoint continues from `checkpoint_cursor` with its
persisted counters: after a worker restart (broker redelivery, or the
`connectors.sync.reap` sweep, which re-enqueues running runs with a stale heartbeat every
`CONNECTOR_SYNC_REAP_INTERVAL_SECONDS`), or after a long Retry-After. When paging is done
the checkpoint is `{"_rudix_phase": "finalize", "cursor_after": ...}`, so a resumed full
sync only tombstones and completes.

**Cancel.** `POST /api/v1/connectors/sync-runs/{id}/cancel` sets `cancelled` as before. The
run checks its status with a fresh query before each page and every
`CONNECTOR_SYNC_CANCEL_CHECK_ITEMS` items (default 50) inside a page, commits the work it
has done, frees the lease, and stops. Committed pages and the checkpoint stay.

**Rate limits.** A `ConnectorRateLimitError` with a Retry-After of at most
`CONNECTOR_SYNC_MAX_INLINE_BACKOFF_SECONDS` (default 60) is slept inside the run, with a
heartbeat at least every 15 seconds, and the same page is retried up to
`CONNECTOR_SYNC_MAX_INLINE_RETRIES` times (default 5). A longer one (or exhausted retries)
keeps the checkpoint, leaves the run `running` with no lease owner and `heartbeat_at` set to
the resume time, and re-enqueues `connectors.sync.run` with `countdown = retry_after`. The
run is not failed.

**Caps.** `CONNECTOR_SYNC_MAX_CONCURRENT_PER_ORG` and
`CONNECTOR_SYNC_MAX_CONCURRENT_PER_CONNECTION` (default 0, no cap) limit runs per
organization and connection. The poll skips jobs over a cap (queued and running runs
count). At lease time running runs with a fresh heartbeat count, serialized by a
transaction-scoped advisory lock on PostgreSQL; a run over a cap stays `queued` and the
task re-enqueues it after `CONNECTOR_SYNC_CAP_RETRY_SECONDS`.

**Tenancy.** Every query is scoped by the run's organization and connection. Items an
adapter returns for another organization or connection are skipped
(`connector.sync.item.tenant_mismatch` log, `rudix_worker_tenant_mismatch_total`), and the
task runs bound to its `organization_id` (contract 4.2.7).

`run_sync(session, ...)` with a session the caller holds still works: every unit then
runs on that session and only flushes, and the caller commits (the 0.5 single-transaction
behaviour, used by tests and tools). `SyncRunResult.pending_document_ids` stays empty and
is deprecated; documents are dispatched through the outbox.

Known limits: file downloads and the ingestion bridge (malware scan, object storage
upload) still run inside the page transaction, as in 0.5. Real provider rate limits are a
staging check.

## Observability and Rollout Controls

Connector operators should use the admin health endpoint to inspect provider
health, sync failures, retry patterns, skipped items, ingestion failures, and
citation usage:

- `GET /api/v1/admin/connectors/health`

The health response is organization-scoped and reports:

- rollout state
- overall platform status
- connection, sync, and retry totals
- provider-specific error codes and latency
- document and citation usage derived from connector provenance

Runtime rollout is controlled by:

- `FEATURE_ENABLE_CONNECTORS`
- `CONNECTOR_ROLLOUT_STAGE`

Recommended rollout stages:

- `off` for shutdown or rollback
- `development` for local and dev deployments
- `staging` for pre-production validation
- `production` for live production enablement
- `all` for deployments where the platform should be active everywhere except test

New providers should pass the shared contract suite before merging. The
contract harness exercises provider fixtures and adapter behavior for
Confluence, Google Drive, and the fake provider used in CI.

Provider-specific code must stay in connector adapters. Shared ingestion and
chat services should depend only on `documents`, chunks, citations, and
provider-neutral source references.

## Security Boundaries

Connector operations must:

- require organization-scoped lookups for every connection, source, item, job,
  run, source document, reference, and tombstone
- validate that any `collection_id` belongs to the same organization
- validate that source documents link only to documents from the same organization
- store tokens and secrets outside public response payloads and logs
- expose only safe credential metadata and diagnostics to frontend APIs
- refresh expired OAuth tokens through shared lifecycle code before sync
- mark revoked credentials unusable and disable future sync jobs on disconnect
- retain ACL metadata as hashes or compact permission snapshots, not full raw
  provider permission exports unless explicitly needed
- treat external content as untrusted document text during ingestion and RAG

MCP and agent tooling must not bypass connector domain services. Side-effect
connector sync operations remain API or worker operations unless explicitly
approved for another surface.
