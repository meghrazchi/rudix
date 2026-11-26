# Changelog

All notable changes to this documentation set are recorded here.

## [Unreleased]

### Added

- `docs/26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md` and `docs/roadmap/`: planned release train from `0.1.0` to `1.0.0`, the `0.1.0` feature catalogue and audit baseline, and one implementation spec per version.
- `docs/roadmap/V0_2_0_IMPLEMENTATION_PLAN.md`: file-level implementation plan for `0.2.0`, with corrections to the `0.2.0` spec found by checking it against the code.
- `backend/README.md` and `docs/14_GITHUB_ACTIONS_CI_CD_PIPELINE.md`: documented the PostgreSQL test lane (`TEST_DATABASE_URL`, `make test-postgres`, `requires_postgres`/`requires_redis` markers) run in the `backend-alembic` CI job (R02-15).
- `docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md` for planned Prometheus and Grafana metrics, exporters, dashboards, security guardrails, and phased rollout.
- `docs/DOCUMENT_TEMPLATE.md` for standardized technical documents.
- `docs/DOCUMENT_REVIEW_CHECKLIST.md` for document quality gating.
- Celery `beat` service in all compose files, `make run-beat`, and an integration-smoke beat check; documented in `backend/README.md`, `docs/10_DEPLOYMENT_DOCKER.md`, and `docs/17_CONNECTOR_OPERATIONS_RUNBOOK.md` (R02-03).

### Changed

- `docs/12_EVALUATION_AND_MONITORING.md` and `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md`: linked the planned Prometheus and Grafana observability architecture and metrics security checklist items.
- `docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md`, `README.md`, `docs/README.md`: aligned observability status (development overlay implemented; staging and production rollout planned); removed dead stub services and `RefreshTokenStore`, and marked the legacy `POST /documents/upload-url` and `POST /chat/sessions/{session_id}/messages` routes deprecated (R02-13, R02-14).
- `README.md`: aligned the GitHub Actions summary with the committed `.github/workflows/` files and documented the standalone Playwright workflow.
- `docs/14_GITHUB_ACTIONS_CI_CD_PIPELINE.md`: updated the CI/CD reference to match the current workflow split between `ci.yml` and `playwright.yml`.
- `docs/CONTRIBUTING.md`: clarified GitHub pull request language and added a workflow-documentation sync check.
- `backend/README.md`: documented the Celery task registration and routing rule enforced by `tests/test_celery_task_registry.py`; `safety_evals.run` is now registered and routed to the evaluations queue (R02-04).

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
