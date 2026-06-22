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

- `GHCR_USERNAME`
- `GHCR_TOKEN`
- `OPENAI_API_KEY` (optional, used by integration smoke; falls back to a placeholder if unset)

### Staging environment

- `STAGING_SSH_HOST`
- `STAGING_SSH_PORT` (optional, defaults to `22`)
- `STAGING_SSH_USER`
- `STAGING_SSH_PRIVATE_KEY`
- `STAGING_APP_PATH`
- `STAGING_ENV_FILE`
- `STAGING_ENV_URL`

### Production environment

- `PRODUCTION_SSH_HOST`
- `PRODUCTION_SSH_PORT` (optional, defaults to `22`)
- `PRODUCTION_SSH_USER`
- `PRODUCTION_SSH_PRIVATE_KEY`
- `PRODUCTION_APP_PATH`
- `PRODUCTION_ENV_FILE`
- `PRODUCTION_ENV_URL`
- `PRODUCTION_POSTGRES_BACKUP_PATH`
- `PRODUCTION_MINIO_BACKUP_PATH`
- `PRODUCTION_QDRANT_BACKUP_PATH`
- `PRODUCTION_BACKUP_CHECK_OK`

### Evaluation and quality gates

- `RUDIX_API_BASE_URL`
- `RUDIX_API_TOKEN`
- `QUALITY_GATE_ID`
- `ACCURACY_EVAL_SET_ID`

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
