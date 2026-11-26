# Deployment Guide

Step-by-step instructions for setting up CI/CD and deploying Rudix to staging and production using GitHub Actions, Docker Compose, and SSH.

---

## Canonical Deployment URLs

Use these exact public URLs for Rudix-hosted deployments:

| Environment | Frontend URL                   | Browser API base URL                      | Backend origin URL                 |
| ----------- | ------------------------------ | ----------------------------------------- | ---------------------------------- |
| Staging     | `https://staging.getrudix.com` | `https://api-staging.getrudix.com/api/v1` | `https://api-staging.getrudix.com` |
| Production  | `https://getrudix.com`         | `https://api.getrudix.com/api/v1`         | `https://api.getrudix.com`         |

Do not use `localhost`, `127.0.0.1`, or placeholder domains in deployed
staging/production secrets. The frontend image must be built with the matching
`NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_APP_URL` values because Next.js embeds
those public variables into the browser bundle at build time.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Prepare the Server](#2-prepare-the-server)
3. [Generate SSH Deploy Keys](#3-generate-ssh-deploy-keys)
4. [Create a GitHub PAT for GHCR](#4-create-a-github-pat-for-ghcr)
5. [Set Up GitHub Environments](#5-set-up-github-environments)
6. [Add GitHub Secrets](#6-add-github-secrets)
7. [Build the ENV File](#7-build-the-env-file)
8. [Trigger the First Deploy](#8-trigger-the-first-deploy)
9. [Verify the Deployment](#9-verify-the-deployment)
10. [Set Up Production Backups](#10-set-up-production-backups)
11. [Set Up Accuracy Evaluation (Optional)](#11-set-up-accuracy-evaluation-optional)
12. [Set Up Sentry (Optional)](#12-set-up-sentry-optional)
13. [Rollback](#13-rollback)

---

## 1. Prerequisites

Install these on your **local machine** before starting:

```bash
# GitHub CLI
brew install gh          # macOS
# or https://cli.github.com for Linux/Windows

# Authenticate
gh auth login

# Verify
gh auth status
```

Your server needs:

- Ubuntu 22.04 or later (or any Docker-capable Linux)
- Docker Engine ≥ 24
- Docker Compose plugin (`docker compose` not `docker-compose`)
- Open ports: `80`, `443`, `8000` (API), `3000` (frontend)

Install Docker on the server:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # allow your deploy user to run docker
```

---

## 2. Prepare the Server

SSH into your server and create the app directory:

```bash
# Staging
ssh ubuntu@<staging-ip>
sudo mkdir -p /opt/rudix
sudo chown ubuntu:ubuntu /opt/rudix

# Production
ssh ubuntu@<production-ip>
sudo mkdir -p /opt/rudix
sudo chown ubuntu:ubuntu /opt/rudix
```

---

## 3. Generate SSH Deploy Keys

Run this on your **local machine** — once for staging, once for production:

```bash
# Staging key
ssh-keygen -t ed25519 -C "github-actions-staging" -f ~/.ssh/rudix_staging_deploy -N ""

# Production key
ssh-keygen -t ed25519 -C "github-actions-production" -f ~/.ssh/rudix_production_deploy -N ""
```

Copy each public key to its server:

```bash
# Staging
ssh-copy-id -i ~/.ssh/rudix_staging_deploy.pub ubuntu@<staging-ip>

# Production
ssh-copy-id -i ~/.ssh/rudix_production_deploy.pub ubuntu@<production-ip>
```

Keep the **private key** (`~/.ssh/rudix_staging_deploy`) — you will paste its contents into GitHub secrets in step 6.

---

## 4. Create a GitHub PAT for GHCR

GitHub Actions pushes Docker images to the GitHub Container Registry (GHCR). You need a Personal Access Token (PAT) for this.

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Click **Generate new token (classic)**
3. Set expiry to **No expiration** (or rotate annually)
4. Select scope: **`write:packages`** (includes `read:packages`)
5. Click **Generate token** and copy the value — you only see it once

---

## 5. Set Up GitHub Environments

GitHub Environments let you protect production deploys with required reviewers.

1. Go to your repo → **Settings → Environments**
2. Click **New environment** → name it `staging` → click **Configure environment**
   - No protection rules needed for staging
3. Click **New environment** → name it `production` → click **Configure environment**
   - Enable **Required reviewers** → add yourself or your team
   - Enable **Prevent self-review** (recommended)

---

## 6. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions**.

All secrets below go under **Repository secrets** (not environment secrets), unless noted otherwise.

### 6a. Container Registry

| Secret          | Value                         |
| --------------- | ----------------------------- |
| `GHCR_USERNAME` | Your GitHub username          |
| `GHCR_TOKEN`    | The PAT you created in step 4 |

### 6b. OpenAI (used in integration smoke test)

| Secret           | Value                             |
| ---------------- | --------------------------------- |
| `OPENAI_API_KEY` | `sk-...` from platform.openai.com |

### 6c. Staging Server

| Secret                    | Value                                                                          |
| ------------------------- | ------------------------------------------------------------------------------ |
| `STAGING_SSH_HOST`        | Staging server IP or hostname                                                  |
| `STAGING_SSH_PORT`        | SSH port — omit if `22`                                                        |
| `STAGING_SSH_USER`        | Linux user, e.g. `ubuntu`                                                      |
| `STAGING_SSH_PRIVATE_KEY` | Full content of `~/.ssh/rudix_staging_deploy`                                  |
| `STAGING_APP_PATH`        | `/opt/rudix`                                                                   |
| `STAGING_ENV_URL`         | `https://staging.getrudix.com`                                                 |
| `STAGING_ENV_FILE`        | Full `.env` file content — see [step 7](#7-build-the-env-file)                 |
| `FRONTEND_ENV_STAGING`    | Browser-safe frontend-only env overrides — see [step 7](#7-build-the-env-file) |

### 6d. Production Server

| Secret                            | Value                                                          |
| --------------------------------- | -------------------------------------------------------------- |
| `PRODUCTION_SSH_HOST`             | Production server IP or hostname                               |
| `PRODUCTION_SSH_PORT`             | SSH port — omit if `22`                                        |
| `PRODUCTION_SSH_USER`             | Linux user, e.g. `ubuntu`                                      |
| `PRODUCTION_SSH_PRIVATE_KEY`      | Full content of `~/.ssh/rudix_production_deploy`               |
| `PRODUCTION_APP_PATH`             | `/opt/rudix`                                                   |
| `PRODUCTION_ENV_URL`              | `https://getrudix.com`                                         |
| `PRODUCTION_ENV_FILE`             | Full `.env` file content — see [step 7](#7-build-the-env-file) |
| `FRONTEND_ENV_PRODUCTION`         | Browser-safe frontend-only env overrides                       |
| `PRODUCTION_POSTGRES_BACKUP_PATH` | `/opt/backups/postgres`                                        |
| `PRODUCTION_MINIO_BACKUP_PATH`    | `/opt/backups/minio`                                           |
| `PRODUCTION_QDRANT_BACKUP_PATH`   | `/opt/backups/qdrant`                                          |
| `PRODUCTION_BACKUP_CHECK_OK`      | `yes` (confirms backups are running before deploy)             |

Each backup path may be a single file or, as in the examples above, a
directory of timestamped dumps. Before Terraform runs, the production job calls
`deploy/scripts/check_remote_backups.sh`, which requires every path to exist and
to contain at least one regular file modified within the last
`DEPLOY_BACKUP_MAX_AGE_HOURS` hours (default `26`, so a daily backup always
passes). A failure names only the failing store (`postgres`, `minio`, or
`qdrant`) and blocks the deploy. See [step 10](#10-set-up-production-backups).

Optional repository **variables** (Settings → Secrets and variables → Actions →
Variables) for the production job:

| Variable                       | Default | Effect                                                                                    |
| ------------------------------ | ------- | ----------------------------------------------------------------------------------------- |
| `DEPLOY_BACKUP_MAX_AGE_HOURS`  | `26`    | Maximum age of the newest backup file per path (positive integer; also read as a secret). |
| `DEPLOY_ALLOW_UNPINNED_IMAGES` | `false` | `true` downgrades the unpinned-image errors of the env check (step 7) to warnings.        |

**To paste a private key:** open the file and copy everything including the header and footer lines:

```
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

### 6e. Add All Secrets with the gh CLI (faster)

```bash
# Container registry
gh secret set GHCR_USERNAME --body "your-github-username"
gh secret set GHCR_TOKEN    --body "ghp_..."

# OpenAI
gh secret set OPENAI_API_KEY --body "sk-..."

# Staging
gh secret set STAGING_SSH_HOST        --body "1.2.3.4"
gh secret set STAGING_SSH_USER        --body "ubuntu"
gh secret set STAGING_SSH_PRIVATE_KEY < ~/.ssh/rudix_staging_deploy
gh secret set STAGING_APP_PATH        --body "/opt/rudix"
gh secret set STAGING_ENV_URL         --body "https://staging.getrudix.com"
gh secret set STAGING_ENV_FILE        < /path/to/staging.env
gh secret set FRONTEND_ENV_STAGING    < /path/to/frontend-staging.env

# Production
gh secret set PRODUCTION_SSH_HOST        --body "5.6.7.8"
gh secret set PRODUCTION_SSH_USER        --body "ubuntu"
gh secret set PRODUCTION_SSH_PRIVATE_KEY < ~/.ssh/rudix_production_deploy
gh secret set PRODUCTION_APP_PATH        --body "/opt/rudix"
gh secret set PRODUCTION_ENV_URL         --body "https://getrudix.com"
gh secret set PRODUCTION_ENV_FILE        < /path/to/production.env
gh secret set FRONTEND_ENV_PRODUCTION    < /path/to/frontend-production.env
gh secret set PRODUCTION_POSTGRES_BACKUP_PATH --body "/opt/backups/postgres"
gh secret set PRODUCTION_MINIO_BACKUP_PATH    --body "/opt/backups/minio"
gh secret set PRODUCTION_QDRANT_BACKUP_PATH   --body "/opt/backups/qdrant"
gh secret set PRODUCTION_BACKUP_CHECK_OK      --body "yes"
```

---

## 7. Build the ENV File

Create a `.env` file for each environment. Start from `.env.example` and change the values below. Do **not** commit these files — paste their contents into the `STAGING_ENV_FILE` / `PRODUCTION_ENV_FILE` secrets.

`STAGING_ENV_FILE` and `PRODUCTION_ENV_FILE` are server-side environment files
used by Docker Compose for the API, workers, MCP server, and infrastructure
containers. They may contain private backend secrets. Do not put these backend
secrets in any `NEXT_PUBLIC_*` variable.

`FRONTEND_ENV_STAGING` and `FRONTEND_ENV_PRODUCTION` are separate. They are
used only while building the Next.js frontend images and may contain only
browser-safe `NEXT_PUBLIC_*` values. The release workflow writes these
deployment-owned values itself, so do not put them in the frontend env secrets:

Staging:

```env
NEXT_PUBLIC_DEPLOYMENT_ENV=staging
NEXT_PUBLIC_API_URL=https://api-staging.getrudix.com/api/v1
NEXT_PUBLIC_APP_URL=https://staging.getrudix.com
```

Production:

```env
NEXT_PUBLIC_DEPLOYMENT_ENV=production
NEXT_PUBLIC_API_URL=https://api.getrudix.com/api/v1
NEXT_PUBLIC_APP_URL=https://getrudix.com
```

Recommended `FRONTEND_ENV_STAGING` content:

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

For production, use the same public keys with `https://api.getrudix.com/api/v1`
in the auth URLs. Never set `NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN` for
deployed environments; `NEXT_PUBLIC_*` variables are readable by every browser
user.

### Generate required secrets first

```bash
# Strong random secret for APP_AUTH_SECRET
openssl rand -hex 32

# Strong random passwords for databases and queues
openssl rand -base64 24   # run once per password needed
```

### Minimum required changes from .env.example

```bash
# ── Environment ───────────────────────────────────────────────────────────────
ENVIRONMENT=production                          # or staging
API_BASE_URL=https://api.getrudix.com           # staging: https://api-staging.getrudix.com
FRONTEND_BASE_URL=https://getrudix.com          # staging: https://staging.getrudix.com
CORS_ORIGINS=https://getrudix.com               # staging: https://staging.getrudix.com

# ── Auth ──────────────────────────────────────────────────────────────────────
APP_AUTH_SECRET=<output of: openssl rand -hex 32>
AUTH_PROVIDER=app
APP_AUTH_ISSUER=rudix-app
APP_AUTH_AUDIENCE=rudix-api

# ── Database ──────────────────────────────────────────────────────────────────
POSTGRES_DB=rag_app
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<strong-password>
DATABASE_URL=postgresql+asyncpg://postgres:<strong-password>@postgres:5432/rag_app

# ── Vector store ──────────────────────────────────────────────────────────────
QDRANT_URL=http://qdrant:6333              # internal Docker service name — keep as-is
QDRANT_COLLECTION=documents
QDRANT_VECTOR_SIZE=1536
QDRANT_BOOTSTRAP_COLLECTION=true

# ── Object storage ────────────────────────────────────────────────────────────
MINIO_ENDPOINT=http://minio:9000           # internal Docker service name — keep as-is
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=<strong-password>
MINIO_ACCESS_KEY=<access-key>
MINIO_SECRET_KEY=<strong-password>
MINIO_BUCKET=documents
MINIO_BOOTSTRAP_BUCKET=true

# ── Message queue ─────────────────────────────────────────────────────────────
RABBITMQ_DEFAULT_USER=admin
RABBITMQ_DEFAULT_PASS=<strong-password>
RABBITMQ_URL=amqp://admin:<strong-password>@rabbitmq:5672//   # internal — keep host as-is

# ── Cache ─────────────────────────────────────────────────────────────────────
# Compose builds REDIS_URL as redis://:${REDIS_PASSWORD}@redis:6379/0 for the
# api, worker, beat, and mcp services and starts Redis with --requirepass.
REDIS_PASSWORD=<output of: openssl rand -hex 32>   # URL-safe characters only

# ── Infrastructure images (pin exact tags or digests; see below) ─────────────
QDRANT_IMAGE=qdrant/qdrant@sha256:<digest>
MINIO_IMAGE=cgr.dev/chainguard/minio@sha256:<digest>
RABBITMQ_IMAGE=rabbitmq@sha256:<digest>
# Optional; defaults are redis:7 and clamav/clamav-debian:stable
# REDIS_IMAGE=redis:7
# CLAMAV_IMAGE=clamav/clamav-debian:stable

# ── LLM ──────────────────────────────────────────────────────────────────────
LLM_DEFAULT_PROVIDER=openai
EMBEDDING_DEFAULT_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_LLM_MODEL=gpt-5.4-mini

# ── Features ──────────────────────────────────────────────────────────────────
FEATURE_ENABLE_EMBEDDINGS=true
FEATURE_ENABLE_LLM=true
FEATURE_ENABLE_EVALUATIONS=true
FEATURE_ENABLE_PIPELINE_EXPLORER=true
FEATURE_ENABLE_CONNECTORS=true
FEATURE_ENABLE_AGENTS=false
```

Everything else in `.env.example` can stay at its default value.
`MALWARE_SCAN_CLAMAV_HOST` is set to the bundled `clamav` service by the
staging/production compose files. The backend refuses to start in staging or
production when malware scanning is enabled and the ClamAV host is a loopback
address (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`); set
`MALWARE_SCAN_ENABLED=false` explicitly only if you accept uploads without a scan.

### Deploy env check

Right after the secrets validation, both deploy jobs run
`deploy/scripts/check_deploy_env.sh` on the env file (passed through the step's
`env:` block; values are never printed):

- `REDIS_PASSWORD` must be set and match `^[A-Za-z0-9._~-]+$`.
- `QDRANT_IMAGE`, `MINIO_IMAGE`, and `RABBITMQ_IMAGE` must be set and pinned:
  an explicit tag other than `latest`, or a digest.

In production any failure stops the deploy; the image checks become warnings
when the `DEPLOY_ALLOW_UNPINNED_IMAGES` variable is `true`. In staging every
finding is a warning.

### Pin the running infrastructure versions before the first deploy

Unset image variables fall back to the previous floating tags
(`qdrant/qdrant:latest`, `cgr.dev/chainguard/minio:latest`,
`rabbitmq:3-management`), so pin what each host runs today instead of guessing
a version. On each server:

```bash
cd /opt/rudix
docker compose -f docker-compose.production.yml images   # or docker-compose.staging.yml
docker inspect --format '{{index .RepoDigests 0}}' "$(docker compose -f docker-compose.production.yml ps -q qdrant)"
docker inspect --format '{{index .RepoDigests 0}}' "$(docker compose -f docker-compose.production.yml ps -q minio)"
docker inspect --format '{{index .RepoDigests 0}}' "$(docker compose -f docker-compose.production.yml ps -q rabbitmq)"
```

Put the printed `image@sha256:...` references into `QDRANT_IMAGE`,
`MINIO_IMAGE`, and `RABBITMQ_IMAGE` in `PRODUCTION_ENV_FILE` /
`STAGING_ENV_FILE`. Upgrade later by changing those values deliberately.

### Maintenance window for the Redis/RabbitMQ/ClamAV rollout

The first deploy that adds `REDIS_PASSWORD` and the Redis/RabbitMQ volumes
recreates the `redis` and `rabbitmq` containers. Plan it in a maintenance window:

- In-flight Celery results and Redis rate-limit counters are lost.
- Messages queued in RabbitMQ are lost once (they are already lost on every
  recreate today; from now on `rabbitmq_data` and the fixed `hostname: rabbitmq`
  keep them across recreates).
- The first `clamav` start downloads the signature database, which can take
  several minutes (healthcheck `start_period: 300s`). The API and worker do not
  wait for it; until it is ready, uploads follow `MALWARE_SCAN_REQUIRED` and
  `MALWARE_SCAN_BYPASS_ON_UNAVAILABLE`. The final `docker compose up -d --wait`
  of the Terraform rollout does wait for every service, so that first deploy can
  take up to about 10 minutes, and it fails if ClamAV never becomes healthy.
  `clamd` holds the signature database in memory (roughly 1.5 GB, more while it
  reloads signatures), so check the host's free memory first.

---

## 8. Trigger the First Deploy

### Staging (automatic on push to main)

```bash
git push origin main
```

This triggers `release.yml` which:

1. Builds and pushes Docker images to GHCR
2. Runs the integration smoke test
3. SSHes into the staging server and deploys via Docker Compose
4. Runs database migrations on the server
5. Checks `/api/v1/health` and `/api/v1/ready`

Monitor progress at: **GitHub → Actions → Release**

### Staging (manual)

```bash
gh workflow run release.yml --field target=staging
```

### Production (manual dispatch)

```bash
gh workflow run release.yml --field target=production
```

Or push a version tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Production deploy requires approval from the reviewers you added to the `production` Environment in step 5.

---

## 9. Verify the Deployment

After the workflow completes, verify from your local machine:

```bash
# Health check
curl https://api-staging.getrudix.com/api/v1/health

# Readiness check
curl https://api-staging.getrudix.com/api/v1/ready

# Auth boundary (should return 401)
curl https://api-staging.getrudix.com/api/v1/documents
```

Then open `https://staging.getrudix.com` in a browser and log in. For
production, use `https://api.getrudix.com/api/v1/*` and `https://getrudix.com`.

---

## 10. Set Up Production Backups

The production deploy job checks that every backup path holds a recent backup
before deploying. Expected layout: one directory per store with timestamped
dumps, the newest modified within `DEPLOY_BACKUP_MAX_AGE_HOURS` (default 26 h):

```text
/opt/backups/postgres/backup-20261125.sql.gz
/opt/backups/minio/minio-20261125.tar.gz
/opt/backups/qdrant/documents-20261125.snapshot
```

A path may also be a single file that is overwritten on each run, or a symlink
to the latest dump (the check follows a symlinked path). Missing
paths, empty directories, and stale backups fail the deploy. Set up a cron job
on the production server:

```bash
# On the production server
sudo mkdir -p /opt/backups/postgres /opt/backups/minio /opt/backups/qdrant

# Example: daily Postgres dump at 2am
crontab -e
# Add:
# 0 2 * * * docker exec rudix-postgres pg_dump -U postgres rag_app | gzip > /opt/backups/postgres/backup-$(date +\%Y\%m\%d).sql.gz
```

Once each path holds a backup newer than the age limit, the `PRODUCTION_BACKUP_CHECK_OK=yes` secret tells the deploy job the backup system is active. Schedule backups at least daily so the 26-hour default always passes.

---

## 11. Set Up Accuracy Evaluation

The accuracy eval workflow (`accuracy-eval.yml`) calls your **live deployed API** to measure answer quality. It requires the app to already be deployed.

It runs **nightly at 02:00 UTC** against staging. Before every staging deploy, `release.yml` gates on the **latest completed nightly run** of `ACCURACY_EVAL_SET_ID` (`quality-gate.yml` with `EVALUATION_RUN_ID=latest`); the gate fails when no completed run exists or the newest one is older than **36 hours** (set the repository variable `QUALITY_GATE_MAX_RUN_AGE_HOURS` to change it). Without these secrets the staging deploy is blocked. To bootstrap a repository before staging exists, set the repository variable `QUALITY_GATE_ALLOW_MISSING_CONFIG=true` (missing secrets become a warning); remove it once the secrets below are set.

### Steps

1. Deploy the app (steps 1–9 above)
2. Log in to the app as an admin
3. Go to **Admin → API Keys** → create a service account key with `evaluations:read` scope
4. Go to **Admin → Evaluations → Datasets** → create or import a dataset → copy its UUID
5. Go to **Admin → Quality Gates** → create a gate with your thresholds → copy its UUID
6. Add the secrets:

```bash
gh secret set RUDIX_API_BASE_URL   --body "https://api-staging.getrudix.com/api/v1"
gh secret set RUDIX_API_TOKEN      --body "rudix_..."
gh secret set ACCURACY_EVAL_SET_ID --body "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
gh secret set QUALITY_GATE_ID      --body "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

### Run it

```bash
gh workflow run accuracy-eval.yml --field mode=smoke
```

Run it once in `nightly` mode after setup so the first staging release has a fresh run to gate on:

```bash
gh workflow run accuracy-eval.yml --field mode=nightly
gh variable set QUALITY_GATE_MAX_RUN_AGE_HOURS --body "36"   # optional
```

---

## 12. Set Up Sentry (Optional)

```bash
gh secret set SENTRY_DSN        --body "https://...@sentry.io/..."
gh secret set SENTRY_AUTH_TOKEN --body "sntrys_..."
gh secret set SENTRY_ORG        --body "your-org-slug"
gh secret set SENTRY_PROJECT    --body "rudix"
```

Sentry releases are tagged automatically on every staging and production deploy.

---

## 13. Rollback

To roll back production to a previous image set:

1. Go to **GitHub → Actions → Release → Run workflow**
2. Set **target** to `rollback`
3. Paste the image digests from a previous deploy's artifact (download `image-digests` artifact from a prior run)

Or via CLI:

```bash
gh workflow run release.yml \
  --field target=rollback \
  --field rollback_api_image=ghcr.io/owner/repo/api@sha256:... \
  --field rollback_worker_image=ghcr.io/owner/repo/worker@sha256:... \
  --field rollback_frontend_image=ghcr.io/owner/repo/frontend@sha256:...
```

---

## Summary Checklist

```
 Server setup
 [ ] Docker installed on staging server
 [ ] Docker installed on production server
 [ ] /opt/rudix directory created on each server

 SSH keys
 [ ] Staging deploy key generated and public key added to server
 [ ] Production deploy key generated and public key added to server

 GitHub
 [ ] staging Environment created
 [ ] production Environment created with required reviewers
 [ ] GHCR_USERNAME secret added
 [ ] GHCR_TOKEN secret added (write:packages scope)
 [ ] OPENAI_API_KEY secret added
 [ ] All STAGING_* secrets added (7 secrets)
 [ ] All PRODUCTION_* secrets added (11 secrets)

 ENV files
 [ ] staging.env file built with real values
 [ ] production.env file built with real values
 [ ] Both pasted into STAGING_ENV_FILE / PRODUCTION_ENV_FILE secrets

 First deploy
 [ ] Push to main → staging deploy completes
 [ ] Health check passes on staging
 [ ] Production tag pushed or manually triggered

 Optional
 [ ] Backup cron running on production server
 [ ] RUDIX_API_* secrets added for accuracy eval
 [ ] Sentry secrets added
```
