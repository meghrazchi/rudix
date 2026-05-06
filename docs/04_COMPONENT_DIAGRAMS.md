# 04 — Component Diagrams

## System component diagram

```mermaid
flowchart TD
    subgraph Client["Client Layer"]
        Browser[User Browser]
        Next[Next.js App]
    end

    subgraph API["Application Layer"]
        FastAPI[FastAPI API]
        AuthMiddleware[Auth Middleware]
        DocumentAPI[Document API]
        ChatAPI[Chat API]
        EvalAPI[Evaluation API]
    end

    subgraph Services["Backend Services"]
        StorageService[Storage Service]
        DocumentService[Document Service]
        ExtractionService[Extraction Service]
        ChunkingService[Chunking Service]
        EmbeddingService[Embedding Service]
        RetrievalService[Retrieval Service]
        RerankService[Rerank Service]
        PromptService[Prompt Builder]
        LLMService[LLM Service]
        CitationService[Citation Service]
        EvaluationService[Evaluation Service]
    end

    subgraph Async["Async Processing"]
        RabbitMQ[RabbitMQ]
        Celery[Celery Workers]
    end

    subgraph Data["Data Layer"]
        PostgreSQL[(PostgreSQL)]
        Qdrant[(Qdrant)]
        MinIO[(MinIO)]
        Redis[(Redis)]
    end

    subgraph External["External Services"]
        AuthProvider[Supabase Auth / Clerk]
        OpenAI[OpenAI APIs]
        Sentry[Sentry]
    end

    Browser --> Next
    Next --> FastAPI

    FastAPI --> AuthMiddleware
    AuthMiddleware --> AuthProvider

    FastAPI --> DocumentAPI
    FastAPI --> ChatAPI
    FastAPI --> EvalAPI

    DocumentAPI --> DocumentService
    ChatAPI --> RetrievalService
    EvalAPI --> EvaluationService

    DocumentService --> StorageService
    DocumentService --> RabbitMQ

    RabbitMQ --> Celery
    Celery --> ExtractionService
    Celery --> ChunkingService
    Celery --> EmbeddingService
    Celery --> EvaluationService

    StorageService --> MinIO
    DocumentService --> PostgreSQL
    ExtractionService --> MinIO
    ExtractionService --> PostgreSQL
    ChunkingService --> PostgreSQL
    EmbeddingService --> OpenAI
    EmbeddingService --> Qdrant

    RetrievalService --> EmbeddingService
    RetrievalService --> Qdrant
    RetrievalService --> RerankService
    RerankService --> PromptService
    PromptService --> LLMService
    LLMService --> OpenAI
    LLMService --> CitationService
    CitationService --> PostgreSQL

    FastAPI --> Redis
    FastAPI --> Sentry
    Celery --> Sentry
```

## Deployment diagram

```mermaid
flowchart TD
    subgraph Vercel["Vercel"]
        FE[Next.js Frontend]
    end

    subgraph BackendHost["Backend Docker Host / Cloud"]
        API[FastAPI Container]
        Worker1[Celery Worker Container]
        Worker2[Celery Worker Container]
        Beat[Celery Beat Optional]
    end

    subgraph DataHost["Data Services"]
        PG[(PostgreSQL)]
        QD[(Qdrant)]
        MO[(MinIO)]
        RMQ[(RabbitMQ)]
        RD[(Redis)]
    end

    subgraph External["External Managed Services"]
        Auth[Supabase Auth / Clerk]
        OpenAI[OpenAI]
        Sentry[Sentry]
    end

    FE --> API
    API --> Auth
    API --> PG
    API --> QD
    API --> MO
    API --> RMQ
    API --> RD
    API --> OpenAI
    API --> Sentry

    RMQ --> Worker1
    RMQ --> Worker2
    Worker1 --> PG
    Worker1 --> QD
    Worker1 --> MO
    Worker1 --> OpenAI
    Worker1 --> Sentry

    Worker2 --> PG
    Worker2 --> QD
    Worker2 --> MO
    Worker2 --> OpenAI
    Worker2 --> Sentry

    Beat --> RMQ
```

## RAG data-flow diagram

```mermaid
flowchart LR
    F[Original File] --> O[MinIO Object]
    O --> P[Page Text Extraction]
    P --> C[Chunks]
    C --> M[Chunk Metadata in PostgreSQL]
    C --> E[Embeddings]
    E --> V[Qdrant Vectors]

    Q[User Question] --> QE[Query Embedding]
    QE --> S[Qdrant Search]
    V --> S
    S --> R[Reranked Context]
    M --> R
    R --> Prompt[Prompt]
    Prompt --> LLM[LLM]
    LLM --> A[Answer]
    R --> Cit[Citations]
    A --> UI[Next.js UI]
    Cit --> UI
```

## Bounded context diagram

```mermaid
flowchart TD
    subgraph Identity["Identity Context"]
        Auth[Auth Provider]
        Users[Users]
        Organizations[Organizations]
    end

    subgraph Documents["Document Context"]
        Upload[Upload]
        Storage[MinIO Storage]
        Metadata[Document Metadata]
        Processing[Processing Jobs]
    end

    subgraph Retrieval["Retrieval Context"]
        Chunks[Chunks]
        Embeddings[Embeddings]
        VectorIndex[Qdrant Index]
        Search[Semantic Search]
    end

    subgraph Conversation["Conversation Context"]
        Chat[Chat Sessions]
        Messages[Messages]
        Answers[Answers]
        Citations[Citations]
    end

    subgraph Evaluation["Evaluation Context"]
        TestSets[Test Sets]
        EvalRuns[Evaluation Runs]
        Metrics[Metrics]
    end

    Identity --> Documents
    Documents --> Retrieval
    Retrieval --> Conversation
    Conversation --> Evaluation
```

## RAG pipeline explorer UI component diagram

```mermaid
flowchart TD
    Page[RAG Pipeline Explorer Page] --> Flow[React Flow Canvas]
    Page --> Panel[Node Details Side Panel]
    Page --> Filters[Document / Run Filters]

    Flow --> UploadNode[Upload Node]
    Flow --> ExtractNode[Extract Node]
    Flow --> ChunkNode[Chunking Node]
    Flow --> EmbedNode[Embedding Node]
    Flow --> VectorNode[Qdrant Node]
    Flow --> QueryNode[Query Node]
    Flow --> RetrieveNode[Retrieve Node]
    Flow --> RerankNode[Rerank Node]
    Flow --> PromptNode[Prompt Node]
    Flow --> LLMNode[LLM Node]
    Flow --> AnswerNode[Answer Node]
    Flow --> EvalNode[Evaluation Node]

    UploadNode --> Panel
    ExtractNode --> Panel
    ChunkNode --> Panel
    EmbedNode --> Panel
    VectorNode --> Panel
    QueryNode --> Panel
    RetrieveNode --> Panel
    RerankNode --> Panel
    PromptNode --> Panel
    LLMNode --> Panel
    AnswerNode --> Panel
    EvalNode --> Panel

    Panel --> API[FastAPI Pipeline Run API]
```

## Infrastructure dependency diagram

```mermaid
flowchart TD
    API[FastAPI] --> PG[(PostgreSQL)]
    API --> MINIO[(MinIO)]
    API --> QDRANT[(Qdrant)]
    API --> RABBIT[(RabbitMQ)]
    API --> REDIS[(Redis)]
    API --> AUTH[Auth Provider]
    API --> OPENAI[OpenAI]
    API --> SENTRY[Sentry]

    WORKER[Celery Worker] --> PG
    WORKER --> MINIO
    WORKER --> QDRANT
    WORKER --> RABBIT
    WORKER --> REDIS
    WORKER --> OPENAI
    WORKER --> SENTRY

    FRONTEND[Next.js] --> API
    FRONTEND --> AUTH
```
