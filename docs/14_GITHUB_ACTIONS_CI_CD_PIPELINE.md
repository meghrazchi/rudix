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
   - starts an ephemeral PostgreSQL service
   - runs `alembic upgrade head`
   - runs a downgrade/upgrade round trip to catch migration regressions
4. `frontend`
   - runs `npm ci`
   - runs Prettier, ESLint, and TypeScript checks
   - verifies generated API types against the committed OpenAPI schema
   - runs the production frontend build

Playwright end-to-end validation lives in `playwright.yml` instead of `ci.yml`.

### `playwright.yml`

Runs:

- Playwright browser installation
- the repository's standalone Playwright end-to-end suite
- Playwright report upload on completion

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
   - verifies health, readiness, auth boundaries, preflight behavior, and worker liveness
3. `deploy-staging`
   - uses Terraform to roll out the staging compose deployment on the default branch
   - requires `STAGING_*` secrets plus GHCR credentials
4. `deploy-production`
   - uses Terraform to roll out the production compose deployment on tags or manual dispatch
   - requires `PRODUCTION_*` secrets, backup paths, and the explicit backup-check confirmation secret
5. `rollback-production`
   - restores previously known-good image refs with the compose rollback script

### `quality-gate.yml`

Manual dispatch workflow that runs the evaluation quality gate script against a completed evaluation run or safety run.

### `accuracy-eval.yml`

Nightly scheduled workflow that runs the accuracy evaluation runner. It also supports manual dispatch with smoke or nightly mode selection.

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

## Notes

- The legacy CI pipeline has been removed from the repository.
- The release workflow expects GitHub Environments for `staging` and `production` plus GHCR and deployment secrets.
- Production deployment should be protected with required reviewers and tight secret scoping in GitHub Environments.
