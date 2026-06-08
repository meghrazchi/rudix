# 18 — Langfuse LLM Observability

This document covers how to run the self-hosted Langfuse observability stack alongside Rudix, how to configure Rudix to send traces to it, and what the traces contain. It also covers privacy controls, backup, upgrade, and production deployment notes.

---

## Overview

Langfuse is an **optional** open-source LLM observability platform. When enabled, Rudix sends structured traces for every chat/RAG request so you can inspect:

- Prompt and answer content (configurable — can be redacted)
- Retrieval, reranking, embedding, and LLM generation latencies
- Token usage and estimated cost per request
- Confidence scores, citation counts, not-found signals
- Language detection and answer language decisions
- Error types and fallback flags

Langfuse is never a hard runtime dependency. When it is disabled or unreachable, no requests fail and no errors are surfaced to users.

---

## Quick start (local / dev)

### 1. Start Langfuse

```bash
cd infra/langfuse
cp .env.example .env
# Edit .env — fill in LANGFUSE_NEXTAUTH_SECRET and LANGFUSE_SALT
# Any random 32-char string works for local dev: openssl rand -hex 32
docker compose up -d
```

Langfuse is then available at **http://localhost:3030**.

### 2. Create a project and get API keys

1. Open http://localhost:3030 and create an account (local only, no email verification).
2. Create a project.
3. Go to **Settings → API Keys** and create a key pair.
4. Copy the **Public Key** and **Secret Key**.

### 3. Configure Rudix

Add to your Rudix `.env`:

```env
LANGFUSE_ENABLED=true
LANGFUSE_BASE_URL=http://localhost:3030
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_CAPTURE_INPUT_OUTPUT=true
LANGFUSE_REDACTION_MODE=none
```

### 4. Restart the Rudix API

```bash
docker compose restart api
# or for local uvicorn: just restart the process
```

After the next chat query you should see a trace appear in the Langfuse UI under **Traces**.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `LANGFUSE_ENABLED` | `false` | Master switch. Set to `true` to activate tracing. |
| `LANGFUSE_BASE_URL` | _(none)_ | Full URL of the Langfuse server, e.g. `http://localhost:3030`. |
| `LANGFUSE_PUBLIC_KEY` | _(none)_ | Project public key (safe to log). |
| `LANGFUSE_SECRET_KEY` | _(none)_ | Project secret key — never log or expose in responses. |
| `LANGFUSE_SAMPLE_RATE` | `1.0` | Fraction of requests to trace (0.0–1.0). Use `0.1` in high-traffic production. |
| `LANGFUSE_CAPTURE_INPUT_OUTPUT` | `true` | When `false`, question and answer are always redacted regardless of redaction mode. |
| `LANGFUSE_REDACTION_MODE` | `none` | See [Privacy and redaction](#privacy-and-redaction) below. |

All keys are server-side only. They are never returned by any API endpoint or included in frontend configuration.

---

## Privacy and redaction

Rudix applies the following rules before sending any data to Langfuse:

### User IDs

User IDs are one-way hashed (SHA-256, first 16 hex chars with a `u_` prefix) before being sent. The raw user ID is never included in a trace. This means you can filter traces by user without being able to reconstruct the original ID from the trace.

### `LANGFUSE_REDACTION_MODE`

| Mode | Question | Answer | Chunk text |
|---|---|---|---|
| `none` (default) | Sent as-is | Sent as-is | Never sent (not in trace payload) |
| `inputs` | Redacted | Sent as-is | Never sent |
| `all` | Redacted | Redacted | Never sent |

Chunk text (retrieved document content) is **never** included in traces regardless of the redaction mode — only counts, scores, and metadata are sent.

### What is never sent

- Raw connector tokens, OAuth credentials, or refresh tokens
- JWT access tokens or session cookies
- OpenAI API keys or any provider secrets
- MinIO signed URLs or object storage credentials
- Raw document text or chunk content
- Any field with a key matching `*_secret`, `*_token`, `*_api_key`, `*_password`, or `authorization`

---

## Trace structure

Each chat/RAG query produces one Langfuse trace with the following child spans:

```
rag.chat                          (root trace)
  ├── embedding.query             latency, model, token count
  ├── retrieval.vector_search     latency, retrieved_count
  ├── retrieval.rerank            latency, selected_count  (only when rerank=true)
  ├── llm.generate_answer         model, token usage, cost estimate, latency
  └── citations.validate          cited_count, validation_failed flag
```

For `scope_mode=none` (general LLM chat, no retrieval):

```
rag.chat
  └── llm.generate_answer
```

### Trace metadata fields

| Field | Description |
|---|---|
| `organization_id` | Organization UUID |
| `feature_area` | Always `chat` for chat/RAG requests |
| `scope_mode` | `all`, `collection`, `documents`, or `none` |
| `source_scope` | Human-readable scope label |
| `environment` | `development`, `staging`, or `production` |
| `release_version` | API version string |
| `retrieved_count` | Chunks returned by vector search |
| `selected_count` | Chunks after reranking |
| `cited_count` | Citations in the final answer |
| `not_found` | `true` when the answer could not be grounded |
| `citation_validation_failed` | `true` when citation chunk IDs could not be resolved |
| `confidence_score` | Float 0–1 |
| `confidence_category` | `low`, `medium`, or `high` |
| `embedding_model` | Embedding model used for query |
| `detected_language` | ISO 639-1 code of the detected question language |
| `answer_language_used` | ISO 639-1 code of the answer language |
| `prompt_template_key` | Template key used for generation |
| `prompt_template_version` | Template version number |
| `answer_latency_ms` | End-to-end request latency |

---

## Admin diagnostics

Admins and owners can check Langfuse status without restarting the API:

```
GET /api/v1/admin/langfuse/status
Authorization: Bearer <admin token>
```

Response (no secrets are included):

```json
{
  "enabled": true,
  "base_url_configured": true,
  "keys_configured": true,
  "client_initialized": true,
  "reachable": true,
  "last_error": null
}
```

`reachable` is checked live by probing `{LANGFUSE_BASE_URL}/api/public/health`. `client_initialized` reflects whether `init_langfuse()` succeeded at startup.

---

## Docker Compose operations

All commands run from `infra/langfuse/`:

### Start

```bash
docker compose up -d
```

### Stop (preserves data)

```bash
docker compose down
```

### Stop and delete all data

```bash
docker compose down -v   # removes the langfuse_postgres_data volume
```

### View logs

```bash
docker compose logs -f langfuse
docker compose logs -f langfuse-postgres
```

### Upgrade Langfuse

```bash
docker compose pull
docker compose up -d
```

Langfuse runs database migrations automatically on startup. Always read the Langfuse release notes before upgrading in production.

### Backup

The only stateful component is the `langfuse_postgres_data` volume. To back it up:

```bash
docker run --rm \
  -v rudix_langfuse_postgres_data:/data \
  -v $(pwd)/backups:/backup \
  postgres:16-alpine \
  pg_dump -U langfuse -h langfuse-postgres langfuse \
  > backups/langfuse-$(date +%Y%m%d-%H%M%S).sql
```

To restore, bring Postgres up without Langfuse and `psql` the dump in before starting the full stack.

### Reset (wipe all traces)

```bash
docker compose down -v
docker compose up -d
```

---

## Docker network considerations

The Langfuse compose file defines its own isolated network. By default:

| Scenario | `LANGFUSE_BASE_URL` value |
|---|---|
| Rudix API running locally (native) | `http://localhost:3030` |
| Rudix API inside Docker (same host) | `http://host.docker.internal:3030` (Mac/Windows) |
| Rudix API and Langfuse on the same Docker host (Linux) | `http://172.17.0.1:3030` or use a shared external network |

To share a network between the two stacks, create an external network and reference it in both compose files:

```bash
docker network create rudix-observability
```

In `infra/langfuse/docker-compose.yml` and `docker-compose.yml`, add:

```yaml
networks:
  rudix-observability:
    external: true
```

Then set `LANGFUSE_BASE_URL=http://langfuse:3000` (using the service name, port 3000 inside the network).

---

## Running both stacks with one command

```bash
# From the project root
docker compose -f docker-compose.yml -f infra/langfuse/docker-compose.yml up -d
```

Or with Docker Compose v2.20+ `include` directive in `docker-compose.yml`:

```yaml
include:
  - path: infra/langfuse/docker-compose.yml
    env_file: infra/langfuse/.env
```

---

## Single-VM production deployment

Langfuse standalone is suitable for a single VM. Keep the following in mind:

- **Put a reverse proxy in front** (nginx, Caddy, Traefik) with TLS. Langfuse stores sensitive trace data — never expose it over plain HTTP on a public interface.
- **Set `NEXTAUTH_URL`** to the public HTTPS URL (e.g. `https://langfuse.internal.yourcompany.com`).
- **Use strong secrets** for `NEXTAUTH_SECRET` and `SALT` (at least 32 random bytes each).
- **Firewall the Postgres port** (5432) — it must not be reachable from outside the VM.
- **There is no built-in high availability.** Postgres on a single volume is a single point of failure. For HA you need an external managed Postgres (e.g. RDS, Cloud SQL) and multiple Langfuse instances behind a load balancer.
- **Back up the Postgres volume** on a regular schedule before upgrades.
- **`TELEMETRY_ENABLED=false`** is already set in the compose file — this prevents usage data being sent to Langfuse Inc.

---

## Sampling in production

At high request volumes, tracing every request adds storage cost. Recommended values:

| Traffic | `LANGFUSE_SAMPLE_RATE` |
|---|---|
| Development | `1.0` (trace everything) |
| Staging | `1.0` |
| Low production (< 1k req/day) | `1.0` |
| Medium production (1k–50k req/day) | `0.2` |
| High production (> 50k req/day) | `0.05`–`0.1` |

Sampling is random per request. For deterministic sampling tied to session ID, you can extend `langfuse_tracer.py`'s `_should_sample()` function.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No traces in Langfuse | `LANGFUSE_ENABLED=false` or wrong keys | Check `/api/v1/admin/langfuse/status` |
| `client_initialized: false` in status | Init failed at startup — check API logs for `langfuse.disabled` | Verify keys and `BASE_URL`; restart API |
| `reachable: false` in status | Network connectivity issue | Check Docker network (see above); verify Langfuse is running |
| Traces appear but no spans | SDK version mismatch | Ensure `langfuse>=2.0.0,<4.0.0` is installed |
| Questions appear as `<redacted:question>` | `LANGFUSE_REDACTION_MODE=inputs` or `all`, or `LANGFUSE_CAPTURE_INPUT_OUTPUT=false` | Adjust redaction settings |
| API startup warning about Langfuse | Keys missing while `LANGFUSE_ENABLED=true` | Add `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` |
