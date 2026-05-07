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
  "message": "Document uploaded and queued for processing."
}
```

Backend actions:

1. Verify token.
2. Validate file type.
3. Validate file size.
4. Upload to MinIO.
5. Insert `documents` row.
6. Enqueue Celery processing task.

### GET `/documents`

List documents.

Query params:

```text
status=indexed
limit=50
offset=0
```

Response:

```json
{
  "items": [
    {
      "id": "uuid",
      "filename": "policy.pdf",
      "file_type": "pdf",
      "status": "indexed",
      "page_count": 24,
      "created_at": "2026-05-07T10:00:00Z"
    }
  ],
  "total": 1
}
```

### GET `/documents/{document_id}`

Response:

```json
{
  "id": "uuid",
  "filename": "policy.pdf",
  "status": "indexed",
  "page_count": 24,
  "chunk_count": 92,
  "created_at": "2026-05-07T10:00:00Z",
  "updated_at": "2026-05-07T10:04:00Z"
}
```

### GET `/documents/{document_id}/chunks`

Returns chunk previews.

Response:

```json
{
  "document_id": "uuid",
  "chunks": [
    {
      "id": "uuid",
      "page_number": 4,
      "chunk_index": 12,
      "text_preview": "Employees are entitled to...",
      "token_count": 690
    }
  ]
}
```

### DELETE `/documents/{document_id}`

Soft-delete a document and enqueue deletion of MinIO and Qdrant assets.

Response:

```json
{
  "document_id": "uuid",
  "status": "deleting"
}
```

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
  "chat_session_id": "uuid",
  "title": "Policy questions",
  "created_at": "2026-05-07T10:00:00Z"
}
```

### GET `/chat/sessions`

List chat sessions.

Response:

```json
{
  "items": [
    {
      "id": "uuid",
      "title": "Policy questions",
      "created_at": "2026-05-07T10:00:00Z"
    }
  ]
}
```

### POST `/chat`

Ask a question.

Request:

```json
{
  "chat_session_id": "uuid",
  "question": "What is the leave policy?",
  "document_ids": ["uuid"],
  "top_k": 5,
  "rerank": true
}
```

Response:

```json
{
  "message_id": "uuid",
  "answer": "Employees receive 20 paid leave days per year.",
  "confidence_score": 0.87,
  "not_found": false,
  "citations": [
    {
      "document_id": "uuid",
      "chunk_id": "uuid",
      "filename": "employee_policy.pdf",
      "page_number": 4,
      "text_snippet": "Employees are entitled to 20 paid leave days...",
      "similarity_score": 0.89,
      "rerank_score": 0.94
    }
  ],
  "debug": {
    "retrieval_latency_ms": 180,
    "llm_latency_ms": 1200,
    "model_name": "gpt-5.4-mini"
  }
}
```

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
  "evaluation_set_id": "uuid"
}
```

### POST `/evaluation-sets/{evaluation_set_id}/questions`

Add test questions.

Request:

```json
{
  "questions": [
    {
      "question": "How many paid leave days are available?",
      "expected_answer": "20 paid leave days",
      "expected_document_id": "uuid",
      "expected_page_number": 4
    }
  ]
}
```

Response:

```json
{
  "inserted": 1
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
    "model_name": "gpt-5.4-mini"
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

### GET `/evaluations/runs/{evaluation_run_id}`

Response:

```json
{
  "id": "uuid",
  "status": "completed",
  "summary": {
    "retrieval_hit_rate": 0.86,
    "faithfulness": 0.81,
    "citation_accuracy": 0.78,
    "average_latency_ms": 1450
  }
}
```

## Pipeline explorer

### GET `/pipeline/runs/{document_id}`

Returns node statuses for a document processing run.

Response:

```json
{
  "document_id": "uuid",
  "nodes": [
    {
      "id": "upload",
      "label": "Upload",
      "status": "completed",
      "started_at": "2026-05-07T10:00:00Z",
      "completed_at": "2026-05-07T10:00:03Z"
    },
    {
      "id": "chunking",
      "label": "Chunking",
      "status": "completed",
      "metrics": {
        "chunk_count": 92,
        "average_tokens": 640
      }
    }
  ]
}
```

### GET `/pipeline/runs/{document_id}/nodes/{node_id}`

Returns details for one node.

Response:

```json
{
  "node_id": "chunking",
  "title": "Chunking",
  "status": "completed",
  "description": "Split extracted text into overlapping chunks.",
  "inputs": {
    "pages": 24
  },
  "outputs": {
    "chunks": 92
  },
  "config": {
    "chunk_size_tokens": 700,
    "overlap_tokens": 120
  },
  "logs": [
    "Created 92 chunks from 24 pages."
  ]
}
```

## Admin endpoints

### GET `/admin/usage`

Returns usage statistics.

```json
{
  "total_questions": 1200,
  "total_documents": 84,
  "total_tokens": 950000,
  "estimated_cost_usd": 12.45
}
```

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
