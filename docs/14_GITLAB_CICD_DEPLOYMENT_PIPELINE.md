# 14) GitLab CI/CD Deployment Pipeline

## Objective

This document describes the GitLab CI/CD release gate for Rudix:

- validate and test backend/frontend changes
- run security checks
- build and publish immutable container images
- run integration smoke tests
- deploy to staging automatically
- deploy to production with manual approval
- support manual rollback

Deployment execution is Terraform-driven. GitLab deploy jobs run `terraform init/apply` in `deploy/terraform`, which updates remote Compose files, runtime `.env`, image refs, migrations, and rollout checks.

## Pipeline Entry Points

Defined in root `.gitlab-ci.yml`:

- merge request pipelines
- branch pipelines
- tag pipelines
- duplicate push pipelines are skipped when an MR pipeline exists for the same branch

## Stage Order

1. `validate`
2. `test`
3. `build`
4. `security`
5. `integration`
6. `deploy_staging`
7. `deploy_production`
8. `rollback`

Non-deployment jobs are `interruptible: true`. Deployment jobs are serialized with GitLab `resource_group`.

## Quality Gates

### Backend (Python 3.12)

- Ruff format/lint
- mypy type checks
- pytest with JUnit + coverage artifacts
- Alembic migration validation against ephemeral PostgreSQL

### Frontend (Node 22 / Next.js)

- `npm ci`
- format check
- lint
- typecheck
- unit/component tests
- production build
- Playwright smoke/e2e (enabled in CI job)

## Security Gates

Pipeline includes GitLab templates for:

- SAST
- Dependency Scanning
- Secret Detection
- Container Scanning

`security:severity-gate` fails protected refs when dependency/container scan reports include `high` or `critical` vulnerabilities.

## Image Build and Publish

Built and pushed to GitLab Container Registry:

- `${CI_REGISTRY_IMAGE}/api:${CI_COMMIT_SHA}`
- `${CI_REGISTRY_IMAGE}/worker:${CI_COMMIT_SHA}`
- `${CI_REGISTRY_IMAGE}/frontend:${CI_COMMIT_SHA}`

Additional tags:

- default branch: `staging`, `latest`
- tag pipeline: `${CI_COMMIT_TAG}`

Image digests are exported as artifacts and used by deploy jobs.

## Integration Validation

`integration:stack-smoke` starts a full stack using `deploy/compose/docker-compose.integration.yml` and runs:

- migration job (`alembic upgrade head`)
- health/readiness checks
- protected endpoint auth-boundary check (`401`)
- upload/chat preflight checks
- worker process health check

## Environments

### Staging

- automatic on protected default branch
- deploys immutable image refs
- deploy orchestration is executed by Terraform
- runs migrations before service rollout
- records deployment metadata artifact

### Production

- manual approval required
- limited to protected default branch or protected tags
- requires `PRODUCTION_BACKUP_CHECK_OK` confirmation
- deploy orchestration is executed by Terraform
- runs migrations before service rollout
- records deployment metadata artifact

## Rollback

Manual `rollback:production` job redeploys previously known-good image refs via:

- `ROLLBACK_API_IMAGE`
- `ROLLBACK_WORKER_IMAGE`
- `ROLLBACK_FRONTEND_IMAGE`

Rollback limitation:

- irreversible database migrations cannot be automatically reversed by image rollback alone

## Required GitLab CI Variables

### Staging

- `STAGING_SSH_HOST`
- `STAGING_SSH_PORT` (optional, defaults to `22`)
- `STAGING_SSH_USER`
- `STAGING_SSH_PRIVATE_KEY` (masked/protected)
- `STAGING_APP_PATH`
- `STAGING_ENV_FILE` (masked/protected; full runtime `.env` content)
- `STAGING_ENV_URL`

### Production

- `PRODUCTION_SSH_HOST`
- `PRODUCTION_SSH_PORT` (optional, defaults to `22`)
- `PRODUCTION_SSH_USER`
- `PRODUCTION_SSH_PRIVATE_KEY` (masked/protected)
- `PRODUCTION_APP_PATH`
- `PRODUCTION_ENV_FILE` (masked/protected; full runtime `.env` content)
- `PRODUCTION_ENV_URL`
- `PRODUCTION_BACKUP_CHECK_OK` (set after backup/snapshot verification)
- `PRODUCTION_POSTGRES_BACKUP_PATH`
- `PRODUCTION_MINIO_BACKUP_PATH`
- `PRODUCTION_QDRANT_BACKUP_PATH`

### Optional Sentry Release Tagging

- `SENTRY_DSN`
- `SENTRY_AUTH_TOKEN` (masked/protected)
- `SENTRY_ORG`
- `SENTRY_PROJECT`

## Deployment Metadata Artifacts

Each deploy job stores metadata including:

- commit SHA
- image references
- migration revision
- deploy user
- pipeline URL
- environment URL

## Operational Notes

- Keep environment variables scoped to GitLab environments.
- Never commit runtime secrets.
- Use protected branches/tags for release deploys.
- Store backup runbook and recovery procedures outside CI logs.
- Treat Terraform state as sensitive. It may contain secrets and must be stored in a protected backend in production GitLab setups.
