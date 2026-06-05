# 16 — Connector Platform

## Objective

The connector platform gives Jira, Confluence, Google Drive, and future providers
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
| `external_sources` | Provider containers such as Jira projects, Confluence spaces, Drive folders, or shared drives |
| `external_items` | Normalized issues, pages, files, folders, comments, and attachments |
| `connector_sync_jobs` | Durable sync configuration and cursor state |
| `connector_sync_runs` | Per-run lifecycle, counters, cursors, and safe error details |
| `source_documents` | Mapping from normalized external items to Rudix `documents` rows |
| `source_references` | Provider-neutral citation/source locators tied to documents and optional chunks |
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

The default registry includes Jira, Confluence, and Google Drive. New providers
can be registered by constructing a `ProviderRegistration` and calling
`ProviderRegistry.register()` or `ConnectorPlatformService.register_provider()`.

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

- Jira issues, comments, and attachments
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
   branches to chat, citation, retrieval, or prompt services.

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
- retain ACL metadata as hashes or compact permission snapshots, not full raw
  provider permission exports unless explicitly needed
- treat external content as untrusted document text during ingestion and RAG

MCP and agent tooling must not bypass connector domain services. Side-effect
connector sync operations remain API or worker operations unless explicitly
approved for another surface.
