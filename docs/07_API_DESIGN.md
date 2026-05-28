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
    "postgres": { "ok": false, "detail": "postgres_unreachable", "metadata": { "dsn": "postgresql+asyncpg://db:5432/rag_app" } },
    "redis": { "ok": true, "detail": null, "metadata": { "url": "redis://redis:6379/0" } },
    "rabbitmq": { "ok": true, "detail": null, "metadata": { "url": "amqp://rabbitmq:5672//" } },
    "minio": { "ok": true, "detail": null, "metadata": { "endpoint": "http://minio:9000", "bucket": "documents" } },
    "qdrant": { "ok": true, "detail": null, "metadata": { "url": "http://qdrant:6333", "collection": "documents" } },
    "openai_config": { "ok": true, "detail": null, "metadata": { "api_key_set": true, "embedding_model": "text-embedding-3-small", "llm_model": "gpt-5.4-mini" } }
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
6. Generate a `document_id` and MinIO object key: `uploads/{organization_id}/{user_id}/{document_id}.{ext}`.
7. Upload to MinIO.
8. Insert `documents` row with status `uploaded`, bucket/object key, and checksum.
9. Publish `documents.process` task with `document_id`, `organization_id`, `user_id`, and `request_id`.
10. Worker extracts text by file type and normalizes page text (null-byte/control-char cleanup and whitespace normalization).
11. Worker stores `document_pages(page_number, text, char_count)` with page boundaries preserved.
12. Worker chunks cleaned pages with configured token size/overlap and stores `document_chunks` metadata (`page_number`, `chunk_index`, `token_count`, `embedding_model`, `index_version`).
13. If chunk windows span page boundaries, chunk `page_number` is attributed to the dominant page in the window for citation safety.
14. Worker generates embeddings for all chunks in provider-safe batches using the configured embedding model.
15. Transient embedding provider failures are retried with backoff; permanent embedding failures mark document `failed`.
16. Worker upserts embeddings to Qdrant in batches using deterministic UUIDv5 point IDs derived from `{document_id}:{index_version}:{chunk_index}`.
17. Qdrant payload includes filter/citation fields: `organization_id`, `user_id`, `document_id`, `chunk_id`, `filename`, `file_type`, `page_number`, `chunk_index`, `text`, `embedding_model`, `index_version`.
18. Worker records embedding usage telemetry (`input_tokens`, `latency_ms`, approximate `cost_usd`) in `usage_events` for downstream billing/analytics integration.
19. On successful extraction/chunking/embedding/index upsert, document status becomes `indexed`; empty/malformed extraction marks document `failed`.
20. Worker logs cleaning/chunking/embedding stats (`cleaning_*`, `chunk_count`, `index_version`, `embedding_*`) for pipeline observability.
21. Worker persists `pipeline_runs` + `pipeline_events` rows for node-level lifecycle visibility (`extract`, `index_cleanup`, `chunk`, `embed`, `index`).
22. Event payloads store sanitized previews (`inputs`, `outputs`, `config`, `logs`, `error_details`) and redact secret-like fields.
23. Terminal failures persist a safe `error_message` and structured `error_details` for frontend status polling.

Queue publish failure behavior:

- Upload remains persisted with document status `uploaded` so processing can be retried.
- API returns `503` with a safe enqueue-failure message.

Duplicate policy:

- Duplicate uploads are currently accepted as separate documents. Each upload gets a new `document_id` and object key even when checksum matches a previous upload.

### GET `/documents`

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
  "page_count": 24,
  "chunk_count": 92,
  "checksum": "sha256:...",
  "error_message": null,
  "error_details": null,
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:04:00Z"
}
```

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

### GET `/documents/{document_id}/status`

Returns a compact status payload for polling-only clients.

Response:

```json
{
  "document_id": "uuid",
  "status": "processing",
  "error_message": null,
  "error_details": null,
  "updated_at": "2026-05-07T10:04:00Z"
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
      "index_version": "v1"
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

- Document is already `processing`.
- Document is `deleting`.
- Document is `deleted`.

Notes:

- Access is restricted to `owner` and `admin` roles.
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
- Prompt builder enforces grounded-only behavior: no outside knowledge, no fake citations, and explicit treatment of retrieved document text as untrusted input.
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
    "llm_model": "gpt-5.4-mini"
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
    "top_k": 5,
    "rerank": true,
    "model_name": "gpt-5.4-mini",
    "selected_document_ids": ["uuid"],
    "metric_options": {
      "faithfulness": true,
      "citation_accuracy": true
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
- If duplicate active-run prevention is enabled, concurrent queued/running runs for the same set return `409`.
- Worker computes per-question metrics (`retrieval_hit_rate`, `context_precision`, `context_recall`, `faithfulness_score`, `answer_relevance_score`, `citation_accuracy_score`, `refusal_accuracy`, latency, and cost) and stores them in `evaluation_results.details.metrics`.
- Worker also writes a run summary to `evaluation_runs.config.metrics_summary` with aggregated means/rates and latency/cost/token totals.
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
    "top_k": 5,
    "rerank": true,
    "model_name": "gpt-5.4-mini",
    "selected_document_ids": ["uuid"],
    "metric_options": {
      "faithfulness": true,
      "answer_relevance": true
    }
  },
  "summary": {
    "question_total_count": 20,
    "question_success_count": 19,
    "question_failure_count": 1,
    "retrieval_hit_rate": 0.86,
    "context_precision": 0.71,
    "context_recall": 0.80,
    "faithfulness_score": 0.81,
    "answer_relevance_score": 0.84,
    "citation_accuracy_score": 0.78,
    "refusal_accuracy": 1.0,
    "latency_ms_total": 29000,
    "latency_ms_average": 1450.0,
    "cost_usd_total": 0.043,
    "cost_usd_average": 0.0023
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
  "steps": ["extract", "clean", "chunk", "embed", "index", "retrieve", "rerank", "generate", "evaluate"]
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

### PATCH `/admin/governance`

Updates organization-scoped governance policy fields.

Safe update semantics:

- unknown tool names are rejected (`422`)
- side-effect tool changes require explicit acknowledgment (`side_effect_warning_acknowledged=true`)
- policy changes are audit-logged as `admin.governance.policy.updated`

The endpoint returns the updated effective policy, changed field names, and whether an audit record was written.

## Rate limits

Recommended:

| Endpoint | Limit |
|---|---|
| `/documents/upload` | 20 uploads/hour/user |
| `/chat` | 60 questions/hour/user |
| `/evaluations/run` | Admin only |
| `/retrieval/search` | Admin/debug only |

## Status codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 201 | Created |
| 202 | Accepted for async processing |
| 400 | Invalid request |
| 401 | Not authenticated |
| 403 | Not authorized |
| 404 | Not found or inaccessible |
| 409 | Conflict |
| 413 | File too large |
| 415 | Unsupported file type |
| 429 | Rate limit exceeded |
| 500 | Internal error |
