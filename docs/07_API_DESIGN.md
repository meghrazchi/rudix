# 07 — API Design

FastAPI exposes the production backend API.

## API principles

1. Every endpoint must verify authentication.
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

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document not found or access denied.",
    "details": {}
  }
}
```

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

## Documents

### POST `/documents/upload`

Upload a document.

Request:

```http
multipart/form-data
file=<PDF|TXT|DOCX>
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

### POST `/chat`

Main real-time RAG query endpoint.

Request:

```json
{
  "question": "What is the leave policy?",
  "chat_session_id": "uuid-optional",
  "document_ids": ["uuid"],
  "top_k": 5,
  "rerank": true
}
```

Notes:

- `rerank=true` applies MMR reranking on retrieved candidates before prompt construction.
- MMR behavior is configured through `RERANK_MMR_LAMBDA`, `RERANK_MMR_CANDIDATE_COUNT`, and `RERANK_MMR_DUPLICATE_SIMILARITY_THRESHOLD`.
- `rerank=false` returns raw retrieval ordering (similarity-only) up to `top_k`.
- When `FEATURE_ENABLE_GRAPH_RAG=true`, the backend may expand Qdrant hits with
  evidence-backed Neo4j context that is still scoped to the caller organization
  and allowed document IDs. Graph-only facts are not cited unless a matching
  document/chunk reference exists in the retrieved context.
- Prompt builder enforces grounded-only behavior: no outside knowledge, no fake citations, and explicit treatment of retrieved document text as untrusted input.
- The active `answer_generation` prompt template version is resolved per organization and persisted on assistant chat messages for rollback/evaluation traceability.
- Prompt context blocks include source metadata (`document_id`, `chunk_id`, `filename`, `page_number`) plus retrieval metadata (`similarity_score`, `rerank_score`, `rerank_rank`) and an explicit allowed chunk ID list for citation validation.
- LLM is instructed to return strict JSON (`answer`, `not_found`, `citations`) for deterministic downstream parsing.
- Backend requests JSON mode when supported by the selected model/provider and transparently retries without JSON mode for providers that do not support `response_format`.
- If model output is still not valid structured JSON after retries, backend falls back to a safe not-found response (no citations).
- Model citations are validated against retrieved final context: chunk IDs must exist, filename/page are repaired from authoritative chunk metadata, and quote snippets must match chunk text (exact/fuzzy) or are replaced with safe chunk snippets.
- When model citations are missing or invalid, backend falls back to top retrieved chunks as citations (unless `not_found=true`).
- Citation validation quality contributes to final confidence scoring.
- On success, question/answer/citations and assistant telemetry (`latency_ms`, `model_name`, token counts, `cost_usd`) are persisted transactionally to `chat_messages`/`citations`.
- A `usage_events` row (`event_type=chat.completion`) is recorded transactionally for billing/admin analytics with latency, confidence, and retrieval metadata.
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
      "rerank_score": 0.91,
      "rerank_rank": 1,
      "text_snippet": "Employees receive 20 paid leave days..."
    }
  ],
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

### POST `/chat/sessions/{session_id}/messages`

Ask a question.

Request:

```json
{
  "message": "What is the leave policy?",
  "document_ids": ["uuid"],
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

Current scaffold behavior:

- Endpoint validates authz and document access, then returns `501` until retrieval/generation pipeline implementation is completed.

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

Response (`201 Created`):

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

### GET `/agent/runs/{run_id}`

Returns persisted run state, steps, tool calls, approvals, budget/costs, and safe error metadata.

### GET `/agent/runs/{run_id}/stream`

Reserved endpoint for streaming responses. Currently returns `501 Not Implemented`.

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

### GET `/admin/governance`

Returns organization-scoped governance policy for agent and MCP controls.

Response includes:

- effective policy toggles (`agentic_mode_enabled`, `mcp_exposure_enabled`)
- side-effect guard posture (`allow_side_effect_tools`)
- allowlisted tool names
- runtime budget limits
- external MCP server policy entries (metadata + secret references only)
- global MCP endpoint status and deployment warnings

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
