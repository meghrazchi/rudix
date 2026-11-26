# Audit Baseline (v0.1.0)

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md)

## 1. Purpose

Record what the application contains at `0.1.0` and what the November 2026 audit found, so
each roadmap item can be traced to evidence.

## 2. Scope and method

- Code was read at commit `f3447b83`. Line numbers refer to that commit and will drift.
- Five read-only audits covered: API and database, RAG pipeline and workers, frontend,
  infrastructure and CI, and the feature inventory.
- Tests, load tests, and deployments were **not** run. "Verify first" marks a runtime
  consequence inferred from code.
- "Complete" in the catalogue means router, service, UI, and tests exist. It does not mean
  the behaviour was exercised.

## 3. Size of the system

| Measure | Value |
|---|---|
| Backend application code | 691 files, about 148,000 lines |
| Backend domains / tables / migrations | 40 / 118 / 95 |
| Backend tests | 234 files, about 4,050 test functions (SQLite in-memory) |
| Frontend source | 674 files, about 198,000 lines |
| Frontend tests | 200 Vitest files, 10 Playwright specs |
| Locales | en, de, es, fr, ar, fa |
| `FEATURE_*` flags | 44 (18 on, 25 off, 1 environment-derived) |
| Configuration | about 380 settings fields, about 290 variables in `.env.example` |

## 4. Feature catalogue

| # | Area | Feature IDs | Status | Gap |
|---|---|---|---|---|
| 1 | Auth and sessions | 52, 56-57, 95, 168, 305 | Partial | No signup, password-reset, or email-verify endpoint; MFA hardcoded off (`interfaces/http/security_settings.py:174`) |
| 2 | Org, team, roles, permissions | 10, 162, 278, 324, 330-336, 354 | Complete | |
| 3 | Enterprise identity | 160, 161, 165, 264 | Complete | Not tested against a real IdP |
| 4 | Ingestion and upload security | 12-20, 31-32, 62, 131, 142, 200-201, 230, 232, 237, 299 | Complete | Legacy `POST /documents/upload-url` returns 501 |
| 5 | Chunking | 206-216 | Complete | Flags off by default |
| 6 | Retrieval | 24-25, 293-295, 297-298, 300, 340-341, 345 | Complete | Hybrid, rewriting, packing, routing off |
| 7 | Answer generation and trust | 26-29, 145, 268, 296, 301, 306-317, 338-339, 346-347 | Complete | Verifier, conflict detection, planner-critic off |
| 8 | Chat UX | 22-23, 47, 67-71, 134-137, 231, 259, 277, 318-323, 337, 342 | Complete | Legacy `POST /chat/sessions/{id}/messages` returns 501 |
| 9 | Knowledge organisation | 129-130, 253-257, 325, 328 | Complete | |
| 10 | Connectors | 169-170, 238-250, 273-274, 352 | Partial | Confluence, Google Drive, SharePoint/OneDrive, Notion; Jira (242) removed |
| 11 | GraphRAG | 269, 279-291 | Complete | Opt-in, needs Neo4j profile |
| 12 | Agents | 98-106, 171-174, 344 | Partial | Stream endpoint 501; approved runs do not resume |
| 13 | MCP | 107-113, 175-176 | Complete | Off by default |
| 14 | Org memory | 343 | Complete | Off by default |
| 15 | Evaluation and quality | 33-37, 72-76, 146-149, 215, 226, 234, 302-304, 316 | Complete | CI gates are manual-only |
| 16 | Model providers and local LLM | 151-152, 217-229 | Complete | Opt-in |
| 17 | Admin ops and observability | 41-42, 82-86, 140-141, 155-159, 184, 271, 329 | Complete | Metrics stack is a dev overlay |
| 18 | Reports and analytics | 49, 60-61, 153, 258, 348-353 | Complete | |
| 19 | Billing, plans, quotas | 154, 163-164, 191 | Stub | Invoices synthesised from usage; no payment provider |
| 20 | Notifications, email, webhooks | 139, 166, 251 | Partial | No admin UI for email |
| 21 | Collaboration bots | 261 | Partial | Backend only |
| 22 | Settings | 50, 187-196 | Complete | |
| 23 | i18n and RTL | 227, 235-236, 275-276, 366 | Complete | About half of components untranslated |
| 24 | Public site, legal, onboarding, help | 97, 114-128, 177-182, 202-205, 327 | Complete | |
| 25 | Data lifecycle and portability | 143, 186 | Complete | |
| 26 | Platform and CI | 11, 51, 53, 88, 90-91, 94, 96 | Complete | |

Not found anywhere: payments, self-serve signup, MFA, public API docs or SDK, data residency,
backup and restore tooling, mobile app.

## 5. Findings

Paths are relative to `backend/` or `frontend/` as indicated. Severity: C critical, H high,
M medium. The last column is the roadmap item that resolves the finding.

### 5.1 Correctness and security

| Sev | Finding | Evidence | Item |
|---|---|---|---|
| C | WebSocket chat has no plan quota check or usage recording; HTTP has both | `backend/app/interfaces/http/chat.py:2980,4897` vs pipeline at `:6115-7534` | R02-01 |
| C | WebSocket chat lacks the per-document citation authorization filter | `chat.py:3586-3613` (HTTP only) | R02-01 |
| C | Retry or redelivery of `documents.process` returns `skipped` and leaves the document in `processing` | `backend/app/workers/document_tasks.py:3061-3077` | R02-02 |
| C | No Celery beat process in any compose file or Makefile; schedules never fire | `backend/app/workers/celery_app.py:83-92` | R02-03 |
| C | Production Terraform starts `neo4j`; production compose has no such service (verify first) | `deploy/terraform/main.tf:11`, `deploy/compose/docker-compose.production.yml` | R02-08 |
| C | No CSP or security headers in the repo | `frontend/next.config.ts` | R02-09 |
| H | `safety_evals.run` is not in the worker `include` list (verify first) | `celery_app.py:26-32` | R02-04 |
| H | Production retrieval never filters on `index_version`; evaluation re-ingest writes `eval-` versions into the same collection (verify first) | `domains/chat/services/parallel_retrieval_optimizer.py:225-231`, `workers/evaluation_tasks.py:686-722` | R02-05 |
| H | One `AsyncSession` shared across concurrent retrieval branches | `parallel_retrieval_optimizer.py:186,241,283` | R02-06 |
| H | Quota increment is read-modify-write without a lock | `domains/quota/repositories/quota_repository.py:115-130` | R02-07 |
| H | Tenant isolation is application filters only; RLS setter has no callers | `backend/app/db/tenant_context.py:83`, `app/db/rls.py:38-40` | R04-08 |
| H | Access token in `localStorage` and in the WebSocket URL | `frontend/src/lib/auth-session.ts:122-126`, `src/lib/chat-websocket.ts:112` | R02-10, R07-09 |
| H | Approved agent runs are marked `running` but nothing resumes them | `interfaces/http/agent_runs.py:834-841` | R06-13 |
| H | Backup gate tests for files where the docs configure directories | `deploy/scripts/check_remote_backups.sh:20-22` | R02-08 |
| M | Dev auth fallback variables are not rejected in production builds | `frontend/src/lib/auth-login.ts:129-144` | R02-11 |
| M | WebSocket rate limiter always fails open | `chat.py:6052-6060` | R02-12 |
| M | Prompt-injection guard covers the question only; auxiliary prompts lack the untrusted-context rule | `core/safety_guardrails.py:26`, `domains/chat/services/prompt_service.py:58-70` | R05-09 |

### 5.2 Performance and scalability

| Sev | Finding | Evidence | Item |
|---|---|---|---|
| C | Chat holds one DB session across all LLM calls; pool is the default 5 + 10 | `chat.py:2980-4903`, `:6201-7297`, `app/db/session.py:11-16` | R04-01, R05-02 |
| H | Answers are not token-streamed; one delta carries the whole answer | `chat.py:6886-6905` | R05-03 |
| H | Up to 9-12 sequential LLM calls per question, no overall latency budget | `chat.py:3355,3965,4411,4560`, `rerank_service.py:488` | R05-04 |
| H | No application cache; auth, permissions, flags, and profiles hit the DB per request | `app/auth/providers/app_provider.py:78-92`, `feature_flag_service.py:163` | R04-05 |
| H | N+1 queries: citations per message, counts per row | `chat.py:2891,5699`, `collections.py:252,1009`, `documents.py:855` | R04-03 |
| H | Missing indexes on hot foreign keys and org-scoped tables | `app/models/chat.py:15`, `organization_members.user_id` | R04-02 |
| H | No partitioning or retention for append-only tables | No `PARTITION BY` in `alembic/` | R04-09 |
| H | Sync boto3, Qdrant, and Celery calls inside async handlers | `profile.py:252`, `documents.py:1526`, `query_retrieval_service.py:209` | R04-11 |
| H | In-process WebSocket connection counts | `chat.py:6024-6025` | R08-03 |
| H | One worker pool consumes every queue; no time limits or recycling | `docker-compose.production.yml:65` | R06-03, R06-04 |
| H | Ingestion is one monolithic coroutine; a retry redoes OCR and embeddings | `document_tasks.py:608-2122` | R06-01 |
| H | No embedding model migration path; one fixed-size collection | `clients/qdrant_client.py:137-149` | R06-08 |
| H | Connector sync runs in one DB transaction | `workers/connector_sync_tasks.py:42-48` | R06-11 |
| H | Agent runs execute inside the API request | `agent_runs.py:401` | R06-13 |
| H | Chat page re-renders on every token; list not virtualized; 500 messages in one request | `frontend/src/lib/use-chat-websocket.ts:124`, `ChatPage.tsx:1340,3148` | R05-11 |
| H | Chat WebSocket has no reconnect | `use-chat-websocket.ts:193-208` | R05-13 |
| H | No static generation for marketing pages; no code splitting | `frontend/src/app/layout.tsx:38-39` | R07-01, R07-03 |
| H | Full 340-470 KB message catalogue sent to the client on every page | `frontend/src/i18n/messages.ts:6` | R07-02 |
| H | Generated API types cover 38 paths; 4 of 76 client modules use them | `frontend/openapi.json` | R07-05 |
| M | `ensure_qdrant_collection()` on every upsert and delete | `qdrant_service.py:111,190` | R06-07 |
| M | FTS hard-codes `'english'`; chunks carry no `organization_id` | `keyword_retrieval_service.py:98,111-121` | R06-09 |
| M | Neo4j writes one transaction per entity | `document_tasks.py:2528,2542` | R06-10 |
| M | Usage events omit rewrite, verifier, refiner, and conflict tokens (verify first) | `chat.py:4744-4750` | R05-07 |
| M | Polling: documents page every 4 s including background tabs | `DocumentsPage.tsx:537-566` | R07-07 |

### 5.3 Engineering and operations

| Sev | Finding | Evidence | Item |
|---|---|---|---|
| H | All backend tests run on SQLite; `requires_postgres` marker unused | `backend/tests/conftest.py:29-33` | R03-01 |
| H | Playwright, accuracy-eval, and quality-gate workflows are manual-only | `.github/workflows/playwright.yml:4` | R03-03 |
| H | No lockfile; images run as root; floating `latest` tags in production | `backend/Dockerfile:17,43` | R03-05, R03-06 |
| H | No git tags; production rebuilds images instead of promoting the tested digest | `.github/workflows/release.yml:484-487` | R03-07 |
| H | No backups, PITR, or restore drill | `DEPLOYMENT.md:432` | R08-06 |
| H | No reverse proxy or TLS; app ports published on the host | `docker-compose.production.yml:14,36,116` | R08-01 |
| H | Metrics stack absent from staging and production; alerts have no receiver | `infra/observability/alertmanager/alertmanager.yml:11-12` | R08-09 |
| H | `chat.py` is 8,085 lines with two copies of the pipeline; 67 backend and 28 frontend files exceed the size guideline | `chat.py:2960-5222`, `:6115-7534` | R05-01, R05-10 |
| M | No global exception handlers; 647 string `detail=` errors | `backend/app/main.py` | R04-10 |
| M | No secret, image, npm, or licence scanning; `pip-audit` only warns | `.github/workflows/security.yml:58-64` | R03-08 |

## 6. Already done well

Do not redo these:

- `acks_late`, `reject_on_worker_lost`, prefetch 1, jittered backoff, transient/permanent
  error taxonomy, `FailedJob` table.
- Qdrant tenant index on `organization_id`, mandatory org filter with post-filter re-check,
  deterministic UUID5 point IDs.
- Redis-backed rate limiting with configurable failure mode and standard 429 headers.
- `/api/v1` prefix, request-ID middleware, structured logging, Prometheus metrics endpoint.
- Batched authorization context builders; capped list limits almost everywhere.
- Frontend single-flight token refresh with cross-tab lease; query-key factory; cache clear on
  organisation switch.
- SEO fundamentals: canonical, hreflang, sitemap, robots, `llms.txt`, JSON-LD.
- i18n key parity across six locales enforced by a test.
- Pydantic startup validation with production-only checks.
- Alembic upgrade/downgrade round trip on Postgres in CI.

## 7. Change Notes

- 2026-11-26: Initial baseline.
