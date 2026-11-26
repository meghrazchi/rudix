# 14) GitHub Actions CI/CD Pipeline

## Objective

This document describes the GitHub Actions automation used for Rudix:

- validate repository configuration and Terraform syntax
- run backend linting, tests, and migration validation
- run frontend formatting, linting, type checks, API client checks, and build validation
- run the standalone Playwright e2e suite on demand
- run filesystem and dependency vulnerability scans
- run CodeQL security analysis on Python and TypeScript code
- build and publish release images
- run integration smoke tests against the container stack
- deploy staging automatically from the default branch
- deploy production with GitHub Environment approval
- support manual rollback
- support manual quality gates and scheduled accuracy evaluations

The workflows are intentionally split by concern so feedback stays fast and failures are easier to triage.

## Workflows

### `ci.yml`

Triggered on push, pull request, and manual dispatch for repository paths that affect application or infrastructure behavior.

Jobs:

1. `validate`
   - validates `.env.example`
   - runs `terraform fmt -check -diff`
   - runs `terraform init -backend=false`
   - runs `terraform validate`
2. `backend`
   - installs backend dev dependencies
   - checks Ruff formatting and linting
   - runs backend pytest with coverage artifacts
3. `backend-alembic`
   - starts ephemeral PostgreSQL and Redis services
   - runs `alembic upgrade head`
   - runs a downgrade/upgrade round trip to catch migration regressions
   - job name `Backend Alembic validation`; the PostgreSQL test lane moved to
     `backend-postgres.yml` (R03-01)
4. `frontend`
   - runs `npm ci`
   - runs Prettier, ESLint, and TypeScript checks
   - verifies generated API types against the committed OpenAPI schema
   - runs the production frontend build

Playwright end-to-end validation lives in `playwright.yml` instead of `ci.yml`.

### `backend-postgres.yml`

Runs the backend PostgreSQL test lane as its own job, `backend-postgres` (check name
`Backend PostgreSQL tests`). It triggers on every push, pull request, and manual dispatch with
no `paths` filter, so the check always reports and can be required in branch protection.

- starts ephemeral `postgres:16` (database `rudix_test`) and `redis:7` services
- runs `make -C backend install`
- runs `make -C backend test-postgres` with `TEST_DATABASE_URL` set; the target and the
  `pg_migrated_url` fixture both apply `alembic upgrade head`, then pytest runs every
  `requires_postgres` / `requires_redis` test, including the PostgreSQL parameters of
  `both_dialects` suites
- uploads `artifacts/backend-postgres-junit.xml` as the `backend-postgres-junit` artifact

Making `Backend PostgreSQL tests` a required status check is a manual branch-protection
setting in GitHub; it is not stored in the repository.

### `playwright.yml`

Triggered on every pull request, on push to `main`, and by manual dispatch. There is no
workflow-level `paths` filter (see [Required status checks](#required-status-checks)); a
`changes` job (`Detect frontend changes`) compares the PR with its base and sets
`frontend=true` when anything under `frontend/` or the workflow itself changed. It is
always `true` on `main` and on dispatch.

Job `Frontend Playwright` (`needs: changes`, `if: needs.changes.outputs.frontend == 'true'`)
runs:

- Playwright browser installation
- the repository's standalone Playwright end-to-end suite
- Playwright report upload on completion

On a PR that does not touch the frontend, `Frontend Playwright` reports as skipped, which
satisfies a required check.

### `security.yml`

Runs:

- `pip-audit` against the backend virtual environment, publishing a report artifact and warning on findings
- Trivy filesystem scanning with a high/critical severity gate

### `codeql.yml`

Runs CodeQL analysis for:

- Python
- JavaScript / TypeScript

The workflow runs on pull requests, pushes, a weekly schedule, and manual dispatch.

### `release.yml`

Triggered on:

- pushes to `main`
- version tags matching `v*`
- manual dispatch

Jobs:

1. `build-images`
   - logs in to GHCR with repository secrets
   - builds and pushes the backend API and worker images
   - builds and pushes the frontend image
   - tags images with the commit SHA and release tags
2. `integration-smoke`
   - runs the integration compose stack
   - applies migrations
   - verifies health, readiness, auth boundaries, preflight behavior, and worker and beat liveness
3. `deploy-staging`
   - uses Terraform to roll out the staging compose deployment on the default branch
   - requires `STAGING_*` secrets plus GHCR credentials
4. `deploy-production`
   - uses Terraform to roll out the production compose deployment on tags or manual dispatch
   - requires `PRODUCTION_*` secrets, backup paths, and the explicit backup-check confirmation secret
5. `rollback-production`
   - restores previously known-good image refs with the compose rollback script

### `e2e-integration.yml`

Job `E2E against integration stack` (R03-04). It is a reusable workflow:

- `workflow_call` with required string inputs `api_image` and `worker_image`. It logs in to
  GHCR with `github.token` (`packages: read`) and tests those exact images. `release.yml` is
  meant to call it as job `e2e-integration` (`needs: build-images`) and list it in
  `deploy-staging.needs`. B2 adds that wiring.
- `workflow_dispatch` (no inputs) builds `docker build --target api` and `--target worker` from
  `backend/` as `rudix-local-*:e2e`, and falls back to an untargeted build if a target is missing.

Steps: write `.env.ci.integration` (the `integration-smoke` keys, with
`CORS_ORIGINS=http://127.0.0.1:3200` and a placeholder `OPENAI_API_KEY`), start
`docker-compose.integration.yml` plus the overlay `docker-compose.integration-stub.yml`, run
`migrate`, and bootstrap an admin with credentials generated per run and masked with
`::add-mask::`. Then set up Node 24, run `npm ci`, install Playwright Chromium, and run
`RUDIX_E2E_INTEGRATION=1 npm run test:e2e:integration`. The Playwright report and the compose
logs are uploaded as artifacts, and the stack is removed with `down -v`.

The overlay adds `llm-stub` (`ci/stubs/llm_stub.py`, standard library only, `python:3.12-slim`
pinned by digest), a deterministic OpenAI-compatible provider for chat completions, embeddings,
and rerank prompts. It points `api` and `worker` at `http://llm-stub:8080/v1`
(`LLM_DEFAULT_PROVIDER=local`, `EMBEDDING_DEFAULT_PROVIDER=local`, `LOCAL_LLM_BASE_URL`,
`LOCAL_EMBEDDING_BASE_URL`, `OPENAI_BASE_URL`) and sets `MALWARE_SCAN_ENABLED=false`, because
the stack has no ClamAV. No secrets are required. `backend/tests/test_llm_stub_contract.py`
checks that the stub's output passes the backend's prompt builder, answer parser, and citation
validation.

### `quality-gate.yml`

Runs `ci/scripts/quality_gate_runner.py`, the F149 gate, against a completed evaluation run
or safety run on a deployed Rudix API. Triggers:

- `workflow_dispatch` with `evaluation_run_id`, `safety_eval_run_id`, and `dry_run`;
- `workflow_call` with `evaluation_run_id` (default `latest`), `safety_eval_run_id`, and
  `dry_run` (default `false`). `release.yml` calls it before `deploy-staging` with
  `secrets: inherit`.

`EVALUATION_RUN_ID=latest` lists `GET {RUDIX_API_BASE_URL}/evaluations/runs?evaluation_set_id=
<ACCURACY_EVAL_SET_ID>&status=completed` and gates the newest completed run. The gate fails
when there is no completed run, or when the newest one finished more than
`QUALITY_GATE_MAX_RUN_AGE_HOURS` ago (default 36; override with the repository variable of
the same name). A stale run usually means the nightly `accuracy-eval.yml` did not run.

Missing secrets (`RUDIX_API_BASE_URL`, `RUDIX_API_TOKEN`, `QUALITY_GATE_ID`, plus
`ACCURACY_EVAL_SET_ID` for `latest`) fail the job. Setting the repository variable
`QUALITY_GATE_ALLOW_MISSING_CONFIG` to `true` turns that into a warning and skips the gate.
This is for bootstrap only (a fork, or a repository before staging exists); remove the
variable once the secrets are set, or the release gate stops gating.

### `accuracy-eval.yml`

Runs the accuracy evaluation runner against the deployed staging API. Scheduled nightly at
02:00 UTC (`cron: "0 2 * * *"`, nightly mode: scheduled runs have no inputs, so the mode
falls back to `nightly`), and by manual dispatch with smoke or nightly mode selection. The
release quality gate reads the newest completed run this workflow produces. It uses the
secrets in [Evaluation and quality gates](#evaluation-and-quality-gates).

### `accuracy-smoke.yml`

Deterministic accuracy smoke over pinned fixtures (R03-03). Runs on every pull request and on
push to `main`, with no workflow-level `paths` filter. A `changes` job sets `pipeline=true`
when the PR touches `backend/app/domains/{chat,ai,rag_profiles,prompt_templates,evaluations,
quality_gates}/`, `backend/app/application/chat/`, `backend/app/interfaces/http/chat.py`,
`backend/app/core/config.py`, `ci/config/accuracy_eval_thresholds.yml`,
`backend/tests/fixtures/accuracy_smoke/`, `backend/tests/test_accuracy_smoke.py`,
`backend/tests/accuracy_smoke_support.py`, or the workflow itself (always `true` on `main`).

Job `Accuracy smoke` runs `make -C backend install`, then
`cd backend && .venv/bin/pytest -m accuracy_smoke --junitxml=...`. The suite drives the real
in-process `POST /api/v1/chat` pipeline with feature-hashed embeddings, an in-memory Qdrant
fake that applies the organization and document filters, and a rule-based fake LLM, and
checks retrieval hit rate, citation accuracy, refusal accuracy, not-found rate, and
injection-not-followed against the `smoke` thresholds in
`ci/config/accuracy_eval_thresholds.yml` with the F149 `evaluate_gate` function. It tests
the pipeline, not model quality; the nightly live run covers the model. It needs no secrets
and no services.

### `openapi-contract.yml`

OpenAPI contract check (R03-10). Runs on every pull request and on push to `main`, with no
`paths` filter. Job `OpenAPI contract`:

1. `make -C backend install`;
2. `cd backend && .venv/bin/python scripts/export_openapi.py --check ../frontend/openapi.json`
   compares the committed schema with the app's schema as parsed JSON, so formatting never
   fails it, and prints the added, removed, and changed paths and component schemas;
3. `cd frontend && npm ci && npm run api:check` verifies that
   `src/lib/api/generated/schema.d.ts` matches `openapi.json`.

When it fails, run `cd frontend && npm run api:update-schema` and commit both files.

## CI Inputs

The workflows rely on the repository's committed defaults and do not require a separate legacy CI variable set.

## Required GitHub Secrets

### Shared

| Secret           | Expected content                                                                                      |
| ---------------- | ----------------------------------------------------------------------------------------------------- |
| `GHCR_USERNAME`  | GitHub user or organization account with package pull access.                                         |
| `GHCR_TOKEN`     | GitHub PAT with `read:packages` access for deploy hosts.                                              |
| `OPENAI_API_KEY` | Optional OpenAI API key used by integration smoke; the workflow falls back to a placeholder if unset. |

### Staging environment

| Secret                    | Expected content                                                                                                     |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `STAGING_SSH_HOST`        | Staging server hostname or IP address.                                                                               |
| `STAGING_SSH_PORT`        | Optional SSH port; defaults to `22` when unset.                                                                      |
| `STAGING_SSH_USER`        | Linux deploy user on the staging server.                                                                             |
| `STAGING_SSH_PRIVATE_KEY` | Full private key for the staging deploy user, including header and footer lines.                                     |
| `STAGING_APP_PATH`        | Absolute deploy directory on the staging server, for example `/opt/rudix/staging`.                                   |
| `STAGING_ENV_FILE`        | Full backend/server `.env` file content for staging. See [Staging environment file](#staging-environment-file).      |
| `STAGING_ENV_URL`         | `https://staging.getrudix.com`.                                                                                      |
| `FRONTEND_ENV_STAGING`    | Browser-safe frontend-only environment overrides. See [Frontend staging environment](#frontend-staging-environment). |

Staging uses `https://staging.getrudix.com` as the public frontend URL and
`https://api-staging.getrudix.com/api/v1` as the browser API base URL. The
release workflow writes those three deployment-owned values during frontend
image build:

```env
NEXT_PUBLIC_DEPLOYMENT_ENV=staging
NEXT_PUBLIC_API_URL=https://api-staging.getrudix.com/api/v1
NEXT_PUBLIC_APP_URL=https://staging.getrudix.com
```

Do not put those keys in `FRONTEND_ENV_STAGING`; the workflow strips them so
stale `localhost` values cannot be baked into the Next.js client bundle.

#### Frontend staging environment

`FRONTEND_ENV_STAGING` must contain only non-sensitive `NEXT_PUBLIC_*` values
that are safe to expose to browsers. Keep backend secrets, API keys, database
URLs, queue passwords, and service tokens out of this secret.

Recommended staging content:

```env
NEXT_PUBLIC_AUTH_PROVIDER=app
NEXT_PUBLIC_AUTH_LOGIN_URL=https://api-staging.getrudix.com/api/v1/auth/login
NEXT_PUBLIC_AUTH_REFRESH_URL=https://api-staging.getrudix.com/api/v1/auth/token/refresh
NEXT_PUBLIC_AUTH_LOGOUT_URL=https://api-staging.getrudix.com/api/v1/auth/logout
NEXT_PUBLIC_AUTH_LOCAL_FALLBACK=false
NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK=false
NEXT_PUBLIC_FEATURE_UNAVAILABLE_BACKEND_ENDPOINTS=false
NEXT_PUBLIC_DASHBOARD_ENABLE_ADMIN_USAGE=true
NEXT_PUBLIC_CHAT_FEEDBACK_ENABLED=true
NEXT_PUBLIC_FEATURE_COLLECTIONS_ENABLED=true
NEXT_PUBLIC_FEATURE_EXPORTS_ENABLED=true
NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED=true
```

Do not set `NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN` in deployed environments.
Anything under `NEXT_PUBLIC_*` is readable by every browser user.
Keep `NEXT_PUBLIC_AUTH_LOCAL_FALLBACK=false` so staging always calls the backend
login endpoint.

#### Staging environment file

`STAGING_ENV_FILE` is the server-side `.env` used by the API, worker, MCP, and
compose dependencies. It should include staging public URLs and backend secrets:

```env
ENVIRONMENT=staging
API_BASE_URL=https://api-staging.getrudix.com
FRONTEND_BASE_URL=https://staging.getrudix.com
CORS_ORIGINS=https://staging.getrudix.com

POSTGRES_DB=rag_app
POSTGRES_USER=<staging-db-user>
POSTGRES_PASSWORD=<staging-db-password>

OPENAI_API_KEY=<openai-api-key>

AUTH_PROVIDER=app
APP_AUTH_SECRET=<strong-random-secret>
APP_AUTH_ISSUER=rudix-app
APP_AUTH_AUDIENCE=rudix-api
APP_AUTH_AUTO_PROVISION_USERS=false

QDRANT_COLLECTION=documents
QDRANT_VECTOR_SIZE=1536
QDRANT_BOOTSTRAP_COLLECTION=true

MINIO_ROOT_USER=<minio-user>
MINIO_ROOT_PASSWORD=<minio-password>
MINIO_ACCESS_KEY=<minio-user>
MINIO_SECRET_KEY=<minio-password>
MINIO_BUCKET=documents
MINIO_BOOTSTRAP_BUCKET=true

RABBITMQ_DEFAULT_USER=admin
RABBITMQ_DEFAULT_PASS=<rabbitmq-password>
REDIS_URL=redis://redis:6379/0
```

### Production environment

| Secret                            | Expected content                                                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------------------- |
| `PRODUCTION_SSH_HOST`             | Production server hostname or IP address.                                                         |
| `PRODUCTION_SSH_PORT`             | Optional SSH port; defaults to `22` when unset.                                                   |
| `PRODUCTION_SSH_USER`             | Linux deploy user on the production server.                                                       |
| `PRODUCTION_SSH_PRIVATE_KEY`      | Full private key for the production deploy user, including header and footer lines.               |
| `PRODUCTION_APP_PATH`             | Absolute deploy directory on the production server, for example `/opt/rudix/production`.          |
| `PRODUCTION_ENV_FILE`             | Full backend/server `.env` file content for production.                                           |
| `PRODUCTION_ENV_URL`              | `https://getrudix.com`.                                                                           |
| `FRONTEND_ENV_PRODUCTION`         | Browser-safe frontend-only environment overrides for production.                                  |
| `PRODUCTION_POSTGRES_BACKUP_PATH` | Absolute path to production PostgreSQL backup artifacts.                                          |
| `PRODUCTION_MINIO_BACKUP_PATH`    | Absolute path to production MinIO backup artifacts.                                               |
| `PRODUCTION_QDRANT_BACKUP_PATH`   | Absolute path to production Qdrant backup artifacts.                                              |
| `PRODUCTION_BACKUP_CHECK_OK`      | `yes`, once backup jobs are active and at least one backup exists in each configured backup path. |

Production uses `https://getrudix.com` as the public frontend URL and
`https://api.getrudix.com/api/v1` as the browser API base URL. Keep
`PRODUCTION_ENV_URL` aligned with `https://getrudix.com`.

`FRONTEND_ENV_PRODUCTION` follows the same rules as
`FRONTEND_ENV_STAGING`: only browser-safe `NEXT_PUBLIC_*` values, no backend
secrets, no service tokens, and no `NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN`.
The release workflow writes these production values during frontend image
build, so do not include them in `FRONTEND_ENV_PRODUCTION`:

```env
NEXT_PUBLIC_DEPLOYMENT_ENV=production
NEXT_PUBLIC_API_URL=https://api.getrudix.com/api/v1
NEXT_PUBLIC_APP_URL=https://getrudix.com
```

### Evaluation and quality gates

| Secret                 | Expected content                                                                      |
| ---------------------- | ------------------------------------------------------------------------------------- |
| `RUDIX_API_BASE_URL`   | API base URL including prefix, for example `https://api-staging.getrudix.com/api/v1`. |
| `RUDIX_API_TOKEN`      | Bearer token value only, without the `Bearer ` prefix.                                |
| `QUALITY_GATE_ID`      | UUID of the quality gate configuration.                                               |
| `ACCURACY_EVAL_SET_ID` | UUID of the published evaluation set.                                                 |

### Optional Sentry release tagging

- `SENTRY_DSN`
- `SENTRY_AUTH_TOKEN`
- `SENTRY_ORG`
- `SENTRY_PROJECT`

For production or external deployment automation, use environment-scoped GitHub secrets and the dedicated release workflow instead of duplicating logic in ad hoc jobs.

## Required status checks

Branch protection on `main` should require these checks (job names). This is configured
manually in the GitHub repository settings, not in the repository:

- `Validate config`
- `Backend lint and tests`
- `Backend Alembic validation`
- `Backend PostgreSQL tests`
- `Frontend quality checks`
- `Frontend Playwright`
- `Accuracy smoke`
- `OpenAPI contract`
- `Backend dependency audit`
- `Frontend dependency audit`
- `Filesystem vulnerability scan`
- `Secret scan`
- `Image scan`

A required check from a workflow that a workflow-level `paths` filter skipped stays pending
and blocks the merge. So the workflows behind required checks have no `paths` filter: either
the job always runs, or a `changes` job decides and the job is skipped by a job-level `if:`,
which counts as satisfied. `ci.yml` lost its `paths` lists for this reason, so docs-only pull
requests now run the full CI workflow too; that costs runner minutes on every PR in exchange
for checks that always report.

## Notes

- The legacy CI pipeline has been removed from the repository.
- The release workflow expects GitHub Environments for `staging` and `production` plus GHCR and deployment secrets.
- Production deployment should be protected with required reviewers and tight secret scoping in GitHub Environments.
