# 08 — Service Implementation Guide

This file describes backend services and implementation details.

## Backend folder structure

```text
backend/
  app/
    main.py
    config.py
    database.py
    logging.py

    api/
      documents.py
      chat.py
      evaluations.py
      pipeline.py
      health.py

    models/
      user.py
      organization.py
      document.py
      chat.py
      evaluation.py

    schemas/
      documents.py
      chat.py
      evaluations.py
      common.py

    services/
      auth_service.py
      storage_service.py
      document_service.py
      extraction_service.py
      chunking_service.py
      embedding_service.py
      qdrant_service.py
      retrieval_service.py
      rerank_service.py
      prompt_service.py
      llm_service.py
      citation_service.py
      confidence_service.py
      evaluation_service.py
      usage_service.py

    workers/
      celery_app.py
      document_tasks.py
      evaluation_tasks.py

    tests/
      test_chunking.py
      test_retrieval.py
      test_api_chat.py
```

## Configuration

Use environment variables.

```env
ENVIRONMENT=development
API_BASE_URL=http://localhost:8000
FRONTEND_BASE_URL=http://localhost:3000

DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/rag_app

QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=documents

MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=documents
MINIO_SECURE=false

RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672//
REDIS_URL=redis://redis:6379/0

OPENAI_API_KEY=
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_LLM_MODEL=gpt-5.4-mini

AUTH_PROVIDER=clerk
CLERK_JWKS_URL=
SUPABASE_JWKS_URL=

SENTRY_DSN=
LOG_LEVEL=INFO
```

## Document processing task

Pseudo-code:

```python
def process_document(document_id: str):
    document = db.documents.get(document_id)
    mark_status(document_id, "processing")

    try:
        file_bytes = storage.download(document.storage_object_key)

        pages = extraction.extract(
            file_bytes=file_bytes,
            file_type=document.file_type
        )

        cleaned_pages = [clean_page(page) for page in pages]
        db.document_pages.insert_many(cleaned_pages)

        chunks = chunking.chunk_pages(
            document_id=document_id,
            pages=cleaned_pages,
            chunk_size_tokens=700,
            overlap_tokens=120
        )

        db.document_chunks.insert_many(chunks)

        embeddings = embedding.embed_texts([chunk.text for chunk in chunks])

        qdrant.upsert_chunks(
            chunks=chunks,
            embeddings=embeddings,
            organization_id=document.organization_id
        )

        mark_status(document_id, "indexed")

    except Exception as exc:
        mark_status(document_id, "failed", error_message=str(exc))
        raise
```

## Extraction service

### PDF with PyMuPDF

```python
def extract_pdf(file_path: str) -> list[dict]:
    import fitz

    doc = fitz.open(file_path)
    pages = []

    for page_index, page in enumerate(doc):
        text = page.get_text("text")
        pages.append({
            "page_number": page_index + 1,
            "text": text
        })

    return pages
```

### TXT

```python
def extract_txt(file_bytes: bytes) -> list[dict]:
    text = file_bytes.decode("utf-8", errors="ignore")
    return [{"page_number": 1, "text": text}]
```

### DOCX

```python
def extract_docx(file_path: str) -> list[dict]:
    from docx import Document

    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n".join(paragraphs)

    return [{"page_number": 1, "text": text}]
```

## Text cleaning

```python
def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

## Chunking service

Start with recursive word/token chunking.

```python
def chunk_text(text: str, chunk_size: int = 700, overlap: int = 120):
    tokens = tokenize(text)
    chunks = []
    start = 0

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(detokenize(chunk_tokens))
        start += chunk_size - overlap

    return chunks
```

Production requirements:

- Never create empty chunks.
- Skip chunks below minimum token threshold unless document is very small.
- Store page number.
- Store chunk index.
- Store token count.
- Store index version.

## Embedding service

```python
class EmbeddingService:
    def __init__(self, client, model_name: str):
        self.client = client
        self.model_name = model_name

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(
            model=self.model_name,
            input=texts
        )
        return [item.embedding for item in response.data]
```

Production requirements:

- Batch embeddings.
- Retry transient errors.
- Track token/cost usage.
- Store embedding model name.
- Handle rate limits.

## Qdrant service

Responsibilities:

- Create collection if missing.
- Upsert chunk vectors.
- Search with metadata filters.
- Delete by document ID.
- Count vectors by document.

Search filter example:

```python
qdrant_filter = {
    "must": [
        {"key": "organization_id", "match": {"value": organization_id}},
        {"key": "document_id", "match": {"any": document_ids}}
    ]
}
```

## Retrieval service

Pseudo-code:

```python
def retrieve_context(question, organization_id, document_ids, top_k=5):
    query_vector = embedding_service.embed_texts([question])[0]

    candidates = qdrant.search(
        vector=query_vector,
        organization_id=organization_id,
        document_ids=document_ids,
        limit=20
    )

    reranked = rerank_service.rerank(
        query=question,
        candidates=candidates,
        top_k=top_k
    )

    return reranked
```

## Reranking service

Start with MMR.

Later add a cross-encoder.

```python
def mmr_rerank(candidates, lambda_mult=0.7, top_k=5):
    # Balance relevance and diversity.
    pass
```

## Prompt service

```python
def build_rag_prompt(question: str, chunks: list[dict]) -> str:
    context_blocks = []

    for i, chunk in enumerate(chunks, start=1):
        block = (
            f"Source {i}\n"
            f"Document: {chunk['filename']}\n"
            f"Page: {chunk['page_number']}\n"
            f"Chunk ID: {chunk['chunk_id']}\n"
            f"Text:\n{chunk['text']}\n"
        )
        context_blocks.append(block)

    context = "\n\n".join(context_blocks)

    return (
        "You are an AI document assistant.\n\n"
        "Answer only using the context below.\n"
        "If the answer is not in the context, say:\n"
        "\"I could not find this information in the uploaded documents.\"\n\n"
        f"Question:\n{question}\n\n"
        f"Context:\n{context}\n\n"
        "Return JSON with: answer, citations, and not_found."
    )
```

## LLM service

Responsibilities:

- Send prompt to model.
- Request structured JSON output when possible.
- Retry transient errors.
- Track latency, input tokens, output tokens, and cost.
- Handle refusal/not-found cases.

## Citation service

Validation rules:

1. Citation chunk IDs must exist in retrieved context.
2. Cited text snippets must appear in or be supported by cited chunks.
3. Do not allow model-generated fake filenames.
4. If citations are invalid, fallback to retrieved chunks as citations.

## Confidence service

Inputs:

- Top similarity score.
- Average similarity score.
- Rerank score.
- Number of citations.
- Citation validation success.
- Not-found flag.

Example categories:

```text
0.80–1.00 = High
0.50–0.79 = Medium
0.00–0.49 = Low
```

## Evaluation service

Evaluation steps:

1. Load evaluation set.
2. Run query pipeline for each question.
3. Compare retrieved chunks to expected source.
4. Score generated answer.
5. Score citation correctness.
6. Store results.
7. Generate summary.

## Idempotency

All Celery tasks must be idempotent.

Rules:

- Use document status transitions.
- Delete existing chunks/vectors before re-indexing the same version.
- Use stable Qdrant point IDs.
- Use database unique constraints.
- Store task attempt logs.

## Logging

Use structured logs.

Example log event:

```json
{
  "event": "document_indexed",
  "document_id": "uuid",
  "organization_id": "uuid",
  "chunk_count": 92,
  "duration_ms": 18400
}
```
