# 07 — API Design

## Reports API (F349)

### Answer quality report (F351)

`GET /api/v1/reports/answer-quality` returns the reviewer/admin answer-quality read model:
aggregate confidence and citation metrics, confidence distribution, daily trends, low-confidence
collections, bad-feedback categories, and a paginated answer table. It accepts bounded `from`/`to`
ranges plus `collection_id`, `source_id`, `user_id`, `warning`, `confidence`, `sort`, `direction`,
`page`, and `page_size` filters.

`GET /api/v1/reports/answer-quality/{message_id}` returns the question, final answer, confidence
reasons, warnings, feedback/evaluation links, and only those cited sources the viewer may access.
Both endpoints require `reviewer`, `admin`, or `owner`; inaccessible or cross-organization details
return `404`.

`POST /api/v1/reports/events` records a typed, content-free reporting fact. Supported
categories are question, answer, citation, confidence, feedback, indexing,
connector sync, permission, export, and audit. The strict request schema rejects
unknown fields, so questions, answers, source text, snippets, credentials, and
arbitrary metadata cannot enter or leave the reporting store.

`GET /api/v1/reports` returns a stable envelope with `metrics`, `chart`, `table`,
`action_items`, and `pagination`. Both endpoints require an organization owner or
admin. Organization scope always comes from the authenticated principal and cannot
be overridden by a query parameter.

Filters: `from`, `to`, `category`, `workspace_id`, `collection_id`, `connector_id`,
`user_id`, `team_id`, and `source_id`. Table controls: `page` (1-based), `page_size`
(maximum 200), `sort`, and `direction`. Date ranges are limited to 366 days. The
event table has composite tenant/date indexes for the high-cardinality dimensions.

Report rows contain identifiers and numeric operational facts only; they never
contain filenames, source titles/URLs, questions, answers, citations snippets, or
document content. Frontends must resolve any source label through its existing
permission-checked source endpoint.

FastAPI exposes the production backend API.

## API principles

1. Every endpoint must verify authentication unless it is explicitly documented
   as a public endpoint.
2. Every document operation must check organization membership.
3. Long-running work must be handled by Celery.
4. API responses must be typed with Pydantic schemas.
5. Errors must use consistent JSON format.
6. File access must use signed URLs or backend proxying.
7. Query endpoints must apply Qdrant metadata filters.

## Common headers

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

## Authentication

Rudix supports two auth modes:

- external identity providers handled through JWT verification
- app-managed auth with database-backed passwords, JWT access tokens, and HttpOnly refresh cookies

### App auth session flow

#### POST `/auth/login`

Authenticates a user with email and password.

- Returns an access token plus session metadata, including `session_id`
- Sets the refresh token in an HttpOnly cookie
- Locks accounts after repeated failed logins

#### POST `/auth/token/refresh`

Rotates the refresh session using the HttpOnly cookie.

- Reads the refresh token from the cookie first
- Falls back to the request body only for compatibility
- Replaces the old refresh session with a new one
- Returns a new access token plus session metadata

#### POST `/auth/logout`

Revokes the current refresh session and clears the cookie.

#### POST `/auth/logout-all`

Revokes every active refresh session for the authenticated user.

#### GET `/auth/session`

Returns the current authenticated session state derived from the bearer token.

#### GET `/auth/sessions`

Returns the active refresh sessions for the authenticated user.

#### SSO callback redirects

When the SAML callback is received as a browser form post, the backend issues the refresh cookie and redirects to the frontend callback route with access-token/session metadata in the query string. API clients can still receive JSON when they do not send a browser-form payload.

## Error format

Every error response (HTTP errors, request validation failures, and unhandled exceptions) uses
one envelope:

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document not found",
    "request_id": "0b9f6c1e-6a52-4a52-9f0c-3e1f6f7a1a11",
    "details": null
  },
  "detail": "Document not found"
}
```

- `error.code` is a stable machine-readable code. It is resolved from, in order: a structured
  `detail` that already carries `code` or `error` (kept verbatim, for example
  `rate_limit_exceeded`, `plan_limit_exceeded`), the registry of frequent messages in
  `backend/app/core/error_codes.py` (for example `DOCUMENT_NOT_FOUND`, `INVALID_CURSOR`,
  `CURSOR_SORT_UNSUPPORTED`), and a status fallback: `400 BAD_REQUEST`, `401 UNAUTHENTICATED`,
  `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT`, `413 PAYLOAD_TOO_LARGE`,
  `422 VALIDATION_ERROR`, `429 RATE_LIMITED`, `500 INTERNAL_ERROR`, `501 NOT_IMPLEMENTED`,
  `503 SERVICE_UNAVAILABLE`.
- `error.request_id` echoes `X-Request-ID` (or the generated id) and is also returned as a response
  header. Quote it when reporting a problem.
- `error.details` carries structured detail: the validation error list for `422`, the structured
  object for dict details, otherwise `null`.
- `detail` is a compatibility alias with exactly the value the API returned before the envelope
  existed (string, validation list, or structured object). It is kept until `1.0.0`; new clients
  should read `error`.
- Response headers set by the failing handler (`WWW-Authenticate`, `Retry-After`,
  `X-RateLimit-*`) are preserved.
- Unhandled exceptions return `500` with `INTERNAL_ERROR` and a generic message. Exception text and
  stack traces are never returned; they are logged server-side and reported to Sentry.

### Chat error codes

Since `0.5.0` every error the chat routes (`/chat/*`, `app/interfaces/http/chat*.py` and the
chat pipeline) raise has its own code; none falls back to the status code
(`tests/test_chat_error_codes_registry.py` checks every raise site). The lower-snake codes are
structured details that existed before the registry and are not renamed: codes are a public
contract.

| Status | `error.code` | When |
|---|---|---|
| 403 | `plan_limit_exceeded` | The organisation's question quota is used up (`POST /chat`, WebSocket). |
| 403 | `NO_ACTIVE_ORGANIZATION_CONTEXT_FOR_PRINCIPAL`, `PRINCIPAL_IDENTITY_CONTEXT_IS_INVALID` | The principal has no usable organisation or user id. |
| 403 | `SHARE_LINK_PASSWORD_REQUIRED` | A password-protected answer share was opened without the right password. |
| 403 | `SHARE_LINK_USER_NOT_ALLOWED` | The viewer is not in the answer share's allowed-users list. |
| 404 | `document_not_found` | `POST /chat` names a document the caller cannot see. |
| 404 | `chat_session_not_found` | `POST /chat` names a malformed, foreign, or unknown session. |
| 404 | `CHAT_SESSION_NOT_FOUND` | Session, message-list, share, and feedback routes with an unknown session. |
| 404 | `message_not_found`, `trust_metadata_not_available` | `GET /chat/messages/{id}/trust-metadata`. |
| 404 | `MESSAGE_NOT_FOUND`, `FEEDBACK_NOT_FOUND` | Feedback and answer-share routes. |
| 404 | `SHARE_NOT_FOUND` | Revoking an unknown session or answer share. |
| 404 | `SHARE_LINK_NOT_FOUND_EXPIRED_OR_REVOKED` | `GET /chat/shared/{token}`, `GET /chat/answer-shared/{token}`. |
| 422 | `CHAT_SHARE_LIMIT_REACHED`, `ANSWER_SHARE_LIMIT_REACHED` | More than 10 active share links per session or per answer. |
| 422 | `SHARE_ALLOWED_USER_IDS_REQUIRED` | `access_mode = "specific_users"` with an empty `allowed_user_ids`. |
| 429 | `rate_limit_exceeded` | Chat rate limit (`Retry-After` is set). |
| 429 | `provider_busy` | The organisation's concurrent LLM call limit stayed reached (`POST /chat`, WebSocket; R05-06). |
| 500 | `chat_persistence_failed` | The answer could not be saved. |
| 501 | `CHAT_MESSAGE_CREATE_NOT_IMPLEMENTED` | Deprecated `POST /chat/sessions/{id}/messages`. |
| 503 | `retrieval_failed`, `generation_failed`, `prompt_template_unavailable` | Retrieval, the model provider, or the prompt template is unavailable. |
| 503 | `chat_websocket_disabled`, `ws_ticket_unavailable` | `POST /chat/ws-ticket` when WebSocket chat or the ticket store is off. |

The activity-step details `No relevant answer found`, `No indexed files found`, and
`Request could not be processed` are registered too (`NO_RELEVANT_ANSWER_FOUND`,
`NO_INDEXED_FILES_FOUND`, `REQUEST_COULD_NOT_BE_PROCESSED`), so a client that shows them can map
them the same way.

## Pagination

List endpoints keep `limit`/`offset` paging. Since `0.4.0` the endpoints below also accept a
keyset cursor: the next page starts after the last row of the previous one, so the database
does not read and discard the `offset` rows before it (R04-04).

| Endpoint | Cursor order |
|---|---|
| `GET /chat/sessions` | `updated_at` desc, `id` desc |
| `GET /chat/sessions/{session_id}/messages` | `created_at` asc, role (user before assistant), `id` asc; reversed with `order=desc` |
| `GET /documents` | `created_at` (direction from `sort_order`), `id` desc; only with `sort_by=created_at` |
| `GET /notifications` | `created_at` desc, `id` desc |
| `GET /admin/audit-logs` | `created_at` desc, `id` desc |
| `GET /admin/webhooks/{webhook_id}/deliveries` | `created_at` desc, `id` desc |

Contract:

- Every response of these endpoints carries `next_cursor` (string or `null`). It is `null` on
  the last page. Pass it back unchanged as `?cursor=...` with the same filters and sort to get
  the next page. The first page needs no cursor, so a client can start with `offset=0` and
  follow `next_cursor`.
- Cursors are opaque: base64url-encoded, versioned, and bound to the endpoint's sort order.
  Do not build or parse them. A cursor carries only the sort-key values of the last row; the
  organization and user filters are always applied on the server, so a cursor from one
  organization returns nothing from it when used by another.
- `include_total` controls the `total` count query. It defaults to `true` without a cursor
  (the behaviour before `0.4.0`) and to `false` with a cursor; when it is `false`, `total` is
  `null`. `GET /notifications` always returns `unread_count`. `GET
  /admin/webhooks/{webhook_id}/deliveries` has no count query: its `total` is the number of
  items in the page, as before, and it now accepts `limit` (1 to 200, default 50).
- `offset` keeps working. A cursor together with `offset > 0` is rejected.
- `GET /chat/sessions` orders by `updated_at`: a session that changes between two requests
  moves to the top, so a cursor walk can skip or repeat it.
- On `GET /documents`, non-admin results are filtered by document policy after the page is
  read, so a page can hold fewer than `limit` items while `next_cursor` is still set.

Errors (HTTP `400`):

| `detail` | Cause | `error.code` |
|---|---|---|
| `Invalid pagination cursor` | Malformed, tampered, wrong version, or from another sort order | `INVALID_CURSOR` |
| `Cursor pagination requires sort_by=created_at` | `GET /documents` with a cursor and another `sort_by` | `CURSOR_SORT_UNSUPPORTED` |
| `Cursor pagination cannot be combined with offset` | `cursor` with `offset > 0` | `BAD_REQUEST` (status fallback) |

A `cursor` longer than 1024 characters fails request validation (`422`).

The admin exports `GET /admin/usage/export` (at most 50,000 rows) and
`GET /admin/audit-logs/export` (at most 10,000 rows) stream their body with the row limit
applied in SQL. The CSV and JSON bytes are the same as before. Headers are sent before rows are
read, so a database failure during an export cuts the body short instead of returning an
error status; the failure is logged as `admin.export.streamed` with `status=failed`.

## Quotas and plan limits

- Usage counters are kept per organization and quota type. Each increment runs as one atomic
  database upsert, so concurrent requests never lose updates.
- Windowed quotas (`per_minute`, `per_hour`, `per_day`, `per_month`) reset once per window. The
  reset is a conditional update that only matches an expired row, so concurrent requests cannot
  reset the same window twice. Quotas with `reset_window: none` are permanent caps and never reset.
- Known limit: the quota check and the usage increment are separate steps in a request, so a
  burst of concurrent requests can overshoot a hard limit by the number of requests in flight.
  Closing this gap is planned for a later release.
- When a hard limit would be exceeded, the API returns HTTP `403` with
  `detail.code = "plan_limit_exceeded"` and safe metadata: `quota_type`, `current_value`,
  `requested_amount`, `soft_limit`, `hard_limit`, `reset_window`, `next_reset_at`, `retryable`,
  and `action`.

## Health

### GET `/health`

Response:

```json
{
  "status": "ok",
  "timestamp": "2026-05-07T10:00:00Z",
  "dependencies": {},
  "failed_dependencies": []
}
```

### GET `/status`

Returns the public Rudix service status snapshot used by the public `/status`
marketing page.

- Does not require authentication.
- Returns public-safe component, incident, maintenance, and recent-history data.
- Omits tenant identifiers, internal hostnames, logs, and dependency details.
- Can source incident data from the organization named by
  `PUBLIC_STATUS_ORGANIZATION_SLUG` when configured.

Response:

```json
{
  "generated_at": "2026-06-20T10:00:00Z",
  "overall_status": "operational",
  "headline": "All systems operational",
  "summary": "Rudix services are operating normally.",
  "components": [
    {
      "key": "api",
      "label": "API",
      "status": "operational",
      "summary": "Rudix services are operating normally.",
      "affected_services": [],
      "updated_at": null
    }
  ],
  "current_incidents": [],
  "scheduled_maintenance": [],
  "recent_history": [],
  "uptime_notice": "Status updates are published for transparency and do not imply an SLA unless one is explicitly contracted."
}
```

### GET `/ready`

Checks PostgreSQL, Redis, RabbitMQ, MinIO, Qdrant, and OpenAI configuration.

- Returns `200` when all checks pass.
- Returns `503` when one or more checks fail.

Response:

```json
{
  "status": "degraded",
  "timestamp": "2026-05-07T10:00:00Z",
  "dependencies": {
    "postgres": {
      "ok": false,
      "detail": "postgres_unreachable",
      "metadata": { "dsn": "postgresql+asyncpg://db:5432/rag_app" }
    },
    "redis": {
      "ok": true,
      "detail": null,
      "metadata": { "url": "redis://redis:6379/0" }
    },
    "rabbitmq": {
      "ok": true,
      "detail": null,
      "metadata": { "url": "amqp://rabbitmq:5672//" }
    },
    "minio": {
      "ok": true,
      "detail": null,
      "metadata": { "endpoint": "http://minio:9000", "bucket": "documents" }
    },
    "qdrant": {
      "ok": true,
      "detail": null,
      "metadata": { "url": "http://qdrant:6333", "collection": "documents" }
    },
    "openai_config": {
      "ok": true,
      "detail": null,
      "metadata": {
        "api_key_set": true,
        "embedding_model": "text-embedding-3-small",
        "llm_model": "gpt-5.4-mini"
      }
    }
  },
  "failed_dependencies": ["postgres"]
}
```

### POST `/contact`

Accepts validated submissions from the public `/contact` marketing form.

- Does not require authentication.
- Applies a public Redis-backed IP rate limit using `RATE_LIMIT_CONTACT_REQUESTS`.
- Persists every valid submission in `contact_submissions` before attempting
  email delivery.
- Sends the notification to `CONTACT_RECEIVER_EMAIL` through the configured
  transactional email provider when `EMAIL_ENABLED=true`.
- Uses the submitter email as `reply_to`; provider `from` stays controlled by
  `EMAIL_FROM_ADDRESS`.
- Does not persist CAPTCHA tokens or honeypot values.
- Returns safe provider-independent errors: `503` when delivery is not
  configured, `502` when provider delivery fails, and `429` when rate-limited.

Request:

```json
{
  "full_name": "Alex Rivera",
  "work_email": "alex@example.com",
  "company": "Acme Legal",
  "role_title": "Head of Knowledge",
  "use_case": "Legal document Q&A",
  "team_size": "51-250",
  "message": "We want a demo focused on citations and governance.",
  "consent_accepted": true,
  "captcha_token": "optional-provider-token",
  "source": "public_contact_page"
}
```

Response:

```json
{
  "submission_id": "0b8c8d4e-2b7f-49f5-94af-62d3b8307f3e",
  "status": "received",
  "email_status": "sent"
}
```

## Documents

### POST `/documents/upload`

Upload a document.

Request:

```http
multipart/form-data
file=<PDF|TXT|DOCX>
language=<en|de|es|fr>
```

Response:

```json
{
  "document_id": "uuid",
  "filename": "policy.pdf",
  "status": "uploaded",
  "queue_status": "queued",
  "checksum": "<sha256-hex>",
  "message": "Document uploaded and queued for processing."
}
```

Backend actions:

1. Verify token.
2. Enforce role check and upload rate limit.
3. Validate file extension and MIME type.
4. Validate file size and reject empty payloads.
5. Compute SHA-256 checksum.
6. Scan upload bytes with ClamAV (`clamd` INSTREAM) before persistence.
7. If scan status is `infected`, return `422` with safe message `File failed security scan`, emit structured log, and write audit action `document.upload.rejected_malware`.
8. If scanner is unavailable:
   - When `MALWARE_SCAN_REQUIRED=true`, fail closed with `503` and safe message `File security scan unavailable`.
   - In non-production only, bypass is allowed when `MALWARE_SCAN_BYPASS_ON_UNAVAILABLE=true` and unavailability category is transient.
9. Generate a `document_id` and MinIO object key: `uploads/{organization_id}/{user_id}/{document_id}.{ext}`.
10. Upload to MinIO.
11. Insert `documents` row with status `uploaded`, bucket/object key, and checksum.
12. Publish `documents.process` task with `document_id`, `organization_id`, `user_id`, and `request_id`.
13. Worker extracts text by file type and normalizes page text (null-byte/control-char cleanup and whitespace normalization).
14. Worker stores `document_pages(page_number, text, char_count)` with page boundaries preserved.
15. Worker chunks cleaned pages with configured token size/overlap and stores `document_chunks` metadata (`page_number`, `chunk_index`, `token_count`, `embedding_model`, `index_version`).
16. If chunk windows span page boundaries, chunk `page_number` is attributed to the dominant page in the window for citation safety.
17. Worker generates embeddings for all chunks in provider-safe batches using the configured embedding model.
18. Transient embedding provider failures are retried with backoff; permanent embedding failures mark document `failed`.
19. Worker upserts embeddings to Qdrant in batches using deterministic UUIDv5 point IDs derived from `{document_id}:{index_version}:{chunk_index}`.
20. Qdrant payload includes filter/citation fields: `organization_id`, `user_id`, `document_id`, `chunk_id`, `filename`, `file_type`, `page_number`, `chunk_index`, `text`, `embedding_model`, `index_version`.
21. Worker records embedding usage telemetry (`input_tokens`, `latency_ms`, approximate `cost_usd`) in `usage_events` for downstream billing/analytics integration.
22. On successful extraction/chunking/embedding/index upsert, document status becomes `indexed`; empty/malformed extraction marks document `failed`.
23. Worker logs cleaning/chunking/embedding stats (`cleaning_*`, `chunk_count`, `index_version`, `embedding_*`) for pipeline observability.
24. Worker persists `pipeline_runs` + `pipeline_events` rows for node-level lifecycle visibility (`extract`, `index_cleanup`, `chunk`, `embed`, `index`).
25. Event payloads store sanitized previews (`inputs`, `outputs`, `config`, `logs`, `error_details`) and redact secret-like fields.
26. Terminal failures persist a safe `error_message` and structured `error_details` for frontend status polling.

Queue publish failure behavior:

- Upload remains persisted with document status `uploaded` so processing can be retried.
- API returns `503` with a safe enqueue-failure message.

Security scan failure behavior:

- Malware detection returns `422` and does not persist the object or document row.
- Scan-unavailable failures use safe `503` responses when required mode is enabled.
- Audit metadata remains safe-only (`filename`, `file_type`, `file_size_bytes`, `checksum`, scanner fields, request/user/org IDs).

Duplicate policy:

- Duplicate uploads are currently accepted as separate documents. Each upload gets a new `document_id` and object key even when checksum matches a previous upload.

### GET `/documents`

## Enterprise Graph

When `enterprise_graph_enabled=true`, the backend exposes admin-only graph
operations under `/admin/graph` for owners and admins.

Member-facing graph explorer reads are exposed separately under `/graph`.
These routes are organization-scoped, read-only, and return `503` with the
safe detail `enterprise_graph_unavailable` when the graph layer is disabled or
Neo4j is not reachable.

### Graph explorer

- `GET /graph/entities` searches evidence-backed entities with `query`,
  `entity_type`, `min_confidence`, `source_document_id`, `source_connector`,
  `rel_type`, `relationship_direction`, `skip`, and `limit` filters.
- `GET /graph/entities/{entity_id}` returns entity detail with aliases,
  evidence links, relationships, connected documents, connected entities, and
  summary counts.

Both endpoints require an authenticated principal, enforce organization scope,
and only return graph records derived from evidence-backed sources.

### Relation provenance

- `POST /admin/graph/evidence` creates evidence links for entity provenance.
- `GET /admin/graph/documents/{document_id}/provenance` returns document-level
  evidence chains.
- `GET /admin/graph/entities/{entity_id}/citations` returns citation-ready
  evidence for an entity.

### Relation management

- `GET /admin/graph/relations` lists relations with optional `status`,
  `rel_type`, `workspace_id`, and `min_confidence` filters.
- `POST /admin/graph/relations` creates evidence-backed relations only.
- `GET /admin/graph/relations/{relation_id}` fetches a single relation.
- `PATCH /admin/graph/relations/{relation_id}/status` updates review state.
- `DELETE /admin/graph/relations/{relation_id}` deletes a relation by stable id.

### Entity canonicalization

- `GET /admin/graph/entities/{entity_id}/aliases` lists alias/source-mention
  records for a canonical entity.
- `GET /admin/graph/entity-resolution/candidates` lists likely matches for
  review using org-scoped entity resolution heuristics.
- `POST /admin/graph/entity-resolution/merge` records a manual merge decision.
- `POST /admin/graph/entity-resolution/split` records a manual split decision.

Entity resolution is organization-scoped and only uses derived graph data. Low
confidence candidates are not auto-merged; they remain available for review.

Relation states are `unverified`, `verified`, `rejected`, and
`low_confidence`. Low-confidence relations are still stored with evidence and
can be excluded from GraphRAG by downstream filters.

List documents.

Query params:

```text
status=indexed
limit=50
offset=0
sort_by=created_at|updated_at|filename|status
sort_order=asc|desc
```

Response:

```json
{
  "limit": 50,
  "offset": 0,
  "status": "indexed",
  "sort_by": "filename",
  "sort_order": "asc",
  "items": [
    {
      "document_id": "uuid",
      "filename": "policy.pdf",
      "file_type": "pdf",
      "status": "indexed",
      "graph_extraction_status": "completed",
      "page_count": 24,
      "chunk_count": 92,
      "error_message": null,
      "error_details": null,
      "updated_at": "2026-05-07T10:05:00Z",
      "created_at": "2026-05-07T10:00:00Z"
    }
  ],
  "total": 1
}
```

### GET `/documents/{document_id}`

Returns document metadata and current lifecycle state.

Response:

```json
{
  "document_id": "uuid",
  "filename": "policy.pdf",
  "file_type": "pdf",
  "status": "processing",
  "graph_extraction_status": "extracting",
  "language": "en",
  "page_count": 24,
  "chunk_count": 92,
  "checksum": "sha256:...",
  "error_message": null,
  "error_details": null,
  "chunking_diagnostics": {
    "strategy": "adaptive_hybrid",
    "selected_strategy": "page_aware",
    "profile_source": "custom_profile",
    "profile_version": "1.0",
    "chunk_size_tokens": 700,
    "chunk_overlap_tokens": 120,
    "ocr_applied": true,
    "reason_codes": ["pdf_ocr_applied"],
    "token_distribution": {
      "min_tokens": 120,
      "max_tokens": 260,
      "avg_tokens": 188.5,
      "total_tokens": 7917
    }
  },
  "lifecycle_timeline": [
    {
      "step": "extract",
      "label": "Extract",
      "description": "Extract raw text and metadata from source files.",
      "status": "completed",
      "document_id": "uuid",
      "pipeline_run_id": "uuid",
      "pipeline_type": "document.process",
      "started_at": "2026-05-07T10:01:00Z",
      "completed_at": "2026-05-07T10:01:03Z",
      "duration_ms": 3000,
      "logs": ["extracted 24 pages"]
    }
  ],
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:04:00Z"
}
```

Notes:

- `chunking_diagnostics` is nullable for documents indexed before diagnostics were recorded.
- The diagnostics payload is safe for UI display: it contains strategy metadata, heuristics, and aggregate counts only.
- `language`, `language_source`, `language_confidence`, `ocr_languages_override`, and `ocr_quality_snapshot` power the multilingual troubleshooting UI and should remain safe for display.

### PATCH `/admin/documents/{document_id}/language`

Override the detected document language for admin troubleshooting.

Request:

```json
{
  "language": "fr"
}
```

Notes:

- Restricted to `owner` and `admin` roles.
- Accepts `en`, `de`, `es`, `fr`, or `null` to clear the override.
- Updates `language_source` to `admin_override`.

### PATCH `/admin/documents/{document_id}/ocr-config`

Override OCR language selection for a document.

Request:

```json
{
  "ocr_languages": ["fr", "en"]
}
```

Notes:

- Restricted to `owner` and `admin` roles.
- Accepts `en`, `de`, `es`, `fr`, or `null` to clear the override.
- Languages are validated before being converted to the internal Tesseract
  code string.

### GET `/documents/{document_id}/status`

Returns a compact status payload for polling-only clients, including the
latest graph extraction state.

Response:

```json
{
  "document_id": "uuid",
  "status": "processing",
  "graph_extraction_status": "extracting",
  "error_message": null,
  "error_details": null,
  "updated_at": "2026-05-07T10:04:00Z"
}
```

### POST `/documents/{document_id}/graph/reindex`

Queue a graph-only re-extraction run for an existing document.

Response status: `202 Accepted`

Response:

```json
{
  "document_id": "uuid",
  "status": "pending",
  "queue_status": "queued"
}
```

Notes:

- Access is restricted to `owner` and `admin` roles.
- Re-run clears the previous graph facts for the document before rebuilding.
- Graph extraction failures are tracked separately from the base document
  lifecycle so non-graph ingestion still remains available if Neo4j is down.

Failed response example:

```json
{
  "document_id": "uuid",
  "status": "failed",
  "error_message": "qdrant upsert failed",
  "error_details": {
    "stage": "index",
    "code": "QDRANT_UPSERT_FAILED",
    "category": "infrastructure",
    "retryable": true,
    "message": "qdrant upsert failed"
  },
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:05:10Z"
}
```

### GET `/documents/{document_id}/chunks`

Returns paginated chunk previews.

Query params:

```text
limit=20
offset=0
include_full_text=false
```

Response:

```json
{
  "document_id": "uuid",
  "limit": 20,
  "offset": 0,
  "include_full_text": false,
  "items": [
    {
      "chunk_id": "uuid",
      "page_number": 4,
      "chunk_index": 12,
      "created_at": "2026-05-07T10:02:30Z",
      "text_preview": "Employees are entitled to...",
      "text": null,
      "token_count": 690,
      "embedding_model": "text-embedding-3-small",
      "index_version": "v1",
      "section_path": "Policy > Leave",
      "language": "en",
      "chunk_level": 0,
      "child_count": 0,
      "source_start_offset": 820,
      "source_end_offset": 1510
    }
  ],
  "total": 92
}
```

### GET `/documents/{document_id}/citations/{citation_id}/preview`

Returns a permission-filtered citation preview for a specific citation. This
endpoint is intended for rendering citation popovers and source inspectors in
the frontend.

Implementation notes, UI behavior, and regression fixtures are documented in
[docs/24_CITATION_PREVIEW_ARCHITECTURE.md](./24_CITATION_PREVIEW_ARCHITECTURE.md).

Response:

```json
{
  "citation_id": "uuid",
  "document_id": "uuid",
  "chunk_id": "uuid",
  "filename": "policy.pdf",
  "document_title": "policy.pdf",
  "document_type": "pdf",
  "document_owner_email": "owner@example.com",
  "document_version_label": "v3",
  "document_last_updated_at": "2026-05-20T08:30:00Z",
  "document_last_indexed_at": "2026-05-20T08:15:00Z",
  "page_number": 4,
  "chunk_index": 12,
  "section_path": "Policy > Leave",
  "source_section": "Section 4.1",
  "source_provider": "confluence",
  "source_provider_label": "Confluence",
  "source_title": "Leave policy",
  "source_key": "page-123",
  "source_url": "https://confluence.example.test/wiki/spaces/ENG/pages/123",
  "source_link_allowed": true,
  "document_url": "https://app.rudix.test/documents/uuid?chunk_id=uuid&citation=uuid",
  "snippet": "Employees are entitled to ...",
  "highlight_start_offset": 0,
  "highlight_end_offset": 29,
  "source_start_offset": 820,
  "source_end_offset": 1510,
  "source_last_synced_at": "2026-05-07T10:00:00Z",
  "source_content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "source_sync_version": 5,
  "source_visibility": "org_wide",
  "source_trust_status": "trusted",
  "freshness_state": "current",
  "doc_trust_status": "current",
  "doc_review_status": "current",
  "doc_version_label": "v3",
  "doc_unreviewed_warning": false,
  "doc_deprecated_warning": false,
  "doc_ocr_quality_status": "high",
  "doc_ocr_low_confidence_warning": false,
  "request_id": "req-123"
}
```

Behavior:

- Enforces organization membership, document access, collection permissions,
  and connector ACLs server-side before returning preview data.
- Supports uploaded documents and connector-backed sources.
- Shows source links only when the connector source is available to the current
  user; uploaded documents always fall back to the internal document link.
- Returns `404` with `detail.code = citation_not_found` when the citation does
  not exist, is malformed, or is not visible in the requested document scope.
- Returns `404` with `detail.code = citation_unauthorized` when the source is
  no longer accessible through connector ACLs.
- Returns `409` with `detail.code = citation_not_indexed` when the citation
  points at a document or chunk that is not yet indexed.
- Returns `409` with `detail.code = citation_stale` when the source is stale,
  expired, or otherwise no longer current enough for preview.
- Returns `410` with `detail.code = citation_deleted` when the source document
  or connector-backed item has been deleted or retained under deletion policy.
- Echoes the request identifier in both the response body and the
  `X-Request-ID` response header for troubleshooting.
- Never exposes hidden prompts, raw credentials, or chunks outside the user's
  authorization scope.

### DELETE `/documents/{document_id}`

Soft-delete a document and enqueue deletion of MinIO and Qdrant assets.

Response status: `202 Accepted`

Response:

```json
{
  "document_id": "uuid",
  "status": "deleting"
}
```

If the record is already deleted, the endpoint is idempotent and may return:

```json
{
  "document_id": "uuid",
  "status": "deleted"
}
```

### POST `/documents/{document_id}/reindex`

Queue a re-index run for an existing document.

Optional request body:

```json
{
  "chunking_profile_id": "uuid",
  "force": true
}
```

or

```json
{
  "chunking_profile_config": {
    "strategy": "page_aware",
    "chunk_size_tokens": 700,
    "chunk_overlap_tokens": 120,
    "language": "en",
    "min_tokens": 88,
    "strategy_options": {}
  }
}
```

Response status: `202 Accepted`

Response:

```json
{
  "document_id": "uuid",
  "status": "processing",
  "queue_status": "queued"
}
```

Conflict cases (`409 Conflict`):

- Document is already `processing` unless `force: true` is set.
- Document is `deleting`.
- Document is `deleted`.
- `force: true` only bypasses the `processing` guard for stuck jobs; it does not bypass delete/quarantine/blocked safety checks.

Notes:

- Access is restricted to `owner` and `admin` roles.
- Supply at most one override: `chunking_profile_id` or `chunking_profile_config`.
- Use `force: true` only to recover a document that is stuck in `processing`; normal re-index requests should omit it.
- Enqueue failure returns `503` and restores the previous document status/error fields.
- Re-index worker uses index-version scoped cleanup before upsert to keep retries idempotent:
  - Deletes prior Qdrant points for `{organization_id, document_id, index_version}`.
  - Rebuilds chunks/vectors for the active `index_version`.

## Chat

### POST `/chat/sessions`

Create a chat session.

Request:

```json
{
  "title": "Policy questions"
}
```

Response:

```json
{
  "session_id": "uuid",
  "title": "Policy questions",
  "message_count": 0,
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:00:00Z"
}
```

### GET `/chat/sessions`

List chat sessions for the active principal (organization + user scoped).

Query params:

```text
limit=20
offset=0
```

Response:

```json
{
  "limit": 20,
  "offset": 0,
  "total": 1,
  "items": [
    {
      "session_id": "uuid",
      "title": "Policy questions",
      "message_count": 2,
      "created_at": "2026-05-07T10:00:00Z",
      "updated_at": "2026-05-07T10:01:10Z"
    }
  ]
}
```

### GET `/chat/sessions/{session_id}`

Get a single chat session for the active principal.

Response:

```json
{
  "session_id": "uuid",
  "title": "Policy questions",
  "message_count": 2,
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:01:10Z"
}
```

### GET `/chat/sessions/{session_id}/messages`

List the messages of one of the caller's own chat sessions (R04-04 cursors, R05-11 order).

Query parameters:

| Name | Default | Notes |
|---|---|---|
| `order` | `asc` | `asc`: oldest first (conversation order, the behaviour before `0.5.0`). `desc`: newest first, for loading the latest page of a long history first. |
| `limit` | `200` | 1 to 500 |
| `offset` | `0` | Cannot be combined with `cursor` |
| `cursor` | none | `next_cursor` of the previous page in the same `order` |
| `include_total` | `true` without a cursor, `false` with one | |

- The sort key is `(created_at, role rank, id)` with the user turn before the assistant turn
  within one timestamp; `desc` walks the same key backwards, so a full `desc` walk is exactly
  the reversed `asc` walk.
- Items are returned in the order requested. A client that renders oldest at the top reverses
  each `desc` page.
- A cursor is bound to its order: an `asc` cursor sent with `order=desc` (or the reverse) is
  rejected with `400` `Invalid pagination cursor`.
- A session that does not exist, belongs to another user, or belongs to another organisation
  returns `404` `Chat session not found` in both orders.

Response:

```json
{
  "items": [
    {
      "message_id": "uuid",
      "role": "assistant",
      "content": "...",
      "confidence_score": 0.82,
      "confidence_category": "high",
      "citations": [],
      "created_at": "2026-05-07T10:01:10Z"
    }
  ],
  "total": null,
  "limit": 50,
  "offset": 0,
  "next_cursor": "opaque"
}
```

### POST `/chat`

Main real-time RAG query endpoint.

Request:

```json
{
  "question": "What is the leave policy?",
  "chat_session_id": "uuid-optional",
  "document_ids": ["uuid"],
  "top_k": 5,
  "rerank": true,
  "answer_language": "auto"
}
```

Notes:

- `rerank=true` applies provider-backed cross-encoder reranking on retrieved
  candidates before prompt construction when reranking is enabled by the active
  RAG profile.
- Rerank provider, model, timeout, batch size, input limit, and fallback
  behavior are controlled through the active RAG profile or the
  `RERANK_DEFAULT_*` environment settings.
- `rerank=false` skips the rerank pass and returns raw retrieval ordering
  (similarity-only) up to `top_k`.
- If reranking fails, times out, or the provider is unavailable, the backend
  falls back to the original retrieval order and records rerank diagnostics.
- When `FEATURE_ENABLE_GRAPH_RAG=true`, the backend may expand Qdrant hits with
  evidence-backed Neo4j context that is still scoped to the caller organization
  and allowed document IDs. Graph-only facts are not cited unless a matching
  document/chunk reference exists in the retrieved context.
- When `FEATURE_ENABLE_CONFLICT_DETECTION=true` or the active RAG profile sets
  `conflict_detection_enabled=true`, the backend compares retrieved sources
  before generation and returns conflict metadata when evidence disagrees.
- When `FEATURE_ENABLE_LANGUAGE_AWARE_RAG=true`, the backend detects the
  question language, resolves the answer language, and records both values in
  chat debug metadata.
- The chat response payload includes `agreement_level`, `conflict_detected`,
  `conflict_summary`, `conflicting_document_ids`, `preferred_document_ids`, and
  per-citation `conflict_status` metadata so the UI can warn about conflicts and
  compare sources safely.
- Debug telemetry includes conflict-detection latency and the preferred versus
  conflicting document sets for admin-visible diagnostics.
- Prompt builder enforces grounded-only behavior: no outside knowledge, no fake citations, and explicit treatment of retrieved document text as untrusted input.
- Answer language instructions must not rewrite citation text; citations always
  refer back to source chunk text exactly as stored.
- The active `answer_generation` prompt template version is resolved per organization and persisted on assistant chat messages for rollback/evaluation traceability.
- Prompt context blocks include source metadata (`document_id`, `chunk_id`, `filename`, `page_number`) plus retrieval metadata (`similarity_score`, `original_rank`, `rerank_score`, `rerank_rank`, `final_rank`) and an explicit allowed chunk ID list for citation validation.
- LLM is instructed to return strict JSON (`answer`, `not_found`, `citations`) for deterministic downstream parsing.
- Backend requests JSON mode when supported by the selected model/provider and transparently retries without JSON mode for providers that do not support `response_format`.
- If model output is still not valid structured JSON after retries, backend falls back to a safe not-found response (no citations).
- Model citations are validated against retrieved final context: chunk IDs must exist, filename/page are repaired from authoritative chunk metadata, and quote snippets must match chunk text (exact/fuzzy) or are replaced with safe chunk snippets.
- When model citations are missing or invalid, backend falls back to top retrieved chunks as citations (unless `not_found=true`).
- Citation validation quality contributes to final confidence scoring.
- On success, question/answer/citations and assistant telemetry (`latency_ms`, `model_name`, token counts, `cost_usd`) are persisted transactionally to `chat_messages`/`citations`.
- A `usage_events` row (`event_type=chat.completion`) is recorded transactionally for billing/admin analytics with latency, confidence, and retrieval metadata.
- Trust metadata also stores a safe `query_interpretation` snapshot for advanced diagnostics: intent, retrieval strategy, complexity, optional rewrite preview, and sub-questions. It does not include prompts or chain-of-thought, and org admins can disable the rewrite preview flag.
- LLM stage metrics include latency, token counts, model name, and approximate cost telemetry for orchestration persistence.

Response:

```json
{
  "chat_session_id": "uuid",
  "message_id": "uuid",
  "answer": "Employees receive 20 paid leave days per year.",
  "confidence_score": 0.89,
  "confidence_category": "high",
  "confidence_explanation": {
    "top_similarity": 0.89,
    "average_similarity": 0.84,
    "top_rerank_score": 0.91,
    "citation_support_score": 1.0,
    "citation_validation_score": 1.0,
    "citation_coverage_score": 1.0,
    "retrieval_agreement_score": 0.96,
    "raw_score": 0.89,
    "citation_validation_multiplier": 1.0,
    "not_found_penalty_multiplier": 1.0,
    "no_context": false,
    "not_found_signal": false,
    "weights": {
      "top_similarity": 0.35,
      "average_similarity": 0.2,
      "rerank_score": 0.2,
      "citation_support": 0.15,
      "agreement": 0.1
    },
    "thresholds": {
      "medium": 0.5,
      "high": 0.8
    }
  },
  "not_found": false,
  "citations": [
    {
      "document_id": "uuid",
      "chunk_id": "uuid",
      "filename": "policy.pdf",
      "page_number": 4,
      "score": 0.91,
      "similarity_score": 0.89,
      "original_rank": 3,
      "rerank_score": 0.91,
      "rerank_rank": 1,
      "final_rank": 1,
      "text_snippet": "Employees receive 20 paid leave days..."
    }
  ],
  "query_interpretation": {
    "intent": "policy",
    "intent_label": "Policy",
    "complexity": "simple",
    "retrieval_strategy": "decompose",
    "rewrite_preview_enabled": true,
    "rewritten_query_preview": "leave policy for contractors",
    "sub_queries": [
      "What is the leave policy?",
      "Who qualifies for leave?"
    ]
  },
  "debug": {
    "latencies_ms": {
      "embed": 34,
      "retrieve": 18,
      "rerank": 1,
      "prompt": 0,
      "llm": 620,
      "persist": 5,
      "total": 678
    },
    "retrieval_count": 10,
    "selected_count": 5,
    "rerank_applied": true,
    "rerank_enabled": true,
    "rerank_provider": "openai",
    "rerank_model": null,
    "rerank_fallback_used": false,
    "rerank_fallback_reason": null,
    "rerank_input_count": 10,
    "rerank_batch_count": 2,
    "rerank_prompt_tokens": 1240,
    "rerank_completion_tokens": 48,
    "rerank_total_tokens": 1288,
    "rerank_cost_usd": 0.0,
    "detected_language": "de",
    "answer_language_used": "de",
    "embedding_model": "text-embedding-3-small",
    "llm_model": "gpt-5.4-mini",
    "prompt_template_key": "answer_generation",
    "prompt_template_version": 3,
    "prompt_template_version_id": "uuid",
    "graph_context_enabled": false,
    "graph_context_used": false,
    "graph_context_unavailable": false,
    "graph_context_reason": null,
    "graph_seed_entity_count": 0,
    "graph_related_entity_count": 0,
    "graph_chunk_count": 0,
    "graph_max_hops_used": 0,
    "graph_relation_types_used": []
  },
  "created_at": "2026-05-09T10:01:10Z"
}
```

Not-found behavior:

- When no relevant chunks are retrieved (or confidence is below threshold), response returns `not_found=true`, no citations, and answer:
- `"I could not find this information in the uploaded documents."`

Caches, budgets, and the verified-answer shortcut (0.5.0, R05-04 and R05-05; additive):

- `trust_metadata.stage_degradations` (new, default `[]`): one entry per optional stage the
  latency budget cut short, `{"stage", "reason", "action"}` with `reason` one of
  `deadline`, `budget`, `error` and `action` such as `original_question`, `vector_only`,
  `original_order`, `skipped`, `single_generation`, or `answer_withheld`. Empty unless
  `CHAT_TOTAL_DEADLINE_MS` or a `CHAT_STAGE_BUDGET_*_MS` setting is non-zero. Required stages
  are never listed; in strict grounded verification an exhausted verify budget returns
  `not_found=true` and `verification_failed=true`, never unverified text.
- Verified-answer shortcut (`CHAT_VERIFIED_ANSWER_SHORTCUT_ENABLED`, off by default): when
  on, a published card whose question equals the normalised question and whose citations all
  pass the caller's read, cite, scope, and chunk checks is evaluated, but the response is
  unchanged (shadow mode): the answer is still generated. Returning the card needs a
  contract decision first, because `confidence_score` is a required number and the API does
  not invent one for a verified answer. The planned additive trust fields `answer_source`
  (`"verified_answer"`) and `verified_answer_id` are therefore **not** in the schema yet.
- Repeated questions reuse the organisation's cached query embedding; the response and
  `debug` fields are the same as on a cache miss, except that the token ledger in the usage
  event records zero embedding tokens for a cached query.

### WebSocket `/chat/ws`

Streaming alternative to `POST /chat`, enabled with `FEATURE_CHAT_WEBSOCKET_ENABLED`. The client
sends `{"command": "chat.start", "payload": <ChatQueryRequest>}` (also `chat.cancel`,
`chat.resume` (see [Resume](#resume)), and `heartbeat.pong`). The server streams events with one
envelope (`stream_sequence` is set on the events of a run, `null` on connection events):

```json
{
  "event": "chat.error",
  "request_id": "req_123",
  "conversation_id": null,
  "message_id": null,
  "sequence": 3,
  "timestamp": "2026-11-26T10:00:00+00:00",
  "payload": {"quota_type": "questions", "retryable": true, "next_reset_at": "2026-11-27T00:00:00+00:00"},
  "safe_error_code": "plan_limit_exceeded",
  "stream_sequence": 3
}
```

Events include `chat.request.received`, `activity.step.update`, `retrieval.started`,
`retrieval.completed`, `generation.started`, `generation.delta`, `generation.replace`,
`generation.final`, `chat.completed`, `chat.cancelled`, `chat.resumed`, and `chat.error` (see
[Chat event protocol](#chat-event-protocol)).

Parity with `POST /chat` (shared code in `backend/app/application/chat/`):

- The WebSocket always runs the same pipeline stages as `POST /chat` (since 0.5.0;
  `CHAT_PIPELINE_V2` is deprecated and ignored): query rewriting, context packing, the grounded verifier (strict-mode refusals
  apply), tree search, freshness, OCR, table, and extraction-quality signals, and the AI
  response policy checks. The prompt template is resolved by the same rule (grounded
  questions only). `chat.completed` carries the same `ChatQueryResponse` as `POST /chat`.
- The planning, strategy-selection, and tool-orchestration `activity.step.update` events are
  sent once those decisions are made.
- `sequence` is one counter per connection: heartbeat, `chat.cancel`, and run events never
  repeat a number. `conversation_id` is the chat session id (pre-assigned for a new
  conversation), and `message_id` is the pre-assigned assistant message id on every event
  from `generation.started` on.
- No database connection is held while the model generates; a run that fails before
  persistence writes no chat session or message.
- The plan question quota is checked before any work starts. Nothing is persisted on refusal.
- One question is recorded against the quota in the same transaction as the persisted answer.
- Retrieved chunks from documents the user may not `cite` are dropped before the prompt is built.
  Owners and admins bypass this check.
- Scope-inventory answers (for example "which files are in this scope?") list every readable document, but cite only documents the user may `cite`, on both transports.
- The known quota limit described in [Quotas and plan limits](#quotas-and-plan-limits) applies to
  both transports: the check and the increment are separate, so a burst can overshoot a hard limit.

`safe_error_code` values (`ChatWSSafeErrorCode` in `app/domains/chat/schemas/chat_ws.py`):
`already_running`, `chat_persistence_failed`, `chat_session_not_found`, `document_not_found`,
`generation_failed`, `internal_error`, `invalid_message`, `invalid_request`,
`plan_limit_exceeded`, `provider_busy`, `rate_limit_exceeded`, `rate_limiter_unavailable`,
`resume_unavailable`, `retrieval_failed`.

`provider_busy` (R05-06) means the organisation's concurrent LLM call limit
(`LLM_ORG_MAX_CONCURRENT_CALLS`, off by default) stayed reached for `LLM_ORG_SEMAPHORE_WAIT_MS`;
`POST /chat` answers `429` with `detail.code = "provider_busy"`. Retry after a short delay. An
open provider circuit breaker without a fallback provider is reported as `generation_failed`.
`resume_unavailable` (R05-13) answers a `chat.resume` that cannot be served (see
[Resume](#resume)).

`plan_limit_exceeded` is the WebSocket form of the HTTP `403` with
`detail.code = "plan_limit_exceeded"`. Its `payload` carries only `quota_type`, `retryable`, and
`next_reset_at`. Refusals are counted in `rudix_chat_quota_denied_total{transport}`.

#### Handshake authentication

The handshake is authenticated in this order (`backend/app/application/chat/ws_auth.py`):

1. `?ticket=<ticket>`: a single-use ticket from `POST /chat/ws-ticket`. This is what the browser
   uses. An invalid, reused, or expired ticket fails the handshake; it never falls through to
   another mode. The user, the app session, and a current membership in the ticket's organisation
   are reloaded at redemption, and the role comes from that membership. Handshake headers such as
   `X-Organization-Id` are ignored for ticket auth.
2. `Authorization: Bearer <credential>` header: for non-browser clients. Authenticated exactly like
   HTTP (JWTs, `rudix_` API keys, `svc_` service-account tokens), and `X-Organization-Id` is
   honoured. API-key and service-account principals carry no role, so they still fail the role
   check (`4403`), the same as `POST /chat`.
3. `?token=<access token>`: deprecated and off by default. Accepted only while
   `CHAT_WS_ALLOW_QUERY_TOKEN=true` (default `true` in 0.2.0, `false` since 0.5.0, removed in
   1.0.0). Each use logs `chat.ws.query_token_used` with the user and organisation ids only.
   With the default, a `?token=` handshake closes with `4401`; clients use a ticket instead.

Close codes: `4401` for any authentication failure (`Unauthorized`, or `Missing auth credentials`
when nothing was sent), `4403` for a role that may not chat, `4429` for too many connections per
user, and `4503` when WebSocket chat is disabled. Rejections log `chat.ws.auth.rejected` with the
method and failure reason (never the credential). Attempts are counted in
`rudix_chat_ws_auth_total{method,outcome}`.

Uvicorn logs the handshake path with its query string. A logging filter on the `uvicorn`,
`uvicorn.error`, and `uvicorn.access` loggers replaces `token`, `ticket`, and `access_token`
query values with `***`.

#### Resume

Since 0.5.0 (R05-13, contract 4.2.7 of `docs/roadmap/V0_5_0_IMPLEMENTATION_PLAN.md`) a run
survives a dropped socket and can be followed again from a new connection.

- Every event of a run carries `stream_sequence` (1, 2, … per assistant message, from
  `chat.request.received` to the terminal event). `sequence` stays the connection counter.
- When Redis is configured, every run event is also written to a buffer keyed by the
  organisation, the user, and the assistant message id
  (`rudix:{env}:chat:resume:v1:{org}:{user}:{message_id}`), kept for
  `CHAT_RESUME_BUFFER_TTL_SECONDS` (default 300) after the last event. Past
  `CHAT_RESUME_BUFFER_MAX_EVENTS` (default 2000) entries, consecutive deltas are merged into
  one entry; a replay still sends only the text after the client's last sequence.
- When the socket drops mid-run, the run keeps going for `CHAT_WS_RESUME_GRACE_SECONDS`
  (default 30; `0` cancels on drop as before 0.5.0), and as long as a resumed connection is
  following it. Then it is cancelled and its partial usage is recorded
  (`chat.completion.cancelled`), as for `chat.cancel`. `chat.cancel` always cancels at once.
  Without Redis there is no buffer and the grace window behaves as `0`. SSE is unchanged: a
  disconnect cancels.

To resume, open a new connection (with a fresh ticket) and send:

```json
{"command": "chat.resume", "payload": {"message_id": "<uuid>", "last_stream_sequence": 12}}
```

`message_id` is the `message_id` of the run's events (set from `generation.started` on);
`last_stream_sequence` is the highest `stream_sequence` the client applied (`0` for none).

1. While the buffer exists, the server sends `chat.resumed` (`{"message_id", "replayed"}`, the
   number of buffered events it replays), the buffered events with a higher
   `stream_sequence` in order, then the live events until `chat.completed`, `chat.error`, or
   `chat.cancelled`. Replayed events keep their `stream_sequence` and `request_id` and get new
   `sequence` numbers on this connection.
2. When the run finished and the buffer expired, it sends `chat.resumed` with `replayed: 0` and
   one `chat.completed` rebuilt from the stored message: `payload.rebuilt = true` and
   `payload.response` with `chat_session_id`, `message_id`, `answer`, `confidence_score`,
   `confidence_category`, `citations`, `trust_metadata`, and `created_at` (no `debug` or
   `confidence_explanation`; read the trust metadata route for details).
3. Otherwise it sends `chat.error` with `resume_unavailable`: the message is unknown, belongs
   to another user or organisation, was cancelled before it was stored, Redis is missing or
   failing, or the buffer expired while it was being followed.

The client discards events whose `(message_id, stream_sequence)` it already applied. The
buffer key contains the organisation and user of the principal, so only the user who started
the run, in the same organisation, can read it. `chat.resume` while another command runs on
the connection answers `already_running`; an invalid payload answers `invalid_request`.
`chat.cancel` while following a resumed run asks that run to cancel too. Outcomes are counted
in `rudix_chat_ws_resume_total{outcome}` and drops in `rudix_chat_ws_drop_total{outcome}`.

### POST `/chat/ws-ticket`

Issues a single-use handshake ticket for `/chat/ws`. Same roles as `POST /chat` (owner, admin,
member, viewer; API keys get `403`) and the same `chat` rate-limit scope. No request body.

Response `200` (with `Cache-Control: no-store`):

```json
{
  "ticket": "opaque-url-safe-string",
  "expires_in": 30
}
```

- The ticket works once and expires after `CHAT_WS_TICKET_TTL_SECONDS` (default 30, range 5-300).
- It is bound to the user, the active organisation (from `X-Organization-Id`, as for any HTTP
  request), and the app session. Revoking the session or removing the membership before use makes
  it fail.
- Only `sha256(ticket)` is stored in Redis (`rudix:ws_ticket:v1:<hash>`); the raw ticket is never
  stored or logged.

Errors:

- `503` with `detail.code = "ws_ticket_unavailable"` when Redis is missing or failing.
- `503` with `detail.code = "chat_websocket_disabled"` when `FEATURE_CHAT_WEBSOCKET_ENABLED=false`.
- `401`, `403`, and `429` as for any protected chat route.

### Chat event protocol

`/chat/ws` and `POST /chat/query/stream` send the same events in the same envelope (shown under
WebSocket `/chat/ws`). Since 0.5.0 (R05-03) the answer text streams as the model writes it.

Per answer (contract 4.2.6 of `docs/roadmap/V0_5_0_IMPLEMENTATION_PLAN.md`):

1. `generation.started` with `payload.mode = "live" | "buffered"`.
2. Any number of `generation.delta` (`{"text": <increment>}`).
3. Optional `generation.replace` (`{"text": <full text>, "reason": "verification" | "policy" |
   "retry" | "fallback" | "normalisation"}`).
4. `citation.validation.*`.
5. `generation.final` (`{"answer", "not_found", "citations", "confidence_score",
   "confidence_category", "citation_validation_failed"}`).
6. The existing `chat.completed` after persistence.

Text before `generation.final` is provisional. On `generation.replace` the client replaces all
streamed text; `chat.completed` stays the source of truth. `message_id` (the pre-assigned
assistant message id) is set on every event from `generation.started` on.

Client rules:

- Append each `generation.delta` text to the provisional answer. Render it as provisional (for
  example without citation markers or confidence); deltas never carry citations.
- On `generation.replace`, discard everything streamed so far and show `payload.text` (it may be
  `""`). Later deltas append to that text.
- On `generation.final`, show `payload.answer` with its citations and confidence. It is the
  validated answer; nothing after it changes the text.
- On `chat.completed`, store `payload.response` (the `ChatQueryResponse` of `POST /chat`, with
  the persisted citation ids). Clients that only read `chat.completed`, or that treat one delta
  as the whole answer and then wait for `chat.completed`, keep working.
- `chat.error` can follow any event; provisional text must then be dropped.

When each event is sent:

- `live` mode: the decoded text of the model's JSON `answer` field streams as it arrives. Output
  that is not a JSON object streams nothing and is sent with `generation.replace`.
- `buffered` mode (strict grounded verification, an AI response policy with a post-generation
  rule that can refuse the answer — `citation_mode = "required"`, `min_sources_required`,
  `min_confidence_threshold`, `no_answer_behavior = "refuse"`, `stale_source_behavior =
  "refuse"` — tree search, or `CHAT_STREAM_MODE=buffered`): no delta is sent until citations
  are validated; the verified text then goes out as `generation.delta`, followed by
  `generation.final`. Text the policy or verifier would withhold is never streamed.
- A provider retry or fallback after text was streamed sends `generation.replace` with
  `{"text": "", "reason": "retry" | "fallback"}` before the new attempt's deltas.
- After verification, when the final text differs from the streamed text, one
  `generation.replace` carries the final text with the last reason that changed it: `policy`
  (post-generation block or disclaimer), `verification` (grounded verifier or refiner), or
  `normalisation` (whitespace trimming, length cap, not-found mapping). This replace comes
  after the `citation.validation.*` events and before `generation.final`.
- Guidance answers stream like grounded answers (`live` unless a blocking policy or
  `CHAT_STREAM_MODE=buffered`); scope-inventory answers send one delta. A blocked question
  (injection guard, policy topic) or a question with no evidence sends no `generation.started`
  and no delta, only `generation.final` and `chat.completed`.
- Cancelling (`chat.cancel` on the WebSocket, a client disconnect on SSE) closes the provider
  stream. No message is stored and no question is counted against the quota; the tokens spent
  are recorded as a `usage_events` row with `event_type = "chat.completion.cancelled"`
  (provider-reported usage, or chars / 4 estimates with `metadata.usage_estimated = true`).

### POST `/chat/query/stream`

Server-Sent Events form of `POST /chat` for clients that cannot use WebSockets. Same request
body (`ChatQueryRequest`), roles (owner, admin, member, viewer), `chat` rate-limit scope, quota,
and pipeline.

- Authorisation, the injection guard, and configuration (pipeline stages 1-3) finish before the
  response starts, so their refusals return the same status and `detail` as `POST /chat`
  (`403` with `detail.code = "plan_limit_exceeded"`, `404` for an unknown document or chat
  session, `401`, `429`). Any later failure is sent as a `chat.error` event with the WebSocket
  `safe_error_code` values, and the stream ends.
- Response `200` with `Content-Type: text/event-stream`, `Cache-Control: no-store`, and
  `X-Accel-Buffering: no`. GZip never compresses this media type.
- Frames (one per event; `data` is the event envelope JSON on one line, and `id` equals its
  `sequence`):

```text
id: 12
event: generation.delta
data: {"event":"generation.delta","request_id":"…","conversation_id":"…","message_id":"…","sequence":12,"timestamp":"…","payload":{"text":"Employees receive"},"safe_error_code":null}

```

- The first event is `chat.request.received` and the last is `chat.completed` or `chat.error`.
  A `: keep-alive` comment is sent when no event was sent for
  `WS_CHAT_HEARTBEAT_INTERVAL_SECONDS`.
- A client disconnect cancels the run at once (partial usage as above). There is no resume for
  SSE; reconnecting starts a new question.
- Usage rows of SSE answers carry `metadata.transport = "sse"`.

### POST `/chat/sessions/{session_id}/messages`

Deprecated (returns 501; removed in 1.0.0)

Legacy ask-a-question contract. Use `POST /chat` instead; the shapes below are kept for reference only.

Request:

```json
{
  "message": "What is the leave policy?",
  "document_ids": ["uuid"],
  "answer_language": "auto",
  "stream": false
}
```

Response:

```json
{
  "session_id": "uuid",
  "message_id": "uuid",
  "role": "assistant",
  "answer": "Employees receive 20 paid leave days per year.",
  "citations": [
    {
      "document_id": "uuid",
      "chunk_id": "uuid",
      "page_number": 4,
      "score": 0.89
    }
  ],
  "created_at": "2026-05-07T10:01:10Z"
}
```

Current behavior:

- Endpoint validates authz and document access, then returns `501`. It is marked `deprecated` in OpenAPI and will be removed in `1.0.0`.

## Prompt templates

Prompt templates are organization-scoped product configuration for answer generation, summarization, comparison, citation validation, and agent planning.

Auth and safety:

- All prompt-template endpoints require `owner|admin`.
- Every query and mutation is scoped to the active organization.
- Published versions are immutable; edits require a new draft.
- Rollback creates a new published version copied from the selected published source version.
- Audit events record safe metadata only: template key, version numbers, state transitions, and request IDs. Raw prompt content is not written to audit logs.

### GET `/prompt-templates`

List prompt templates for the active organization. Default system templates are lazily created on first access.

Query params:

```text
limit=50
offset=0
```

Response:

```json
{
  "items": [
    {
      "prompt_template_id": "uuid",
      "organization_id": "uuid",
      "template_key": "answer_generation",
      "name": "Answer Generation",
      "description": "Builds grounded answers from retrieved document chunks.",
      "category": "rag",
      "latest_version_number": 3,
      "active_version_number": 3,
      "active_version_id": "uuid",
      "active_state": "published",
      "active_published_at": "2026-06-05T10:00:00Z",
      "eval_run_count": 4,
      "created_at": "2026-06-01T10:00:00Z",
      "updated_at": "2026-06-05T10:00:00Z"
    }
  ],
  "total": 5,
  "limit": 50,
  "offset": 0
}
```

### GET `/prompt-templates/{template_key}`

Return template metadata, active version, version history, and recent eval results for the active version.

`template_key` values:

```text
answer_generation
summarization
comparison
citation_validation
agent_planning
```

### POST `/prompt-templates/{template_key}/drafts`

Create a draft copied from the active version or a supplied source version.

Request:

```json
{
  "source_version_number": 2,
  "change_note": "Adjust citation instructions"
}
```

### PATCH `/prompt-templates/{template_key}/versions/{version_number}`

Update a draft or review version. Published versions return `409`.

Request:

```json
{
  "content": "Answer using only {{ context }} for {{ question }}.",
  "variables": [
    { "name": "context", "required": true },
    { "name": "question", "required": true }
  ],
  "variable_schema": {
    "type": "object",
    "required": ["context", "question"],
    "properties": {
      "context": { "type": "string" },
      "question": { "type": "string" }
    }
  },
  "preview_context": {
    "context": "Policy excerpt...",
    "question": "What changed?"
  },
  "change_note": "Tighten grounding"
}
```

Validation checks:

- Template placeholders must use declared variables.
- Required variables must be present in `preview_context`.
- `variable_schema` must be JSON-schema-like object metadata.
- Safe error messages identify validation categories without returning private document text.

### POST `/prompt-templates/{template_key}/versions/{version_number}/submit-review`

Move a mutable version from `draft` to `review`.

### POST `/prompt-templates/{template_key}/versions/{version_number}/publish`

Publish a mutable version and make it active for the organization.

Request:

```json
{
  "change_note": "Approved after regression eval"
}
```

### POST `/prompt-templates/{template_key}/rollback`

Restore a previous published version by creating a new active published version.

Request:

```json
{
  "version_number": 1,
  "change_note": "Rollback after eval regression"
}
```

### POST `/prompt-templates/{template_key}/preview`

Render a prompt using a version or supplied draft content plus fake context.

Request:

```json
{
  "version_number": 3,
  "context": {
    "question": "What is the leave policy?",
    "context": "Policy excerpt..."
  }
}
```

Response:

```json
{
  "template_key": "answer_generation",
  "version_number": 3,
  "rendered_prompt": "You are a document-grounded assistant...",
  "context": {
    "question": "What is the leave policy?"
  }
}
```

### GET `/prompt-templates/{template_key}/versions/{version_number}/eval-results`

List evaluation runs that recorded the selected prompt template version.

## Collaboration bots

Slack and Microsoft Teams bot access is exposed as a transport adapter around the
same Rudix chat query path used by `/chat`.

Configuration:

- `FEATURE_ENABLE_COLLABORATION_BOTS` controls the whole bot surface.
- `BOT_SLACK_SIGNING_SECRET` verifies Slack signed requests when configured.
- `BOT_SLACK_CLIENT_ID`, `BOT_SLACK_CLIENT_SECRET`, and optional
  `BOT_SLACK_OAUTH_REDIRECT_URI` enable Slack OAuth installation.
- `BOT_SLACK_OAUTH_SCOPES` controls requested Slack app scopes.
- `BOT_TEAMS_SHARED_SECRET` verifies Teams webhook requests using a bearer secret
  when configured.
- `BOT_PROCESS_EVENTS_ASYNC` controls whether public bot events acknowledge
  quickly and deliver the final answer back to the platform.
- `BOT_DELIVERY_TIMEOUT_SECONDS` caps Slack/Teams outbound delivery calls.
- `RATE_LIMIT_BOT_REQUESTS` applies per workspace/team and external user within
  the shared `RATE_LIMIT_WINDOW_SECONDS`.

Admin setup endpoints require `owner|admin`:

- `POST /admin/bots/slack/oauth/start`
- `GET /admin/bots/installations`
- `POST /admin/bots/installations`
- `PATCH /admin/bots/installations/{installation_id}`
- `PUT /admin/bots/installations/{installation_id}/credential`
- `DELETE /admin/bots/installations/{installation_id}/credential`
- `GET /admin/bots/installations/{installation_id}/mappings`
- `PUT /admin/bots/installations/{installation_id}/mappings`

Installation records store provider metadata only: provider, external
workspace/team/tenant IDs, enabled/disabled status, display name, optional
default `source_scope`, safe config metadata, and encrypted credential metadata.
Raw Slack or Teams bot tokens are encrypted at rest and never returned by API
responses.

External-user mappings bind one Slack/Teams user ID to a Rudix user in the same
organization. Bot ask events are rejected unless:

- the workspace/team installation exists
- the installation is enabled
- the external user is mapped and active
- the mapped Rudix user is active in the organization
- the request is within the bot rate limit

Provider event endpoints:

- `POST /bots/slack/events`
- `GET /bots/slack/oauth/callback`
- `POST /bots/teams/events`

Slack adapters accept URL verification payloads, JSON event callbacks, and
slash-command form payloads. Teams adapters accept Activity-style JSON payloads.
Both normalize to the same internal ask event:

```json
{
  "workspace_id": "T123 or tenant-id",
  "user_id": "U123 or aadObjectId",
  "text": "What is the leave policy?",
  "source_scope": {
    "mode": "collections",
    "collection_ids": ["uuid"]
  }
}
```

If the event omits `source_scope`, the installation default is used. If neither
is set, the query falls back to normal workspace scope. Collection, source, and
document filters are resolved by the existing source-scope and document-access
services before retrieval.

Slash commands and message text can include lightweight selectors:

- `--collection <collection_id>` limits retrieval to one or more collections.
- `--document <document_id>` forwards explicit document IDs to the same chat
  permission checks used by the web API.

By default, event endpoints return a fast acknowledgement and deliver the final
answer asynchronously to Slack `response_url`, Slack `chat.postMessage` thread,
or Teams Bot Framework conversation endpoints when delivery credentials are
configured. Local/debug callers can set `X-Rudix-Bot-Sync: true` to receive the
full `BotAskResponse` in the HTTP response.

Responses include safe platform-ready text, an optional loading string, the
persisted chat session/message IDs, not-found status, and Rudix citation links:

```json
{
  "ok": true,
  "provider": "slack",
  "response_type": "in_channel",
  "text": "Employees receive 20 paid leave days per year.\n\nSources:\n[1] policy.pdf, p. 4: http://localhost:3000/documents/...",
  "loading_text": "Rudix is searching the permitted sources for an answer.",
  "thread_id": "1710000000.0001",
  "chat_session_id": "uuid",
  "message_id": "uuid",
  "not_found": false,
  "citations": [
    {
      "label": "policy.pdf, p. 4",
      "document_id": "uuid",
      "chunk_id": "uuid",
      "filename": "policy.pdf",
      "page_number": 4,
      "url": "http://localhost:3000/documents/{document_id}?chunk_id={chunk_id}&citation=1"
    }
  ]
}
```

Error responses are safe and actionable:

```json
{
  "ok": false,
  "provider": "teams",
  "response_type": "ephemeral",
  "text": "Your Slack or Teams account is not mapped to a Rudix user.",
  "error": {
    "code": "bot_user_not_mapped",
    "message": "Your Slack or Teams account is not mapped to a Rudix user."
  }
}
```

Audit events:

- `bots.installation.created`
- `bots.installation.updated`
- `bots.credential.updated`
- `bots.credential.cleared`
- `bots.slack.oauth.started`
- `bots.user_mapping.upserted`
- `bots.ask.requested`
- `bots.ask.completed`
- `bots.ask.rejected_disabled`
- `bots.ask.rejected_unmapped_user`
- `bots.ask.rejected_inactive_user`
- `bots.ask.rejected_rate_limited`
- `bots.ask.failed`
- `bots.delivery.completed`
- `bots.delivery.failed`

Audit metadata includes provider, workspace/team/tenant IDs, external user ID,
channel/thread IDs, source-scope mode, chat session/message IDs when available,
citation count, not-found status, and safe outcome data. Raw questions, answers,
tokens, secrets, and private document text are not written to bot audit metadata.

Transport note: official Slack and Microsoft Teams SDKs should remain transport
adapters only. They may acknowledge events quickly and dispatch the normalized
ask event to the same backend service; Rudix authorization, scope resolution,
retrieval, citation rendering, audit, and rate limiting must remain in the core
backend.

## Search/debug endpoints

### POST `/retrieval/search`

For admin/debug only.

Request:

```json
{
  "query": "leave policy",
  "document_ids": ["uuid"],
  "top_k": 10
}
```

Response:

```json
{
  "results": [
    {
      "chunk_id": "uuid",
      "filename": "policy.pdf",
      "page_number": 4,
      "text": "...",
      "similarity_score": 0.91
    }
  ]
}
```

## Evaluation

### POST `/evaluation-sets`

Create an evaluation set.

Request:

```json
{
  "name": "HR Policy Evaluation",
  "description": "Questions for HR policy documents."
}
```

Response:

```json
{
  "evaluation_set_id": "uuid",
  "name": "HR Policy Evaluation",
  "description": "Questions for HR policy documents.",
  "question_count": 0,
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:00:00Z"
}
```

### GET `/evaluation-sets`

List evaluation sets for the active organization.

Query params:

```text
limit=20
offset=0
```

Response:

```json
{
  "items": [
    {
      "evaluation_set_id": "uuid",
      "name": "HR Policy Evaluation",
      "description": "Questions for HR policy documents.",
      "question_count": 12,
      "created_at": "2026-05-07T10:00:00Z",
      "updated_at": "2026-05-07T10:00:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### POST `/evaluation-sets/{evaluation_set_id}/questions`

Add one test question to an evaluation set.

Request:

```json
{
  "question": "How many paid leave days are available?",
  "expected_answer": "20 paid leave days",
  "expected_document_id": "uuid",
  "expected_page_number": 4,
  "tags": ["hr", "leave-policy"],
  "metadata": {
    "difficulty": "easy"
  }
}
```

Response:

```json
{
  "evaluation_question_id": "uuid",
  "evaluation_set_id": "uuid",
  "question": "How many paid leave days are available?",
  "expected_answer": "20 paid leave days",
  "expected_document_id": "uuid",
  "expected_page_number": 4,
  "tags": ["hr", "leave-policy"],
  "metadata": {
    "difficulty": "easy"
  },
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:00:00Z"
}
```

### GET `/evaluation-sets/{evaluation_set_id}/questions`

List questions for one evaluation set.

Query params:

```text
limit=20
offset=0
```

Response:

```json
{
  "evaluation_set_id": "uuid",
  "items": [
    {
      "evaluation_question_id": "uuid",
      "evaluation_set_id": "uuid",
      "question": "How many paid leave days are available?",
      "expected_answer": "20 paid leave days",
      "expected_document_id": "uuid",
      "expected_page_number": 4,
      "tags": ["hr", "leave-policy"],
      "metadata": {
        "difficulty": "easy"
      },
      "created_at": "2026-05-07T10:00:00Z",
      "updated_at": "2026-05-07T10:00:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### POST `/evaluations/run`

Run an evaluation.

Request:

```json
{
  "evaluation_set_id": "uuid",
  "config": {
    "run_name": "Chunking benchmark",
    "top_k": 5,
    "rerank": true,
    "model_name": "gpt-5.4-mini",
    "selected_document_ids": ["uuid"],
    "metric_options": {
      "faithfulness": true,
      "citation_accuracy": true
    },
    "comparison_targets": [
      { "label": "Baseline profile", "chunking_profile_id": "uuid" },
      { "label": "Candidate profile", "chunking_profile_id": "uuid" }
    ],
    "regression_thresholds": {
      "retrieval_hit_rate_min": 0.7,
      "citation_accuracy_score_min": 0.8,
      "faithfulness_score_min": 0.8,
      "max_not_found_rate": 0.2
    }
  }
}
```

Response:

```json
{
  "evaluation_run_id": "uuid",
  "status": "queued"
}
```

Notes:

- Endpoint is role-protected (`owner|admin`).
- `evaluation_set_id` must belong to the active organization.
- `config.selected_document_ids` are org-scoped and validated before enqueue.
- Leave `comparison_targets` empty to evaluate the current live index; send one target via `chunking_profile_id` to pin a profile or two-plus `comparison_targets` to compare strategies on the same dataset.
- `comparison_targets` accept either `chunking_profile_id` or `chunking_profile_config`; the backend resolves and stores `chunking_strategy`, `profile_version`, and normalized config in `evaluation_runs.config`.
- The active `answer_generation` prompt template version is resolved when the run is queued and stored as `evaluation_runs.prompt_template_version_id` plus compact `config.prompt_template` metadata.
- `regression_thresholds` are optional release/eval gates; failing targets are flagged in the run summary but do not change the API contract of the run itself.
- If duplicate active-run prevention is enabled, concurrent queued/running runs for the same set return `409`.
- Worker computes per-question metrics (`retrieval_hit_rate`, `retrieval_mrr`, `context_precision`, `context_recall`, `faithfulness_score`, `answer_relevance_score`, `citation_accuracy_score`, `refusal_accuracy`, latency, cost, chunk counts, and not-found rate) and stores them in `evaluation_results.details.metrics`.
- Worker also writes a run summary to `evaluation_runs.config.metrics_summary` with aggregated means/rates, latency/cost/token totals, and optional chunking comparison results.
- `config.metric_options.faithfulness` and `config.metric_options.answer_relevance` toggle judge-based scoring; when enabled, `config.metric_options.judge_model_name` can override the judge model.

### GET `/evaluations/runs/{evaluation_run_id}`

Get evaluation run status/details with paginated question results.

Query params:

- `limit` (default `20`, max `200`)
- `offset` (default `0`)

Response:

```json
{
  "evaluation_run_id": "uuid",
  "evaluation_set_id": "uuid",
  "status": "completed",
  "config": {
    "run_name": "Chunking benchmark",
    "top_k": 5,
    "rerank": true,
    "model_name": "gpt-5.4-mini",
    "selected_document_ids": ["uuid"],
    "metric_options": {
      "faithfulness": true,
      "answer_relevance": true
    },
    "comparison_targets": [
      {
        "label": "Baseline profile",
        "chunking_profile_id": "uuid",
        "chunking_strategy": "token_recursive",
        "profile_version": "cfg-baseline"
      },
      {
        "label": "Candidate profile",
        "chunking_profile_id": "uuid",
        "chunking_strategy": "heading_aware",
        "profile_version": "cfg-candidate"
      }
    ],
    "regression_thresholds": {
      "retrieval_hit_rate_min": 0.7,
      "citation_accuracy_score_min": 0.8
    }
  },
  "summary": {
    "question_total_count": 20,
    "question_success_count": 19,
    "question_failure_count": 1,
    "retrieval_hit_rate": 0.86,
    "retrieval_mrr": 0.79,
    "context_precision": 0.71,
    "context_recall": 0.8,
    "faithfulness_score": 0.81,
    "answer_relevance_score": 0.84,
    "citation_accuracy_score": 0.78,
    "refusal_accuracy": 1.0,
    "latency_ms_total": 29000,
    "latency_ms_average": 1450.0,
    "cost_usd_total": 0.043,
    "cost_usd_average": 0.0023,
    "retrieved_chunk_count_average": 7.4,
    "selected_chunk_count_average": 4.1,
    "not_found_rate": 0.05,
    "comparison": {
      "baseline_label": "Baseline profile",
      "baseline_score": 0.82,
      "latest_label": "Candidate profile",
      "latest_score": 0.78,
      "score_delta": -0.04
    },
    "comparison_targets": [
      {
        "label": "Baseline profile",
        "chunking_strategy": "token_recursive",
        "profile_version": "cfg-baseline",
        "overall_score": 0.82,
        "chunk_count_total": 188,
        "chunk_tokens_average": 166.0,
        "regression_flags": []
      },
      {
        "label": "Candidate profile",
        "chunking_strategy": "heading_aware",
        "profile_version": "cfg-candidate",
        "overall_score": 0.78,
        "chunk_count_total": 144,
        "chunk_tokens_average": 203.0,
        "regression_flags": [
          {
            "metric": "citation_accuracy_score",
            "status": "failed",
            "threshold": 0.8,
            "value": 0.76
          }
        ]
      }
    ],
    "best_by_document_type": {
      "pdf": { "label": "Baseline profile", "score": 0.82 }
    },
    "best_by_use_case": {
      "policy_qa": { "label": "Candidate profile", "score": 0.81 }
    },
    "regressions_count": 1,
    "regression_failed": true
  },
  "failure_reason": null,
  "failure_type": null,
  "results": {
    "total": 20,
    "limit": 20,
    "offset": 0,
    "items": [
      {
        "evaluation_result_id": "uuid",
        "evaluation_question_id": "uuid",
        "question": "What is the leave policy?",
        "status": "completed",
        "generated_answer": "Employees receive 20 paid leave days per year.",
        "retrieval_score": 1.0,
        "faithfulness_score": 0.88,
        "citation_accuracy_score": 0.9,
        "answer_relevance_score": 0.86,
        "latency_ms": 1480,
        "metrics": {
          "retrieval_hit_rate": 1.0,
          "context_precision": 0.8,
          "context_recall": 1.0
        },
        "failure_reason": null,
        "failure_type": null
      }
    ]
  },
  "created_at": "2026-05-09T10:01:10Z",
  "updated_at": "2026-05-09T10:05:00Z"
}
```

Notes:

- Cross-organization run access returns `404`.
- Queued/running runs return current status with empty `results.items` until worker results are persisted.
- Failed runs expose safe failure details (`failure_reason`, `failure_type`) when available.

## Pipeline explorer

Storage model:

- `pipeline_runs` stores run-level metadata and links to `document_id`, `chat_message_id`, or `evaluation_run_id`.
- `pipeline_events` stores ordered node events (`started|completed|failed|skipped`) with timing and sanitized payload previews.
- Current implementation supports document, chat, and evaluation run types using one graph schema.

### GET `/pipeline/steps`

Returns canonical pipeline step labels for UI fallback/validation.

Response:

```json
{
  "steps": [
    "extract",
    "clean",
    "chunk",
    "embed",
    "index",
    "retrieve",
    "rerank",
    "generate",
    "evaluate"
  ]
}
```

### GET `/pipeline/runs/resolve`

Resolves the latest accessible pipeline run for one or more context identifiers.

Query params:

```text
run_type=document.process|chat.answer|evaluation.run
document_id=<uuid>
chat_message_id=<uuid>
evaluation_run_id=<uuid>
```

At least one context identifier is required.

Response:

```json
{
  "pipeline_run_id": "uuid",
  "pipeline_type": "chat.answer",
  "status": "completed"
}
```

### GET `/pipeline/runs/{run_id}`

Returns graph nodes/edges for one pipeline run scoped to the caller organization.

Response:

```json
{
  "pipeline_run_id": "uuid",
  "pipeline_type": "document.process",
  "status": "completed",
  "nodes": [
    {
      "id": "chunk",
      "label": "Chunk",
      "section": "ingestion",
      "description": "Split extracted text into overlapping chunks",
      "status": "completed",
      "started_at": "2026-05-20T08:41:00Z",
      "completed_at": "2026-05-20T08:41:02Z",
      "duration_ms": 1960,
      "metrics": {
        "chunk_count": 92
      }
    }
  ],
  "edges": [
    {
      "id": "extract->chunk",
      "source": "extract",
      "target": "chunk"
    }
  ]
}
```

### GET `/pipeline/runs/{run_id}/nodes/{node_id}`

Returns node-level detail for a specific run/node pair.

Response:

```json
{
  "node_id": "chunk",
  "title": "Chunk",
  "description": "Split extracted text into overlapping chunks.",
  "status": "completed",
  "inputs": {
    "pages": 24
  },
  "outputs": {
    "chunks": 92
  },
  "config": {
    "chunk_size_tokens": 700,
    "chunk_overlap_tokens": 120
  },
  "logs": ["Created 92 chunks from 24 pages."],
  "error_message": null,
  "error_details": {},
  "metrics": {
    "chunk_count": 92
  },
  "started_at": "2026-05-20T08:41:00Z",
  "completed_at": "2026-05-20T08:41:02Z",
  "duration_ms": 1960
}
```

## Agent runs

### POST `/agent/runs`

Creates and executes an agent run. `agentic_mode` must be explicitly `true`.
Validation, roles, rate limit, and the `agent_runs` quota are the same in both execution
modes (`AGENT_RUN_EXECUTION`, R06-13):

- `inline` (default, 0.5.0 behaviour): the run executes inside the request and the
  response carries its final state (example below).
- `worker`: the request stores the run as `queued` (with the validated request and the
  caller's identity as `request_snapshot`), records the quota, writes an outbox row for
  `agents.run.execute` in the same transaction, commits, publishes, and returns `201` at
  once with the same `AgentRunCreateResponse` shape: `status: "queued"`, zero counters,
  `outcome: null`. Follow the run with `GET /agent/runs/{run_id}` or the stream below. A
  broker outage leaves the outbox row pending; the `outbox.relay` beat task publishes it.

Request:

```json
{
  "agentic_mode": true,
  "request": {
    "objective": "Answer the question using indexed documents with citations.",
    "question": "What is our retention policy?",
    "document_ids": ["uuid"],
    "top_k": 5,
    "rerank": true
  }
}
```

Response (`201 Created`, inline mode):

```json
{
  "run": {
    "run_id": "uuid",
    "status": "completed",
    "steps_executed": 4,
    "tool_calls_executed": 5,
    "total_tokens": 1823,
    "total_cost_usd": 0.0012,
    "outcome": {
      "answer": "Retention policy is 7 years for financial records.",
      "citations": [
        {
          "document_id": "uuid",
          "chunk_id": "uuid",
          "page_number": 4
        }
      ],
      "confidence": {
        "score": 0.84,
        "category": "high"
      },
      "not_found": false,
      "mode": "answer"
    },
    "error": null
  }
}
```

Feature-gated behavior:

- If `FEATURE_ENABLE_AGENTS=false`, endpoints return `404` with `feature_not_available`.

### POST `/agent/workflows/preview`

Returns a deterministic workflow plan before execution. The preview is used by
the workspace UI to show step order, planner metadata, and approval-sensitive
actions before the user starts the run.

Request:

```json
{
  "workflow_type": "policy_comparison",
  "request": {
    "objective": "Compare the relevant policies and surface the material differences with citations.",
    "mode": "compare",
    "question": "Compare the policies",
    "document_query": "Compare the policies",
    "rerank": true,
    "budget": { "max_steps": 8, "max_tool_calls": 20 }
  },
  "requested_actions": ["share"]
}
```

Response:

```json
{
  "objective": "Compare the relevant policies and surface the material differences with citations.",
  "mode": "compare",
  "workflow_type": "policy_comparison",
  "planner_strategy": "comparison",
  "planner_high_risk": true,
  "requires_approval": true,
  "requested_actions": ["share"],
  "plan": [
    {
      "step_name": "discover_documents",
      "tool_name": "search_documents",
      "rationale": "Find indexed accessible documents to ground the workflow.",
      "arguments": { "query": "Compare the policies" }
    },
    {
      "step_name": "document_comparison",
      "tool_name": "compare_documents",
      "rationale": "Compare grounded evidence across selected documents.",
      "arguments": { "question": "Compare the policies" }
    }
  ]
}
```

The preview endpoint does not execute tools or persist run state. Execution
continues through `POST /agent/runs` using the previewed request payload.

### GET `/agent/runs/{run_id}`

Returns persisted run state, steps, tool calls, approvals, budget/costs, and safe error metadata.

### GET `/agent/runs/{run_id}/stream`

Server-Sent Events for one run (R06-13; replaces the 0.5.0 `501`). Same roles as
`GET /agent/runs/{run_id}` (owner, admin, member, viewer) and the same feature flag. The
run must belong to the caller's organisation; members and viewers see only runs they
started, owners and admins any run of the organisation. Otherwise `404 Agent run not found`.

Frames use the 0.5.0 framing of `POST /chat/query/stream`:

```text
id: 3
event: agent.step.completed
data: {"id":3,"event":"agent.step.completed","run_id":"uuid","payload":{"sequence":1,"step_name":"discover_documents","tool_name":"search_documents","status":"completed"},"emitted_at":"..."}

: keep-alive
```

| Event | Payload |
|---|---|
| `agent.run.status` | `status` (`queued`, `running`), `resume_count` |
| `agent.step.started` | `sequence`, `step_name`, `tool_name`, `status` |
| `agent.step.completed` | `sequence`, `step_name`, `tool_name`, `status` (`completed`, `failed`) |
| `agent.run.waiting_approval` | `status`, counters, `approval_id`, `error_code` |
| `agent.run.completed` / `.failed` / `.cancelled` | `status`, `steps_executed`, `tool_calls_executed`, `error_code` |

Payloads carry ids, statuses, tool names, counts, and safe error codes only, never
document text, prompts, or tool outputs. Ids increase monotonically within a stream. The
stream ends after a terminal event, or after `AGENT_STREAM_BUFFER_TTL_SECONDS`.

- With Redis, the runtime appends every event to a buffer (TTL
  `AGENT_STREAM_BUFFER_TTL_SECONDS`) keyed by organisation and run and publishes it on a
  channel; send `Last-Event-ID` to replay the events with a larger id, then the stream
  follows new events. While the channel is idle the run row is read every keep-alive
  interval, so a run the reaper failed still ends the stream.
- Without Redis (or without a buffer for the run), the endpoint polls the run and its steps
  every `AGENT_STREAM_POLL_INTERVAL_MS` and sends each state change. Ids then continue after
  `Last-Event-ID`, and the first poll sends the run's current state, so a reconnecting
  client may receive an event again but never misses one.

### POST `/agent/runs/{run_id}/approvals/{approval_id}/decision`

Owner/admin decision endpoint for pending approvals.

Request:

```json
{
  "status": "approved",
  "reason": "Reviewed by admin",
  "decision_payload": {}
}
```

Notes:

- `status` must be `approved` or `rejected`.
- Non-pending approvals return `409`.
- Cross-organization runs/approvals return safe `404`.
- Worker mode (R06-13): approving a run that waits for this approval moves it back to
  `queued` and writes an outbox row for `agents.run.resume` (dedupe key: the approval id)
  in the decision's transaction; the worker continues the run with the approval, so
  clients no longer resubmit with `request.approval_ids`. Inline mode keeps the 0.5.0
  behaviour (the run is marked `running`; resubmit with `approval_ids`). A rejection fails
  the run in both modes.

## Admin endpoints

### GET `/admin/chunking-profiles/strategies`

Returns the safe chunking strategy catalog, deployment default config, and the
feature-flag state used by the admin settings UI.

### GET `/admin/chunking-profiles`

Returns organization-scoped chunking profiles, including the current default
profile marker.

### POST `/admin/chunking-profiles/preview`

Returns safe preview statistics for a candidate config. The response includes
aggregate counts, reason codes, warnings, and sample chunk metadata only; it
does not include raw chunk text.

### GET `/admin/usage`

Returns usage statistics.

```json
{
  "organization_id": "uuid",
  "range": {
    "from": "2026-05-01",
    "to": "2026-05-30"
  },
  "granularity": "day",
  "totals": {
    "input_tokens": 84000,
    "output_tokens": 21000,
    "cost_usd": 12.45,
    "event_count": 1200,
    "avg_confidence": 0.81,
    "avg_latency_ms": 480.0,
    "latency_score": 60.0
  },
  "series": [
    {
      "period_start": "2026-05-01",
      "period_end": "2026-05-01",
      "input_tokens": 3100,
      "output_tokens": 740,
      "cost_usd": 0.42,
      "event_count": 44,
      "avg_confidence": 0.82,
      "avg_latency_ms": 460.0,
      "latency_score": 61.67
    }
  ]
}
```

Notes:

- `avg_confidence` is derived from usage-event metadata confidence fields when present.
- `avg_latency_ms` is derived from usage-event latency metadata fields when present.
- `latency_score` is computed server-side from average latency (0-100, higher is better).

### GET `/admin/audit-logs`

Returns paginated organization-scoped audit events for compliance review.

Query parameters:

- `from`, `to`: date range (`YYYY-MM-DD`, max 365-day span).
- `limit`, `offset`: pagination controls.
- `organization_id`: optional guard filter; must match caller organization context.
- `actor` or `user_id`: actor filter (`actor=system` matches system events).
- `action`: exact action filter.
- `entity` (or `resource_type`): exact entity/resource type filter.
- `resource_id`, `document_id`, `collection_id`: UUID scoping filters.
- `request_id`, `session_id`, `ip_address`: trace/session/network filters.
- `result`: `all|success|failure|unknown`.
- `severity`: severity label filter (for example `info`, `warning`, `critical`).
- `search`: case-insensitive text match across key event fields.

Response includes safe metadata plus derived fields:

- `result`, `severity`
- `request_id`, `session_id`, `ip_address`
- `document_id`, `collection_id` (when present)

Safe-output guarantees:

- metadata is sanitized before response serialization
- secrets/tokens and raw private content fields are redacted

### GET `/admin/audit-logs/export`

Exports filtered audit events for compliance workflows.

Query parameters:

- Supports the same filters as `/admin/audit-logs`.
- `format`: `csv` or `json`.
- `limit`: max rows per export (default `5000`, max `10000`).

Behavior:

- Requires `owner|admin`.
- Enforces organization isolation.
- Returns downloadable attachments with sanitized metadata only.
- Never includes raw auth secrets, tokens, or private document body text.

## Workspace Portability

### POST `/admin/portability/exports`

Creates a workspace export job and returns the completed job record with a
downloadable JSON artifact.

- Requires `owner|admin`.
- Supported sections: `collections`, `document_metadata`, `chat_transcripts`,
  `evaluation_datasets`, `evaluation_results`, `audit_logs`, `settings`,
  `api_metadata`, and `webhook_metadata`.
- `max_rows_per_section` defaults to `5000` and is capped at `10000`.
- Optional `from` and `to` dates filter time-based sections such as chat,
  evaluation results, and audit logs.
- Artifacts expire after the configured job artifact window.

Artifacts use schema version `rudix.workspace_export.v1`:

```json
{
  "schema_version": "rudix.workspace_export.v1",
  "generated_at": "2026-07-01T10:00:00Z",
  "organization": {
    "id": "uuid",
    "name": "Example Org",
    "slug": "example-org"
  },
  "requested_sections": ["collections", "document_metadata"],
  "limits": {
    "max_rows_per_section": 5000,
    "from": null,
    "to": null,
    "artifact_expires_days": 7
  },
  "sections": {
    "collections": { "items": [] },
    "document_metadata": {
      "fields": [],
      "documents": [],
      "values": []
    }
  },
  "limitations": []
}
```

Exports never include original document files, extracted document text,
embeddings, vector payloads, storage object keys, raw API keys, API key hashes,
webhook secret hashes, OAuth tokens, connector credentials, or secret material.

### POST `/admin/portability/imports`

Validates a Rudix workspace export artifact and optionally applies safe records.

- Requires `owner|admin`.
- Request body: `{ "artifact": { ... }, "apply": false }`.
- Validation always runs before processing.
- `apply=false` records a `validated` job with warnings/errors and makes an
  import report artifact available.
- `apply=true` creates safe records only after validation passes.
- Importable sections: `collections`, `document_metadata` metadata field
  definitions, and `evaluation_datasets`.
- Document manifests are validated and reported but do not create document rows,
  object-storage files, chunks, embeddings, or vectors. Documents must still be
  uploaded and indexed through the normal ingestion pipeline.
- Export-only sections such as chat transcripts, audit logs, settings,
  evaluation results, API metadata, and webhook metadata are ignored during
  import and reported as warnings.

### GET `/admin/portability/jobs`

Lists recent workspace portability jobs for the active organization.

### GET `/admin/portability/jobs/{job_id}`

Returns one organization-scoped portability job.

### GET `/admin/portability/jobs/{job_id}/download`

Downloads the export artifact or import report for a completed/validated job.
Cross-organization downloads return `404`, and unavailable or expired artifacts
return `409`.

### GET `/admin/governance`

Returns organization-scoped governance policy for agent and MCP controls.

Response includes:

- effective policy toggles (`agentic_mode_enabled`, `mcp_exposure_enabled`)
- side-effect guard posture (`allow_side_effect_tools`)
- allowlisted tool names
- runtime budget limits
- external MCP server policy entries (metadata + secret references only)
- global MCP endpoint status and deployment warnings
- audit log retention (`R04-09`): `policy.audit_log_retention_days` (organisation override,
  `null` = platform default), `platform_audit_log_retention_days`
  (`RETENTION_AUDIT_LOGS_DAYS`), and `effective_audit_log_retention_days` (override if set,
  else platform default; `null` = keep every row)

Notes:

- Endpoint is role-protected (`owner|admin`).
- Payload excludes raw secrets and tokens by design.

### Connector credential lifecycle

Connector credential endpoints are role-protected (`owner|admin`) and
organization-scoped:

- `POST /connectors/oauth/connect`: validates provider scope policy, stores a
  hashed one-time OAuth state, and returns the provider authorization URL.
- `POST /connectors/oauth/callback`: validates state, exchanges the code through
  the provider token endpoint, stores encrypted credentials, and returns safe
  connection metadata only.
- `POST /connectors/{connection_id}/refresh`: refreshes expired OAuth tokens
  through the shared lifecycle service and records safe audit metadata.
- `POST /connectors/{connection_id}/disconnect`: revokes remote tokens when the
  provider supports revocation, marks the local credential revoked, disables
  connector sync jobs, and writes an audit event.
- `GET /connectors/{connection_id}/diagnostics`: returns status, scopes,
  credential version, expiry, fingerprint, and sanitized metadata only.
- `POST /connectors/{connection_id}/sync-jobs`, `PATCH /connectors/{connection_id}/sync-jobs/{job_id}`, `POST /connectors/{connection_id}/sync/now`, and `POST /connectors/sync-runs/{run_id}/cancel` are owner/admin-only and rate-limited with connector-specific throttles.
- `POST /connectors/sync-runs/{run_id}/retry` re-queues a failed sync run using the
  original cursor snapshot, respects connector rate limits and permission checks,
  and returns the same safe sync-queue response shape as a manual trigger.
- `GET /connectors/{connection_id}` includes source permission snapshots so the UI can surface access-review hooks without exposing raw credentials.
- Connector sync completion and failure paths emit audit-safe lifecycle events for start, success, failure, source selection, and permission changes.

Safe-output guarantees:

- access tokens, refresh tokens, API keys, client secrets, service-account keys,
  and authorization headers are never returned in API responses
- failed callbacks and refresh failures return safe messages only
- audit events, diagnostics, and structured logs are sanitized before persistence

### PATCH `/admin/governance`

Updates organization-scoped governance policy fields.

Safe update semantics:

- unknown tool names are rejected (`422`)
- side-effect tool changes require explicit acknowledgment (`side_effect_warning_acknowledged=true`)
- policy changes are audit-logged as `admin.governance.policy.updated`
- `audit_log_retention_days` (`R04-09`): integer 30..3650 sets the organisation's audit
  retention override (`422` outside the range). Omitting the field keeps the current value,
  and an explicit `null` clears it. A change adds the new override and the effective window
  to the audit entry's metadata.

The endpoint returns the updated effective policy, changed field names, and whether an audit record was written.

## Rate limits

Recommended:

| Endpoint            | Limit                  |
| ------------------- | ---------------------- |
| `/documents/upload` | 20 uploads/hour/user   |
| `/chat`             | 60 questions/hour/user |
| `/bots/*/events`    | 30 asks/window/workspace/user |
| `/evaluations/run`  | Admin only             |
| `/retrieval/search` | Admin/debug only       |

The WebSocket `chat.start` command uses the `chat` scope limit (`RATE_LIMIT_CHAT_REQUESTS`) like
`POST /chat`, counted in its own `/chat/ws` bucket per user and organisation (buckets are keyed by
endpoint), and honours `RATE_LIMIT_REDIS_FAILURE_MODE` through the same limiter core
(`app/rate_limit/counter.py`). In
`closed` mode, when Redis is unavailable or errors, the socket receives `chat.error` with
`safe_error_code=rate_limiter_unavailable` (the equivalent of HTTP 503) and the pipeline is not
started; the connection stays open. In `open` mode the command proceeds and the degradation is
logged. Decisions are counted in `rudix_rate_limit_decisions_total{scope,decision,failure_mode}`.

## Status codes

| Code | Meaning                       |
| ---- | ----------------------------- |
| 200  | Success                       |
| 201  | Created                       |
| 202  | Accepted for async processing |
| 400  | Invalid request               |
| 401  | Not authenticated             |
| 403  | Not authorized                |
| 404  | Not found or inaccessible     |
| 409  | Conflict                      |
| 413  | File too large                |
| 415  | Unsupported file type         |
| 429  | Rate limit exceeded           |
| 500  | Internal error                |
