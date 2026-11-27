# Changelog

All notable changes to Rudix, the product and its documentation, are recorded here.

## [Unreleased]

### Added

- `docs/roadmap/V0_5_0_IMPLEMENTATION_PLAN.md`: nine work packages for `0.5.0` (chat pipeline and streaming) in four chains, with shared-file anchors, the streaming and resume event contracts, and what is deferred or needs staging.
- `docs/roadmap/01_EXECUTION_PLAN.md`: how the roadmap from `0.4.0` to `1.0.0` is executed, with roles, the branch-per-package process, current status, and blockers per version.
- Production retrieval filters on active index versions (`DOCUMENT_ACTIVE_INDEX_VERSIONS`), evaluation re-ingest cleans up its `eval-` chunks and vectors, and `scripts/purge_eval_index_versions.py` purges legacy ones; pre-deploy check in docs/12 (R02-05).
- Integration e2e: deterministic OpenAI-compatible stub `ci/stubs/llm_stub.py` (contract test `tests/test_llm_stub_contract.py`), overlay `deploy/compose/docker-compose.integration-stub.yml` (`llm-stub`, `MALWARE_SCAN_ENABLED=false`), Playwright critical path `frontend/e2e-integration/critical-path.spec.ts` (`npm run test:e2e:integration`, skipped unless `RUDIX_E2E_INTEGRATION=1`), and reusable workflow `.github/workflows/e2e-integration.yml` (R03-04).
- Security headers: frontend `headers()` with report-only CSP, HSTS in staging/production, and `NEXT_PUBLIC_CSP_REPORT_URI`; backend `SecurityHeadersMiddleware` (R02-09).
- Hardened images: digest-pinned bases, `api` and `worker` backend targets (OCR packages only in `worker`), non-root users (uid 10001, `node`), `HEALTHCHECK` in every image, standalone Next.js runtime (`node server.js`), and staging/production compose resource limits, `stop_grace_period`, log rotation, and worker/frontend healthchecks; documented in `docs/10_DEPLOYMENT_DOCKER.md` and docs/11 (R03-06).
- Frontend production-like builds (`NEXT_PUBLIC_DEPLOYMENT_ENV` staging/production) now fail when dev auth fallback variables are set (`NEXT_PUBLIC_AUTH_LOCAL_FALLBACK`, `NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK`, local passwords, default access/refresh tokens); an empty `NEXT_PUBLIC_DEPLOYMENT_ENV` no longer masks `NEXT_PUBLIC_ENVIRONMENT`; the existing `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_APP_URL` checks now also run on `next build` (the `NEXT_PHASE` guard alone never matched in Next 16) (R02-11).
- Frontend upgraded to the latest Next.js 16 patch (16.4.6) with in-range `npm audit fix`; the CSP now allows the contact submit origin and known captcha providers (`turnstile`, `hcaptcha`, `recaptcha`), adds `frame-src`, and can be enforced with `NEXT_PUBLIC_CSP_ENFORCE`; scope-inventory answers now obey the `cite` permission on both chat transports (R03-08).
- `docs/26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md` and `docs/roadmap/`: planned release train from `0.1.0` to `1.0.0`, the `0.1.0` feature catalogue and audit baseline, and one implementation spec per version.
- `docs/roadmap/V0_2_0_IMPLEMENTATION_PLAN.md`: file-level implementation plan for `0.2.0`, with corrections to the `0.2.0` spec found by checking it against the code.
- `docs/roadmap/V0_3_0_IMPLEMENTATION_PLAN.md`: file-level implementation plan for `0.3.0`, with spec corrections, shared-file owners and anchors, and cross-task contracts.
- `docs/roadmap/V0_4_0_IMPLEMENTATION_PLAN.md`: file-level implementation plan for `0.4.0`, with spec corrections, one linear migration chain, shared-file owners and anchors, cross-chain contracts, and deferred items.
- Retention and partitioning (R04-09): per-table `RETENTION_<TABLE>_DAYS` windows (all default to keep) for usage events, audit logs, authorization decision logs, activity timeline events, and webhook deliveries, purged daily per organisation in batches by `maintenance.retention.purge`; organisation audit retention override in `PATCH /admin/governance` (Alembic `20261127_0005`, floor 30 days); `maintenance.partitions.ensure`, `rudix_partition_missing`, and the operator tool `scripts/partition_table.py`. Converting existing tables is documented and deferred.
- No blocking calls on the event loop and no persistence in the documents/admin/evaluations routers: object storage and Celery dispatch on request paths run in threads (`app/clients/object_storage.py`, `app/workers/dispatch.py`), document downloads stream, retrieval offloads the sync Qdrant call, responses over `HTTP_GZIP_MINIMUM_BYTES` (1024; `0` disables) are gzip-encoded, and `rudix_event_loop_lag_seconds` measures loop lag (`LOOP_LAG_MONITOR_ENABLED`); the outbox and `AsyncQdrantClient` are deferred (R04-11, R04-13).
- Application cache (R04-05): `app/core/cache.py` caches the auth principal snapshot, custom-role permission sets, and feature-flag overrides in Redis under org- and user-versioned keys, invalidated in `after_commit` before `commit()` returns (`CACHE_ENABLED` kill switch, `CACHE_TTL_*`, `CACHE_OPERATION_TIMEOUT_MS`); a warm authenticated request issues no auth statements; admin feature-flag set/clear now commit the override.
- Database: configurable pool (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`), server timeouts, PgBouncer mode, `DATABASE_MIGRATION_URL`/`DATABASE_MAINTENANCE_URL`, pool wait and timeout metrics, engine disposal on shutdown, and connection release before three slow admin probes (R04-01); mode-aware PostgreSQL row-level security on every `organization_id` table except the user-scoped `users`, `organization_members`, and `auth_refresh_sessions` (Alembic `20261127_0004`, `RLS_ENFORCEMENT` off/soft/strict, soft by default in staging and production, never strict by default), per-transaction tenant context, soft-denial metric and alert, and `deploy/sql/provision_roles.sql` (R04-08).
- Constant-query list endpoints and keyset pagination: grouped counts and one-query citation loads replace per-row queries (messages, shared sessions, documents, collections, connections, evaluation sets, `ensure_document_ids_access`), answer citations insert in one statement; optional `cursor`/`include_total` and `next_cursor` on chat sessions, messages, documents, notifications, audit logs, and webhook deliveries (`total` is now nullable); usage and audit exports stream with the limit in SQL; documented in `docs/07_API_DESIGN.md` `## Pagination` (R04-03, R04-04).
- Rate limiting and credential usage (R04-07, R04-06): every limiter uses one atomic Lua sliding-window check (one Redis round trip) with an organisation aggregate limit (`RATE_LIMIT_ORG_ENABLED`, `RATE_LIMIT_ORG_LIMIT_MULTIPLIER`, `X-RateLimit-Scope`); API-key and service-account `last_used_*` are buffered in Redis and written by the `usage.touch.flush` beat task (`USAGE_TOUCH_FLUSH_INTERVAL_SECONDS`) instead of on every request.
- `docs/07_API_DESIGN.md`, `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md`, `backend/README.md`, `frontend/README.md`: uniform API error envelope (`error.code`/`message`/`request_id`/`details`, legacy `detail` alias kept until 1.0.0), optional dependencies (Redis, RabbitMQ, Qdrant) no longer abort API startup, `GRAPH_MIGRATIONS_ON_STARTUP` plus `make migrate-graph` for Neo4j migrations in the deploy migrate step, and the `app/core/settings/` package split (R04-10, R04-12).
- Database: hot-path and foreign-key indexes built concurrently by Alembic revisions `20261127_0001`..`20261127_0003` (document and session list sorts, citations, webhook deliveries, memberships, usage and audit logs), a foreign-key index guard test with an exemption list that may only shrink, and a PostgreSQL query-plan test for ten hot queries (R04-02).
- `backend/README.md` and `docs/14_GITHUB_ACTIONS_CI_CD_PIPELINE.md`: documented the PostgreSQL test lane (`TEST_DATABASE_URL`, `make test-postgres`, `requires_postgres`/`requires_redis` markers) run in the `backend-alembic` CI job (R02-15).
- `backend/README.md` and `docs/14_GITHUB_ACTIONS_CI_CD_PIPELINE.md`: the PostgreSQL test lane now runs in its own always-reporting workflow `backend-postgres.yml` (check `Backend PostgreSQL tests`); the `pg_migrated_url` fixture applies `alembic upgrade head` itself; the `both_dialects` marker runs `db_session` suites on SQLite and PostgreSQL, with seven isolation/quota/claim suites ported and a new PostgreSQL full-text search test; `backend-alembic` keeps only the migration round trip (R03-01).
- `docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md` for planned Prometheus and Grafana metrics, exporters, dashboards, security guardrails, and phased rollout.
- `docs/DOCUMENT_TEMPLATE.md` for standardized technical documents.
- Faster, measured test suite: `db_session` copies a session-wide SQLite schema template instead of running `create_all` per test (`make test` about three times faster: 240 s down to 75 s when re-measured at review); the API router is mounted once under `/api/v1` in every environment, including tests; backend `fail_under` and Vitest `coverage.thresholds` ratchets enforced in `ci.yml`, plus `make test-cov` and `npm run test:coverage` (R03-02).
- `docs/DOCUMENT_REVIEW_CHECKLIST.md` for document quality gating.
- CI gates that gate (R03-03) and OpenAPI contract (R03-10): `playwright.yml` runs on PRs and `main` behind a `changes` job; new `accuracy-smoke.yml` (deterministic in-process pipeline smoke, `pytest -m accuracy_smoke`); `accuracy-eval.yml` runs nightly; `quality-gate.yml` is reusable and gates the latest completed nightly run (`EVALUATION_RUN_ID=latest`, `QUALITY_GATE_MAX_RUN_AGE_HOURS`) before `deploy-staging`; `ci.yml` has no `paths` filters; new `openapi-contract.yml` with `export_openapi.py --check`; `frontend/openapi.json` is now the full export. Documented in `docs/14` (including required status checks), `docs/12`, `DEPLOYMENT.md`, and both READMEs.
- Celery `beat` service in all compose files, `make run-beat`, and an integration-smoke beat check; documented in `backend/README.md`, `docs/10_DEPLOYMENT_DOCKER.md`, and `docs/17_CONNECTOR_OPERATIONS_RUNBOOK.md` (R02-03).
- Load-test harness in `ci/load/` (Locust, dev-only `load` extra), `rudix_db_queries_per_request` and `rudix_db_pool_*` metrics (`METRICS_DB_QUERY_COUNTING_ENABLED`), and the "not yet measured" baseline template `docs/roadmap/V0_3_0_LOAD_BASELINE.md`; documented in `docs/12_EVALUATION_AND_MONITORING.md` (R03-09).
- Atomic document processing claim (`documents.processing_task_id`, `processing_started_at`, `processing_reap_count`; migration `20261126_0001`) and the beat-scheduled `documents.reap_stale` reaper, with `rudix_documents_reaped_total` (R02-02).
- Hash-pinned Python lockfile (`backend/uv.lock`, uv) used by `make install`, `make audit`, and the Docker image build (R03-05).
- Deployment fixes: Terraform `infra_services` variable (production no longer waits on `neo4j`), a backup freshness gate that accepts files or directories (`DEPLOY_BACKUP_MAX_AGE_HOURS`, default 26), Redis password and volumes, RabbitMQ volume with a fixed hostname, image tag variables (`QDRANT_IMAGE`, `MINIO_IMAGE`, `RABBITMQ_IMAGE`, `REDIS_IMAGE`, `CLAMAV_IMAGE`), a ClamAV service in staging/production compose, `deploy/scripts/check_deploy_env.sh`, and a staging/production validator that rejects loopback `MALWARE_SCAN_CLAMAV_HOST` while scanning is enabled (R02-08).
- Release integrity and security pipeline (R03-07, R03-08): `release.yml` builds `api`/`worker`/frontend images once on `main` with SBOM, provenance, and cosign keyless signatures, scans the pushed digests, runs `e2e-integration`, tags `staging-passed-<sha>` after staging, and on a `vX.Y.Z` tag promotes those digests to production (`verify-staged`, `cosign verify`, digest equality) and creates the GitHub Release; `scripts/bump_version.py` (`--check`, `--changelog`) and `scripts/extract_release_notes.py`; `deploy/scripts/rollback.sh <environment> <version>`; pinned SSH host keys (`*_SSH_KNOWN_HOSTS`, `ssh_common.sh`, Terraform `host_key`) and S3 remote Terraform state; new `secret-scan.yml` (gitleaks), `image-scan.yml` (Trivy), and `.github/dependabot.yml`; blocking pip-audit and `npm audit --omit=dev` through `security_severity_gate.py` (`--trivy`/`--pip-audit`, allowlist entries need `reason` and `expires`).

### Changed

- Backend `cryptography` range raised to `>=50.0.0,<51.0.0` (locked 50.0.2) to clear PYSEC-2026-3552; `virtualenv` (dev-only) stays at 21.14.5 because its fixed releases need `packaging>=26.3` while `langfuse<3` caps `packaging<25`, so `make audit` still reports it (DEPS).
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
