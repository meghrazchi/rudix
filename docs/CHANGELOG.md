# Changelog

All notable changes to this documentation set are recorded here.

## [Unreleased]

### Added

- Production retrieval filters on active index versions (`DOCUMENT_ACTIVE_INDEX_VERSIONS`), evaluation re-ingest cleans up its `eval-` chunks and vectors, and `scripts/purge_eval_index_versions.py` purges legacy ones; pre-deploy check in docs/12 (R02-05).
- Security headers: frontend `headers()` with report-only CSP, HSTS in staging/production, and `NEXT_PUBLIC_CSP_REPORT_URI`; backend `SecurityHeadersMiddleware` (R02-09).
- Frontend production-like builds (`NEXT_PUBLIC_DEPLOYMENT_ENV` staging/production) now fail when dev auth fallback variables are set (`NEXT_PUBLIC_AUTH_LOCAL_FALLBACK`, `NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK`, local passwords, default access/refresh tokens); an empty `NEXT_PUBLIC_DEPLOYMENT_ENV` no longer masks `NEXT_PUBLIC_ENVIRONMENT`; the existing `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_APP_URL` checks now also run on `next build` (the `NEXT_PHASE` guard alone never matched in Next 16) (R02-11).
- `docs/26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md` and `docs/roadmap/`: planned release train from `0.1.0` to `1.0.0`, the `0.1.0` feature catalogue and audit baseline, and one implementation spec per version.
- `docs/roadmap/V0_2_0_IMPLEMENTATION_PLAN.md`: file-level implementation plan for `0.2.0`, with corrections to the `0.2.0` spec found by checking it against the code.
- `backend/README.md` and `docs/14_GITHUB_ACTIONS_CI_CD_PIPELINE.md`: documented the PostgreSQL test lane (`TEST_DATABASE_URL`, `make test-postgres`, `requires_postgres`/`requires_redis` markers) run in the `backend-alembic` CI job (R02-15).
- `docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md` for planned Prometheus and Grafana metrics, exporters, dashboards, security guardrails, and phased rollout.
- `docs/DOCUMENT_TEMPLATE.md` for standardized technical documents.
- `docs/DOCUMENT_REVIEW_CHECKLIST.md` for document quality gating.
- Celery `beat` service in all compose files, `make run-beat`, and an integration-smoke beat check; documented in `backend/README.md`, `docs/10_DEPLOYMENT_DOCKER.md`, and `docs/17_CONNECTOR_OPERATIONS_RUNBOOK.md` (R02-03).
- Atomic document processing claim (`documents.processing_task_id`, `processing_started_at`, `processing_reap_count`; migration `20261126_0001`) and the beat-scheduled `documents.reap_stale` reaper, with `rudix_documents_reaped_total` (R02-02).
- Deployment fixes: Terraform `infra_services` variable (production no longer waits on `neo4j`), a backup freshness gate that accepts files or directories (`DEPLOY_BACKUP_MAX_AGE_HOURS`, default 26), Redis password and volumes, RabbitMQ volume with a fixed hostname, image tag variables (`QDRANT_IMAGE`, `MINIO_IMAGE`, `RABBITMQ_IMAGE`, `REDIS_IMAGE`, `CLAMAV_IMAGE`), a ClamAV service in staging/production compose, `deploy/scripts/check_deploy_env.sh`, and a staging/production validator that rejects loopback `MALWARE_SCAN_CLAMAV_HOST` while scanning is enabled (R02-08).

### Changed

- Concurrent keyword-search branches in parallel retrieval each use their own database session; swallowed branch failures are logged and counted in `rudix_retrieval_branch_failures_total` (R02-06).
- `documents.process` skips documents in deletion, retention, quarantine, or blocked statuses; a terminal task failure no longer overwrites those statuses (or `deleted`) with `failed`, and the DLP `warn` branch writes nothing to the document row during evaluation re-ingest (R02-02b).
- `docs/12_EVALUATION_AND_MONITORING.md` and `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md`: linked the planned Prometheus and Grafana observability architecture and metrics security checklist items.
- `docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md`, `README.md`, `docs/README.md`: aligned observability status (development overlay implemented; staging and production rollout planned); removed dead stub services and `RefreshTokenStore`, and marked the legacy `POST /documents/upload-url` and `POST /chat/sessions/{session_id}/messages` routes deprecated (R02-13, R02-14).
- `README.md`: aligned the GitHub Actions summary with the committed `.github/workflows/` files and documented the standalone Playwright workflow.
- `docs/14_GITHUB_ACTIONS_CI_CD_PIPELINE.md`: updated the CI/CD reference to match the current workflow split between `ci.yml` and `playwright.yml`.
- `docs/CONTRIBUTING.md`: clarified GitHub pull request language and added a workflow-documentation sync check.
- `backend/README.md`: documented the Celery task registration and routing rule enforced by `tests/test_celery_task_registry.py`; `safety_evals.run` is now registered and routed to the evaluations queue (R02-04).
- Quota usage counters are incremented with an atomic upsert and windows reset with a conditional update; documented in docs/07_API_DESIGN.md (R02-07).
- The `/chat/ws` WebSocket now enforces the plan question quota (`plan_limit_exceeded`), records question usage, and drops chunks the user may not cite, matching `POST /chat`; shared code lives in `backend/app/application/chat/`, refusals are counted in `rudix_chat_quota_denied_total`, and the chat UI shows a translated plan-limit message (R02-01).
- The `/chat/ws` rate limiter now uses the same limiter core as HTTP (`app/rate_limit/counter.py`) and honours `RATE_LIMIT_REDIS_FAILURE_MODE`: in `closed` mode a Redis outage returns `chat.error` `rate_limiter_unavailable`; `rudix_rate_limit_decisions_total` is now populated (R02-12).
- The chat UI now opens `/chat/ws` with a single-use ticket from the new `POST /chat/ws-ticket` (`?ticket=`) instead of the access token; non-browser clients can send an `Authorization` header; the legacy `?token=` handshake is deprecated behind `CHAT_WS_ALLOW_QUERY_TOKEN` (default `true` in 0.2.0, `false` in 0.5.0, removed in 1.0.0); uvicorn logs now mask `token`/`ticket`/`access_token` query values; attempts are counted in `rudix_chat_ws_auth_total` (R02-10).

## [2026-06-02] — F210 Adaptive hybrid chunking

### Added

- `docs/03_RAG_WORKFLOW.md`: replaced stale "Start with recursive chunking" section with a full strategy reference table, adaptive hybrid selection priority table, reason code description, and updated chunk metadata schema.
- `docs/08_SERVICE_IMPLEMENTATION_GUIDE.md`: replaced single-function chunking snippet with strategy registry reference, adaptive hybrid description, `CHUNKING_STRATEGY` env var, and updated production requirements.
- `backend/README.md`: documented `CHUNKING_STRATEGY` env var and adaptive selection behaviour in configuration notes and document processing notes.

### Changed

- Expanded `docs/DOCUMENTATION_STANDARDS.md` into a formal standard.
- Updated `docs/README.md` with standards and templates links.
- Updated `docs/CONTRIBUTING.md` to require template and checklist usage.
- Removed platform-specific frontend deployment guidance across architecture and deployment docs.
- Standardized deployment guidance to containerized/self-hosted frontend and backend infrastructure.

## [2026-05-07]

### Added

- `docs/README.md` documentation index.
- `docs/CONTRIBUTING.md` contribution workflow and checklist.
- `docs/CODE_OF_CONDUCT.md` collaboration behavior policy.
- `docs/SECURITY.md` security reporting and response process.
- `docs/DOCUMENTATION_STANDARDS.md` writing and structure standards.

### Changed

- Moved architecture docs from repository root to `docs/`.
- Updated root `README.md` document paths to `docs/...`.
