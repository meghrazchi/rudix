# AI Document Q&A Assistant — Production Architecture Docs

This documentation bundle defines the production architecture for a RAG-powered AI Document Q&A Assistant.

## Documentation navigation

- Main docs index: [docs/README.md](docs/README.md)
- Frontend setup and standards: [frontend/README.md](frontend/README.md)
- Installation and configuration: [docs/INSTALL.md](docs/INSTALL.md)
- Contribution guide: [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)
- Code of conduct: [docs/CODE_OF_CONDUCT.md](docs/CODE_OF_CONDUCT.md)
- Security policy: [docs/SECURITY.md](docs/SECURITY.md)
- Changelog: [docs/CHANGELOG.md](docs/CHANGELOG.md)
- Documentation standards: [docs/DOCUMENTATION_STANDARDS.md](docs/DOCUMENTATION_STANDARDS.md)

## Base stack

```text
Frontend:        Next.js + React + Tailwind CSS
Backend:         FastAPI
Database:        PostgreSQL
Vector search:   Qdrant
File storage:    MinIO
Auth:            Auth0 or Clerk
Queue:           Celery + RabbitMQ
Cache:           Redis
PDF processing:  PyMuPDF
DOCX processing: python-docx
Embeddings:      OpenAI embeddings
LLM:             Configurable OpenAI model, for example gpt-5.4-mini
Evaluation:      RAGAS + custom metrics
Deployment:      Containerized frontend + backend (self-hosted)
Monitoring:      Sentry + structured logs
```

## Documents included

| File | Purpose |
|---|---|
| `docs/01_ARCHITECTURE_OVERVIEW.md` | Full system architecture and design principles |
| `docs/02_PRODUCTION_STACK.md` | Final stack choices and why each tool is used |
| `docs/03_RAG_WORKFLOW.md` | RAG ingestion, query, generation, and evaluation workflows |
| `docs/04_COMPONENT_DIAGRAMS.md` | Mermaid component, deployment, and data-flow diagrams |
| `docs/05_SEQUENCE_DIAGRAMS.md` | Upload, indexing, query, evaluation, and deletion sequence diagrams |
| `docs/06_DATABASE_SCHEMA.md` | PostgreSQL schema, ERD, and table explanations |
| `docs/07_API_DESIGN.md` | FastAPI endpoints, request/response contracts, errors |
| `docs/08_SERVICE_IMPLEMENTATION_GUIDE.md` | Backend service modules and implementation details |
| `docs/09_FRONTEND_UI_DESIGN.md` | Next.js page structure, UI components, RAG pipeline explorer |
| `docs/10_DEPLOYMENT_DOCKER.md` | Docker Compose, service layout, env vars, deployment notes |
| `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` | Security, auth, permission checks, prompt-injection controls |
| `docs/12_EVALUATION_AND_MONITORING.md` | RAGAS, custom metrics, logs, Sentry, latency/cost tracking |

## Recommended implementation order

1. Create backend project structure.
2. Add PostgreSQL models and migrations.
3. Add MinIO upload flow.
4. Add Celery + RabbitMQ worker setup.
5. Add PDF/TXT/DOCX text extraction.
6. Add chunking and metadata persistence.
7. Add OpenAI embeddings.
8. Add Qdrant indexing and retrieval.
9. Add query pipeline and answer generation.
10. Add citations and confidence scoring.
11. Build Next.js UI.
12. Add evaluation pipeline.
13. Add monitoring and production security controls.
14. Deploy frontend and backend stack using Docker (Compose or Kubernetes).
