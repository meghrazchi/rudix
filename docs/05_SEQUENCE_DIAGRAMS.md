# 05 — Sequence Diagrams

## 1. Upload and indexing sequence

```mermaid
sequenceDiagram
    actor User
    participant FE as Next.js Frontend
    participant API as FastAPI Backend
    participant Auth as Auth Provider
    participant DB as PostgreSQL
    participant MinIO as MinIO
    participant MQ as RabbitMQ
    participant Worker as Celery Worker
    participant OpenAI as OpenAI Embeddings
    participant Qdrant as Qdrant

    User->>FE: Select PDF/TXT/DOCX
    FE->>API: POST /documents/upload
    API->>Auth: Verify access token
    Auth-->>API: Valid user claims
    API->>API: Validate file type and size
    API->>MinIO: Store original file
    MinIO-->>API: object_key
    API->>DB: Insert document(status=uploaded)
    API->>MQ: Enqueue process_document(document_id)
    API-->>FE: Upload accepted + document_id

    MQ-->>Worker: process_document(document_id)
    Worker->>DB: Load document metadata
    Worker->>MinIO: Download original file
    Worker->>Worker: Extract text
    Worker->>Worker: Clean text
    Worker->>Worker: Chunk text
    Worker->>DB: Insert pages and chunks
    Worker->>OpenAI: Create chunk embeddings
    OpenAI-->>Worker: Embeddings
    Worker->>Qdrant: Upsert vectors with payload
    Worker->>DB: Update document(status=indexed)
```

## 2. Real-time question answering sequence

```mermaid
sequenceDiagram
    actor User
    participant FE as Next.js Frontend
    participant API as FastAPI Backend
    participant Auth as Auth Provider
    participant DB as PostgreSQL
    participant OpenAI as OpenAI
    participant Qdrant as Qdrant
    participant Rerank as Reranker
    participant LLM as LLM

    User->>FE: Ask question
    FE->>API: POST /chat
    API->>Auth: Verify token
    Auth-->>API: User + organization claims
    API->>DB: Validate document permissions
    API->>OpenAI: Embed query
    OpenAI-->>API: Query vector
    API->>Qdrant: Search top-k with metadata filters
    Qdrant-->>API: Candidate chunks
    API->>Rerank: Rerank candidates
    Rerank-->>API: Final context chunks
    API->>API: Build grounded prompt
    API->>LLM: Generate answer
    LLM-->>API: Answer JSON
    API->>API: Validate citations
    API->>API: Compute confidence
    API->>DB: Store message, answer, citations
    API-->>FE: Answer + citations + confidence
    FE-->>User: Display response
```

## 3. Evaluation run sequence

```mermaid
sequenceDiagram
    actor Admin
    participant FE as Next.js Admin UI
    participant API as FastAPI Backend
    participant DB as PostgreSQL
    participant MQ as RabbitMQ
    participant Worker as Celery Worker
    participant Qdrant as Qdrant
    participant LLM as LLM / RAGAS Judge

    Admin->>FE: Start evaluation
    FE->>API: POST /evaluations/run
    API->>DB: Create evaluation_run(status=queued)
    API->>MQ: Enqueue run_evaluation(evaluation_run_id)
    API-->>FE: Evaluation queued

    MQ-->>Worker: run_evaluation
    Worker->>DB: Load test questions
    loop For each test question
        Worker->>Qdrant: Retrieve chunks
        Qdrant-->>Worker: Retrieved context
        Worker->>LLM: Generate answer
        LLM-->>Worker: Answer
        Worker->>LLM: Judge faithfulness/relevance if needed
        LLM-->>Worker: Scores
        Worker->>DB: Store evaluation_result
    end
    Worker->>DB: Update evaluation_run(status=completed)
```

## 4. Document deletion sequence

```mermaid
sequenceDiagram
    actor User
    participant FE as Next.js Frontend
    participant API as FastAPI Backend
    participant Auth as Auth Provider
    participant DB as PostgreSQL
    participant Qdrant as Qdrant
    participant MinIO as MinIO
    participant MQ as RabbitMQ
    participant Worker as Celery Worker

    User->>FE: Delete document
    FE->>API: DELETE /documents/{document_id}
    API->>Auth: Verify token
    Auth-->>API: User claims
    API->>DB: Check ownership/permission
    API->>DB: Mark document status=deleting
    API->>MQ: Enqueue delete_document_assets
    API-->>FE: Delete accepted

    MQ-->>Worker: delete_document_assets
    Worker->>Qdrant: Delete vectors by document_id filter
    Worker->>MinIO: Delete object prefix
    Worker->>DB: Delete or soft-delete chunks/pages/document
    Worker->>DB: Mark document status=deleted
```

## 5. Pipeline explorer sequence

```mermaid
sequenceDiagram
    actor User
    participant FE as Pipeline Explorer UI
    participant API as FastAPI Backend
    participant DB as PostgreSQL
    participant Qdrant as Qdrant
    participant MinIO as MinIO

    User->>FE: Click Chunking node
    FE->>API: GET /pipeline/runs/{run_id}/nodes/chunking
    API->>DB: Fetch processing step logs
    API->>DB: Fetch chunk metadata
    API-->>FE: Node details

    User->>FE: Click Qdrant node
    FE->>API: GET /pipeline/runs/{run_id}/nodes/qdrant
    API->>DB: Fetch vector ids
    API->>Qdrant: Count/filter vectors
    Qdrant-->>API: Vector stats
    API-->>FE: Vector index details

    User->>FE: Click Upload node
    FE->>API: GET /pipeline/runs/{run_id}/nodes/upload
    API->>DB: Fetch document metadata
    API->>MinIO: Generate signed preview URL if allowed
    API-->>FE: Upload details
```

## 6. Auth and authorization sequence

```mermaid
sequenceDiagram
    actor User
    participant FE as Next.js
    participant Auth as Supabase Auth / Clerk
    participant API as FastAPI
    participant DB as PostgreSQL

    User->>FE: Login
    FE->>Auth: Authenticate
    Auth-->>FE: Access token
    FE->>API: API request with Bearer token
    API->>Auth: Verify token / JWKS
    Auth-->>API: User identity
    API->>DB: Load user organization and permissions
    DB-->>API: Allowed resources
    API-->>FE: Authorized response
```
