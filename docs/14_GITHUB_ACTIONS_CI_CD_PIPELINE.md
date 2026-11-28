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

### Triggers

Check workflows run on two events: a pull request, and a push to `main` or `develop`. A merge
is a push to the target branch, so merging into `main` or `develop` runs them, and so does a
direct push to `develop`. A push to any other branch runs nothing until a pull request is
opened for it. `codeql.yml` follows the same rule and keeps its `paths` filter.

`release.yml` is the exception: it runs on push to `main` and on `v*` tags only. A push to
`develop` never builds release images or deploys.

### `ci.yml`

Triggered on push to `main` and `develop`, every pull request, and manual dispatch. There is
no `paths` filter (see
[Required status checks](#required-status-checks)).

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
   - prints backend coverage (`--cov-report=term`) and fails below
     `[tool.coverage.report] fail_under` in `backend/pyproject.toml` (R03-02 ratchet)
3. `backend-alembic`
   - starts ephemeral PostgreSQL and Redis services
   - runs `alembic upgrade head`
   - runs a downgrade/upgrade round trip to catch migration regressions
   - job name `Backend Alembic validation`; the PostgreSQL test lane moved to
     `backend-postgres.yml` (R03-01)
4. `frontend`
   - runs `npm ci`
   - runs Prettier, ESLint, and TypeScript checks
   - runs Vitest with coverage (`npm run test:coverage`), prints the summary, and fails below
     `coverage.thresholds` in `frontend/vitest.config.ts` (R03-02 ratchet)
   - verifies generated API types against the committed OpenAPI schema
   - runs the production frontend build

The `deploy-config` job (name `Deploy config`, added in `0.8.0`) checks deployment files
without deploying anything: "Set up Helm" installs Helm `v3.19.0` (`azure/setup-helm@v4`),
"Lint and render Helm chart" runs `deploy/scripts/check_helm_chart.sh` (`helm lint --strict`
and `helm template` of `deploy/helm/rudix` with the defaults, `values-staging.yaml`,
`values-production.yaml`, and every `ci/*-values.yaml`) and writes the manifests to
`$RUNNER_TEMP/helm`, "Validate rendered manifests" runs `kubeconform` `v0.6.7` (strict,
Kubernetes `1.30.0` schemas, unknown kinds such as CRDs skipped) on them, and "Check compose
files" runs `deploy/scripts/check_compose_config.sh` (`docker compose config` of every Compose
file with placeholder env). The `backend` job also installs Helm before "Run backend tests" so
the chart tests (`tests/test_helm_chart_*.py`) run instead of skipping. `kubeconform` and this
job are first exercised in CI; they were not run on a development machine when the job was
added, so add `Deploy config` to the required checks only after it has passed on `develop`.

Edge and parity checks in `deploy-config` (`0.8.0`, `R08-01`, `R08-12`): "Check compose files"
also checks staging and production with `--profile graph --profile analytics --profile pooler
--profile redis-split --profile mcp`, and fails when any service other than `edge` publishes a
host port or `edge` publishes one other than 80 or 443 (`docker compose config --format json`).
"Validate Caddyfile" (after "Check compose files") runs `caddy validate` from the pinned
`caddy:2.10` image on `deploy/compose/edge/Caddyfile` for every combination of
`EDGE_TLS_MODE` (`acme`, `files` with a throwaway self-signed certificate), `EDGE_NOINDEX`
(`true`, `false`), and `EDGE_MATOMO` (`off`, `on`). It is first exercised in CI; Caddy is not
installed on development machines, where `backend/tests/test_edge_proxy_config.py` checks the
Caddyfile text instead.

Release deploys (`0.8.0`): both Terraform steps set the new variable `TF_VAR_compose_profiles`
(staging `graph`, production `analytics`, which keeps Neo4j on staging and Matomo on
production running now that both sit behind profiles). Terraform writes it to the host `.env`
as `COMPOSE_PROFILES=` when not empty and uploads `deploy/compose/edge/` (the Caddyfile and
its snippets, each hashed into the rollout triggers) next to the compose file. The edge image
is pinned like the data stores: the production env file must set `CADDY_IMAGE` (and
`PGBOUNCER_IMAGE` when `COMPOSE_PROFILES` includes `pooler`) to an exact tag or digest, or
`deploy/scripts/check_deploy_env.sh` fails the production deploy unless
`DEPLOY_ALLOW_UNPINNED_IMAGES=true`; staging only warns. Add `CADDY_IMAGE` to
`PRODUCTION_ENV_FILE` before the first `0.8.0` production deploy.

Coverage thresholds are ratchets: raise them when coverage rises and never lower them without
a reason in the pull request.

Playwright end-to-end validation lives in `playwright.yml` instead of `ci.yml`.

### `backend-postgres.yml`

Runs the backend PostgreSQL test lane as its own job, `backend-postgres` (check name
`Backend PostgreSQL tests`). It triggers on push to `main` and `develop`, every pull request, and manual
dispatch with no `paths` filter, so the check always reports and can be required in branch protection.

- starts ephemeral `postgres:16` (database `rudix_test`) and `redis:7` services
- runs `make -C backend install`
- runs `make -C backend test-postgres` with `TEST_DATABASE_URL` and `TEST_REDIS_URL` set
  (the latter opts in `tests/test_rate_limit_redis_live.py`, which runs the production Lua
  scripts on the `redis:7` service); the target and the
  `pg_migrated_url` fixture both apply `alembic upgrade head`, then pytest runs every
  `requires_postgres` / `requires_redis` test, including the PostgreSQL parameters of
  `both_dialects` suites
- uploads `artifacts/backend-postgres-junit.xml` as the `backend-postgres-junit` artifact

Making `Backend PostgreSQL tests` a required status check is a manual branch-protection
setting in GitHub; it is not stored in the repository.

### `playwright.yml`

Triggered on every pull request, on push to `main` and `develop`, and by manual dispatch. There is no
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

Runs on push to `main` and `develop`, every pull request, a weekly schedule, and manual
dispatch, with no `paths` filter (its jobs are required checks). Jobs:

- `Backend dependency audit`: `make -C backend install`, then
  `make -C backend audit-report AUDIT_OUTPUT=$GITHUB_WORKSPACE/artifacts/pip-audit.json`
  (pip-audit over the exported `uv.lock` set, `--disable-pip`; uv virtualenvs have no `pip`).
  The JSON report is uploaded, then `ci/scripts/security_severity_gate.py --pip-audit` blocks.
  pip-audit reports carry no severity, so every finding counts as high unless it has an
  unexpired allowlist entry.
- `Frontend dependency audit`: `npm ci`, a full `npm audit --json` uploaded as an artifact
  (non-blocking), then a blocking `npm audit --omit=dev --audit-level=high`. Dev-only tooling
  advisories are visible in the artifact but do not block; anything in the runtime image does.
- `Filesystem vulnerability scan`: Trivy `fs` scan, HIGH/CRITICAL, `ignore-unfixed`, exit 1.

The severity gate (`ci/scripts/security_severity_gate.py`) takes `--trivy PATH` (repeatable;
`Results[].Vulnerabilities[]`) and `--pip-audit PATH` (`dependencies[].vulns[]`). It exits 0 on
pass, 1 when actionable critical/high findings exceed `SECURITY_GATE_MAX_CRITICAL` /
`SECURITY_GATE_MAX_HIGH` (default 0; `SECURITY_GATE_FAIL_ON_CRITICAL` / `_HIGH` switch the
checks), and 2 on a missing or malformed report or allowlist. Allowlist entries in
`ci/security/security_gate_allowlist.json` need `id` (matched against the finding id and its
aliases), `reason`, and `expires` (ISO date); optional `scanner` (`trivy` or `pip-audit`),
`package`, and `severity` narrow the match. Expired entries stop matching and are printed.

### `codeql.yml`

Runs CodeQL analysis for:

- Python
- JavaScript / TypeScript

The workflow runs on pull requests, pushes, a weekly schedule, and manual dispatch.

### `secret-scan.yml`

Job `Secret scan` (R03-08). Runs on push to `main` and `develop`, every pull request, a
weekly schedule, and manual dispatch, with no `paths` filter. It downloads the gitleaks CLI release tarball at the pinned
`GITLEAKS_VERSION` and checks it against `GITLEAKS_SHA256` (from that release's
`checksums.txt`) before running it. Range:

- pull request: `gitleaks git --log-opts="<base>..<head>"`;
- push: the pushed range `<before>..<after>`; for a new branch or a force push whose `before`
  commit is gone, `origin/<default>..<after>`;
- schedule and dispatch: full history (`--all`), report only (exit code 0).

The report is written with `--redact` and uploaded as `gitleaks-report`. `.gitleaks.toml`
extends the default rules and allowlists only exact placeholder values (`ci-placeholder-key`,
`sk-test`, `minioadmin`, `ci-local-secret`, `dev-insecure-change-me`, and the Playwright e2e
tokens); it never allowlists paths. To bump gitleaks, update both env values together.

### `image-scan.yml`

Job `Image scan` (R03-08). Runs on pull requests, push to `main` and `develop`, and dispatch. A `changes`
job sets `images=true` when `backend/Dockerfile`, `frontend/Dockerfile`, `backend/uv.lock`,
`backend/pyproject.toml`, `frontend/package-lock.json`, a compose file, the gate or its
allowlist, or the workflow changed; otherwise `Image scan` is skipped, which satisfies a
required check. The job builds `--target api` and `--target worker` from `backend/Dockerfile`
and the frontend image locally (`rudix-local-*:scan`, nothing pushed), scans each with
`aquasecurity/trivy-action` (HIGH/CRITICAL, `ignore-unfixed`, JSON), uploads the reports, and
runs the severity gate with three `--trivy` reports. `release.yml` job `scan-images` scans the
pushed digests the same way.

### Dependabot

`.github/dependabot.yml` opens weekly, grouped version-update PRs (minor and patch together)
for `uv` (`/backend`), `npm` (`/frontend`; semver-major updates of `next`, `react`, and
`react-dom` are ignored because framework majors are planned upgrades), `github-actions` (`/`),
and `docker` base images (`/backend`, `/frontend`). Security updates are enabled in the
repository settings and are not grouped.

### `release.yml`

Versioned, signed, promoted releases (R03-07). Triggered on pushes to `main` (with a `paths`
filter), on `v*` tags (paths filters do not apply to tags), and on manual dispatch.

Main push (or dispatch `target=staging`):

1. `build-images`: builds `api` and `worker` from `backend/Dockerfile` with `--target api` and
   `--target worker`, plus `frontend-staging` and `frontend-production` (public URLs baked in
   at build time). Every build uses `--sbom=true --provenance=mode=max --metadata-file`;
   digests come from `containerimage.digest` in the metadata file (no pull). Each digest is
   signed with cosign keyless (`id-token: write`, `cosign sign --yes <ref>@<digest>`). Never
   runs on tags.
2. `integration-smoke`: the integration compose stack with the built digests.
3. `scan-images`: Trivy on the four pushed digests, then the severity gate.
4. `e2e-integration`: calls `e2e-integration.yml` with `api_image` and `worker_image`.
5. `quality-gate-smoke` and `quality-gate` (R03-03).
6. `deploy-staging` (needs all of the above): Terraform rollout with remote state, smoke test,
   then `docker buildx imagetools create --tag <image>:staging-passed-<sha> <digest>` for
   `api`, `worker`, and `frontend-staging` (a tag on the existing digest, no rebuild).

Tag `vX.Y.Z` (or dispatch `target=production` with `version`, which never builds). Release
candidate tags (`vX.Y.Z-rc.N`) skip production:

1. `verify-staged`: the tag commit must be an ancestor of `origin/main`,
   `scripts/bump_version.py --check` must pass with the tag (all seven version strings equal
   `X.Y.Z`), the changelog must have a `[X.Y.Z]` section, and the digests are resolved from
   `api:staging-passed-<sha>`, `worker:staging-passed-<sha>`, and
   `frontend-production:<sha>`. A missing tag fails the job: that commit did not pass staging.
2. `deploy-production`: `cosign verify` on all three digests with
   `--certificate-identity-regexp '^https://github.com/<owner>/<repo>/.github/workflows/release.yml@refs/heads/main$'`
   and `--certificate-oidc-issuer https://token.actions.githubusercontent.com`; backup gate;
   Terraform rollout of the digests; smoke test; then the digests are tagged `vX.Y.Z` and the
   job asserts that the deployed `api` and `worker` digests equal the `staging-passed-<sha>`
   ones. The production frontend cannot equal the staging digest, because its URLs are baked in
   at build time; it is the `frontend-production` image built in the same `main` run that
   passed staging.
3. `github-release` (`contents: write`): `gh release create vX.Y.Z --notes-file` with the
   section from `scripts/extract_release_notes.py`, the image digests, and the SBOMs
   (`docker buildx imagetools inspect --format '{{ json .SBOM }}'`) as assets. A re-run edits
   the existing release.

Rollback (dispatch `target=rollback`): inputs `environment` (`production` or `staging`) and
`version` run `deploy/scripts/rollback.sh <environment> <version>`, which resolves
`api:vX.Y.Z`, `worker:vX.Y.Z`, and `frontend-<environment>:<sha of vX.Y.Z>` to digests and
swaps the images without running migrations. The three `rollback_*_image` inputs still work
as a deprecated fallback when `version` is empty (kept for one milestone).

Kubernetes (`0.8.0`): `release.yml` does not deploy to a cluster; it still rolls Compose out
with Terraform. Installing or upgrading the Helm chart is an operator step: resolve the digests
the workflow promoted (`api:staging-passed-<sha>` or `api:vX.Y.Z`, the same for `worker`, and
`frontend-<environment>:<sha>`) with `docker buildx imagetools inspect`, then render and apply
with `image.<name>.digest` (and `image.frontend.repository=frontend-<environment>`) as in
[docs/28](./28_KUBERNETES_HELM_DEPLOYMENT.md#workloads-rollout-autoscaling-and-network-policy).
The chart's migrate Job runs as a `pre-install,pre-upgrade` hook, so no separate migration step
is needed there; `helm rollback` runs no migrations.

Concurrency: each deploy job (and rollback) holds `rudix-deploy-staging` or
`rudix-deploy-production`, so two runs never apply Terraform to the same environment at once.
Terraform 1.9.8 S3 state has no lock file here; this group is the serialization.

Terraform state lives in the S3 (or S3-compatible) backend configured by `TF_STATE_*`
(`rudix/<env>.tfstate`). With persistent state an unchanged redeploy (same digests, env file,
and compose file) is a no-op; force a rollout with
`terraform apply -replace=null_resource.compose_rollout`. The SSH connection pins the host
key (`host_key`, from `<ENV>_SSH_KNOWN_HOSTS`), and the deploy scripts use
`StrictHostKeyChecking=yes` through `deploy/scripts/ssh_common.sh`.

### `e2e-integration.yml`

Job `E2E against integration stack` (R03-04). It is a reusable workflow:

- `workflow_call` with required string inputs `api_image` and `worker_image`. It logs in to
  GHCR with `github.token` (`packages: read`) and tests those exact images. `release.yml`
  calls it as job `e2e-integration` (`needs: build-images`) and lists it in
  `deploy-staging.needs`.
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
push to `main` and `develop`, with no workflow-level `paths` filter. A `changes` job sets `pipeline=true`
when the PR touches `backend/app/domains/{chat,ai,rag_profiles,prompt_templates,evaluations,
quality_gates}/`, `backend/app/application/chat/`, `backend/app/interfaces/http/chat.py`,
`backend/app/core/config.py`, `backend/app/core/settings/`, `ci/config/accuracy_eval_thresholds.yml`,
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

OpenAPI contract check (R03-10). Runs on every pull request and on push to `main` and
`develop`, with no `paths` filter. Job `OpenAPI contract`:

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

Terraform remote state (used by `deploy-staging` and `deploy-production`; one bucket, one key
per environment, `rudix/staging.tfstate` and `rudix/production.tfstate`):

| Secret                       | Expected content                                                                        |
| ---------------------------- | --------------------------------------------------------------------------------------- |
| `TF_STATE_BUCKET`            | State bucket name. Enable versioning and encryption on it.                              |
| `TF_STATE_REGION`            | Bucket region (any value the store accepts for S3-compatible stores).                   |
| `TF_STATE_ENDPOINT`          | Optional. S3-compatible endpoint URL; when set, path-style and AWS-only checks are off. |
| `TF_STATE_ACCESS_KEY_ID`     | Access key limited to that bucket.                                                      |
| `TF_STATE_SECRET_ACCESS_KEY` | Matching secret key.                                                                    |

See `deploy/terraform/backend.hcl.example` for the same settings as a file.

### Staging environment

| Secret                    | Expected content                                                                                                     |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `STAGING_SSH_HOST`        | Staging server hostname or IP address.                                                                               |
| `STAGING_SSH_PORT`        | Optional SSH port; defaults to `22` when unset.                                                                      |
| `STAGING_SSH_USER`        | Linux deploy user on the staging server.                                                                             |
| `STAGING_SSH_PRIVATE_KEY` | Full private key for the staging deploy user, including header and footer lines.                                     |
| `STAGING_SSH_KNOWN_HOSTS` | Pinned `known_hosts` line(s) for the staging host (ed25519 line first). Required; there is no trust-on-first-use.    |
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

Collect the host key from the server itself (`ssh-keyscan -t ed25519 -p <port> <host>` run
from a trusted network, then compare the fingerprint with `ssh-keygen -lf
/etc/ssh/ssh_host_ed25519_key.pub` on the host console). The deploy scripts write the secret
to a temporary `known_hosts` file with `StrictHostKeyChecking=yes`; Terraform gets fields 2
and 3 of the first line (`ssh-ed25519 AAAA...`) as `TF_VAR_ssh_host_key`. Rotate the secret
whenever the host key changes; a mismatch fails the deploy instead of connecting.

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
| `PRODUCTION_SSH_KNOWN_HOSTS`      | Pinned `known_hosts` line(s) for the production host (ed25519 line first). Required.              |
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

### Single frontend image (optional, R08-11)

By default `build-images` builds two frontend images, `frontend-staging` and
`frontend-production`, each with its environment's public URLs baked in. Set the repository
variable `RUDIX_FRONTEND_IMAGE_MODE=single` to build one image instead, in request mode
(`NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE=request`), with `NEXT_PUBLIC_PUBLIC_SITE_URL` from the
variable `RUDIX_PUBLIC_SITE_URL` (required, `https://`). The image is pushed under both
repositories, so `frontend_staging_image` and `frontend_production_image` are the same digest
and the rest of the workflow (scan, sign, staging deploy, promotion) is unchanged. Each
environment then sets its public values at runtime (container env or the chart's
`runtimeConfig.env`). Canonical URLs stay build-time, so staging serves the production
canonical URL and must send `X-Robots-Tag: noindex` (`EDGE_NOINDEX=true`); a CDN asset prefix
must be one host for both. This path is first exercised in GitHub Actions; leave the variable
unset until the owner has accepted those two decisions.

### Per-secret environment secrets (recommended, R08-11)

`STAGING_ENV_FILE` and `PRODUCTION_ENV_FILE` carry every backend secret in one GitHub secret.
Rotating one value means rewriting and re-pasting the whole file, and every reader of the
secret sees all values. Move to one GitHub environment secret per value (for example
`APP_AUTH_SECRET`, `APP_AUTH_SECRET_PREVIOUS`, `DATABASE_URL`, `METRICS_BEARER_TOKEN`) that
the deploy step writes into the env file, or to a secret manager read by the chart's
`secrets.externalSecret` (External Secrets Operator). Until then, keep the whole-file secrets;
the rotation order for each value is in `docs/11` `### Rotation`.

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
