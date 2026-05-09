# 02 — Production Stack

## Final stack

| Layer | Choice | Purpose |
|---|---|---|
| Frontend | Next.js + React + Tailwind CSS | Production web app UI |
| Backend | FastAPI | Python API service for RAG and app logic |
| Database | PostgreSQL | Relational source of truth |
| Vector search | Qdrant | Vector database for semantic retrieval |
| File storage | MinIO | S3-compatible storage for uploaded files |
| Auth | Supabase Auth or Clerk | User authentication |
| Queue | Celery + RabbitMQ | Reliable background processing |
| Cache | Redis | Cache, rate limiting, optional task result backend |
| PDF processing | PyMuPDF | PDF text extraction |
| DOCX processing | python-docx | DOCX text extraction |
| Embeddings | OpenAI embeddings | Chunk and query embeddings |
| LLM | Configurable OpenAI model | Answer generation |
| Evaluation | RAGAS + custom metrics | RAG quality evaluation |
| Deployment | Containerized frontend + backend | Production deployment |
| Monitoring | Sentry + structured logs | Error tracking and observability |

## Frontend: Next.js + React + Tailwind CSS

Use Next.js for the customer-facing app.

### Responsibilities

- Login and signup.
- Dashboard.
- Document upload.
- Document status view.
- Chat interface.
- Citation/source viewer.
- Evaluation dashboard.
- Admin/debug tools.
- Interactive RAG pipeline explorer.

### Suggested frontend libraries

| Need | Library |
|---|---|
| Styling | Tailwind CSS |
| UI components | shadcn/ui |
| Forms | React Hook Form + Zod |
| API calls | TanStack Query |
| Tables | TanStack Table |
| Diagrams | React Flow |
| Auth UI | Clerk or Supabase Auth helpers |
| Charts | Recharts |
| Toasts | Sonner |

## Backend: FastAPI

FastAPI handles all API endpoints and orchestrates RAG services.

### Responsibilities

- Verify auth tokens.
- Enforce authorization.
- Create document records.
- Generate MinIO upload/download links.
- Start Celery jobs.
- Run real-time query pipeline.
- Store chat messages and citations.
- Trigger evaluation jobs.
- Emit structured logs.

## Database: PostgreSQL

Use PostgreSQL as the source of truth.

Store:

- Users and organizations.
- Documents and file metadata.
- Extracted pages.
- Chunk metadata.
- Chat sessions.
- Questions and answers.
- Citations.
- Evaluation datasets and runs.
- Usage events.
- Audit logs.

Do not store large PDF files in PostgreSQL. Store them in MinIO and keep only the object key in PostgreSQL.

## Vector database: Qdrant

Use Qdrant to store embeddings.

Each point should contain:

```json
{
  "id": "chunk_uuid",
  "vector": [0.01, -0.02, 0.33],
  "payload": {
    "organization_id": "org_uuid",
    "user_id": "user_uuid",
    "document_id": "doc_uuid",
    "chunk_id": "chunk_uuid",
    "filename": "policy.pdf",
    "page_number": 4,
    "chunk_index": 12,
    "text": "Employees are entitled to...",
    "created_at": "2026-05-07T10:00:00Z"
  }
}
```

Use payload filters for security:

```text
organization_id = current user's organization
document_id in selected document IDs
```

## File storage: MinIO

Use MinIO for:

- Original uploaded PDFs.
- Original uploaded TXT/DOCX files.
- Extracted text artifacts.
- Optional generated reports.

Bucket structure:

```text
documents/
  org_{organization_id}/
    user_{user_id}/
      doc_{document_id}/
        original.pdf
        extracted_pages.json
        processing_log.json
```

## Auth: Supabase Auth or Clerk

Both are valid.

### Use Supabase Auth if:

- You want auth integrated with PostgreSQL and row-level security patterns.
- You may later use Supabase-managed Postgres.

### Use Clerk if:

- You want polished auth UI and organization management.
- You want fast SaaS-style user management.

Backend should not trust frontend-only checks. Every API request must verify the auth token.

## Queue: Celery + RabbitMQ

Use Celery workers for long-running tasks.

Tasks:

- Extract text.
- Chunk documents.
- Generate embeddings.
- Index chunks in Qdrant.
- Run evaluations.
- Delete/re-index documents.
- Retry failed processing.

RabbitMQ is used as the broker for reliable task delivery.

## Cache: Redis

Use Redis for:

- Caching recent retrieval results.
- Rate limiting.
- Temporary task status.
- Optional Celery result backend.
- Short-lived session/cache values.

## Embeddings

Recommended:

```text
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Keep the model configurable.

Rules:

- Use the same embedding model for chunks and queries.
- Store the embedding model name with each document or index version.
- Re-index documents when switching embedding models.

## LLM

Use a configurable OpenAI model.

Example environment variable:

```env
OPENAI_LLM_MODEL=gpt-5.4-mini
LLM_RETRY_MAX_ATTEMPTS=2
LLM_RETRY_BASE_SECONDS=0.4
LLM_RETRY_MAX_SECONDS=3
OPENAI_LLM_INPUT_COST_PER_MILLION_TOKENS_USD=0.0
OPENAI_LLM_OUTPUT_COST_PER_MILLION_TOKENS_USD=0.0
```

Do not hardcode model names in service code.

## Evaluation

Use two evaluation layers:

1. **Automated RAG evaluation**
   - RAGAS faithfulness.
   - Answer relevancy.
   - Context precision.
   - Context recall.

2. **Custom production metrics**
   - Retrieval hit rate.
   - Citation accuracy.
   - Refusal accuracy.
   - Latency.
   - Cost.
   - User feedback score.

## Deployment

Recommended:

```text
Frontend: Next.js container (self-hosted)
Backend API: Docker container
Workers: Docker containers
PostgreSQL: managed or containerized
Qdrant: managed or containerized
MinIO: containerized or managed S3-compatible storage
RabbitMQ: containerized or managed
Redis: managed or containerized
```

For local development, use Docker Compose for all backend services.
