# 19 — Local LLM Provider Integration

This guide covers how to configure, run, secure, evaluate, and roll out local LLM providers in Rudix across development, staging, and production environments.

Rudix routes all generation and embedding work through a unified provider interface. A local OpenAI-compatible endpoint can replace cloud providers without any change to the core RAG pipeline.

Related features: F218 (local adapter), F220 (model profiles), F222 (Compose profiles), F223 (routing + fallback), F225 (governance), F226 (evaluation gates), F228 (provider observability).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ChatRequest / EmbedRequest                                      │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
       resolve_task_profile()          ← OrgModelProfile or env default
               │
               ▼
       check_provider_governance()     ← local_only_mode, allowed_provider_profiles
               │
          ┌────┴─────┐
          │  primary  │   OpenAICompatibleChatProvider (local)
          └────┬──────┘         AsyncOpenAI(base_url=LOCAL_LLM_BASE_URL)
               │  transient error + feature_enable_provider_fallback=True
               ▼
          ┌─────────────┐
          │  fallback   │   cloud provider (OpenAI) — NOTE: sends document context externally
          └─────────────┘
```

### Provider types

| `LLM_DEFAULT_PROVIDER` | What it uses |
|---|---|
| `openai` (default) | OpenAI API (`OPENAI_API_KEY` required) |
| `local` | `LOCAL_LLM_BASE_URL` — any OpenAI-compatible endpoint |

| `EMBEDDING_DEFAULT_PROVIDER` | What it uses |
|---|---|
| `openai` (default) | OpenAI embeddings API |
| `local` | `LOCAL_EMBEDDING_BASE_URL` — any `/v1/embeddings`-compatible endpoint |

Compatible local providers:
- **Ollama** — `make up-ollama`, base URL `http://ollama:11434/v1`
- **vLLM** — `make up-vllm`, base URL `http://vllm:8000/v1`
- **LiteLLM gateway** — `make up-litellm`, base URL `http://litellm:4000`
- **LocalAI**, **llama.cpp**, any server that implements the OpenAI chat completions API

---

## Quick start (Ollama, development)

### 1. Copy and configure environment

```bash
cp .env.local-llm.example .env
```

Or add these to your existing `.env`:

```env
LLM_DEFAULT_PROVIDER=local
LOCAL_LLM_BASE_URL=http://ollama:11434/v1
LOCAL_LLM_MODEL=llama3.2
LOCAL_LLM_PROVIDER_KIND=ollama
LOCAL_LLM_JSON_MODE_ENABLED=false
LOCAL_LLM_TIMEOUT_SECONDS=60
```

### 2. Start Ollama and pull a model

```bash
make up-ollama
make pull-local-model     # pulls OLLAMA_MODEL (default: llama3.2)
```

### 3. Restart the API

```bash
docker compose restart api worker
```

The startup probe will log `INFO: local LLM reachable at http://ollama:11434/v1` if the connection succeeds, or `WARNING: local LLM not reachable` if it does not (startup still completes — the probe is non-fatal).

### 4. Enable the feature flag

```env
FEATURE_ENABLE_LOCAL_LLM_PROFILES=true
```

Without this flag, the model profile UI is hidden from admins and `PUT /model-profiles/chat` returns a 422 policy violation for `local_llm_disabled`.

---

## Environment variables

### Chat (generation) provider

| Variable | Default | Description |
|---|---|---|
| `LLM_DEFAULT_PROVIDER` | `openai` | Set to `local` to route all generation through the local endpoint. |
| `LOCAL_LLM_BASE_URL` | _(none)_ | Base URL of the OpenAI-compatible server, e.g. `http://ollama:11434/v1`. Required when `LLM_DEFAULT_PROVIDER=local`. |
| `LOCAL_LLM_MODEL` | _(empty)_ | Model name to pass in the `model` field of chat completion requests. |
| `LOCAL_LLM_PROVIDER_KIND` | `generic` | Provider hint for logging and diagnostics. Use `ollama`, `vllm`, `litellm`, or `generic`. |
| `LOCAL_LLM_TIMEOUT_SECONDS` | `30` | Request timeout. Increase to 120+ for large models or long prompts. |
| `LOCAL_LLM_JSON_MODE_ENABLED` | `true` | Set to `false` for providers that do not support `response_format=json_object` (Ollama, LocalAI). |
| `LOCAL_LLM_API_KEY` | _(empty)_ | API key for gateway authentication. Optional — defaults to `not-required` when unset. Never commit real keys. |

### Embedding provider

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_DEFAULT_PROVIDER` | `openai` | Set to `local` to route embeddings through the local endpoint. |
| `LOCAL_EMBEDDING_BASE_URL` | _(none)_ | Base URL with `/v1/embeddings` support. Required when `EMBEDDING_DEFAULT_PROVIDER=local`. |
| `LOCAL_EMBEDDING_MODEL` | _(empty)_ | Embedding model name. Required when `EMBEDDING_DEFAULT_PROVIDER=local`. |
| `LOCAL_EMBEDDING_TIMEOUT_SECONDS` | `30` | Request timeout for embedding calls. |
| `LOCAL_EMBEDDING_API_KEY` | _(empty)_ | API key for gateway authentication. Optional. Never commit real keys. |

### Feature flags

| Variable | Default | Description |
|---|---|---|
| `FEATURE_ENABLE_LOCAL_LLM_PROFILES` | `false` | Enables local provider in model profile UI and API validation. |
| `FEATURE_ENABLE_LOCAL_EMBEDDING_PROFILES` | `false` | Enables local provider for embedding task profiles. |
| `FEATURE_ENABLE_PROVIDER_FALLBACK` | `false` | Enables cloud fallback when local provider fails. See [Security](#security-and-privacy). |

### Container image and resource limits

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_IMAGE` | `ollama/ollama:latest` | Ollama container image tag. |
| `OLLAMA_MODEL` | `llama3.2` | Model pulled by `make pull-local-model`. |
| `OLLAMA_MEMORY_LIMIT` | `8g` | Docker memory limit for the Ollama container. |
| `VLLM_IMAGE` | `vllm/vllm-openai:latest` | vLLM container image tag. |
| `VLLM_MODEL` | `mistralai/Mistral-7B-v0.1` | Model served by vLLM (passed as `--model` arg). |
| `VLLM_MAX_MODEL_LEN` | `4096` | Maximum context length. |
| `VLLM_MEMORY_LIMIT` | `16g` | Docker memory limit for the vLLM container. |
| `VLLM_HF_TOKEN` | _(empty)_ | HuggingFace token for gated models. Never commit. |
| `VLLM_GPU_COUNT` | `1` | GPU count (GPU pass-through must be uncommented in `docker-compose.yml`). |
| `LITELLM_IMAGE` | `ghcr.io/berriai/litellm:main-latest` | LiteLLM container image. |
| `LITELLM_MEMORY_LIMIT` | `2g` | Docker memory limit for LiteLLM. |
| `LITELLM_LOG_LEVEL` | `WARNING` | LiteLLM log verbosity. |
| `LITELLM_MASTER_KEY` | `sk-local-dev-change-me` | Gateway API key. Rotate before sharing with team. Never commit real keys. |

---

## Docker Compose profiles

Local model services are declared as Docker Compose named profiles. They are **not started by `docker compose up`** unless explicitly requested. This keeps the default stack lightweight.

```
┌────────────┬──────────────────┬───────────────────────────────┐
│ Profile    │ Make target      │ Rudix env vars                │
├────────────┼──────────────────┼───────────────────────────────┤
│ ollama     │ make up-ollama   │ LOCAL_LLM_BASE_URL=           │
│            │                  │   http://ollama:11434/v1      │
├────────────┼──────────────────┼───────────────────────────────┤
│ vllm       │ make up-vllm     │ LOCAL_LLM_BASE_URL=           │
│            │                  │   http://vllm:8000/v1         │
├────────────┼──────────────────┼───────────────────────────────┤
│ litellm    │ make up-litellm  │ LOCAL_LLM_BASE_URL=           │
│            │                  │   http://litellm:4000         │
└────────────┴──────────────────┴───────────────────────────────┘
```

Local services bind to the **internal Docker network only** — no host ports are exposed by default. If you need to reach Ollama from outside Docker, add a `ports:` entry in `docker-compose.yml` or use `docker compose exec ollama ...` directly.

### Useful commands

```bash
make up-ollama             # Start Ollama profile
make up-vllm               # Start vLLM profile
make up-litellm            # Start LiteLLM gateway
make down-local-llm        # Stop all local model containers
make logs-local-llm        # Tail logs from all local model containers
make pull-local-model      # Pull OLLAMA_MODEL inside running Ollama container
make benchmark-local-model # Run quality benchmark suites (requires running API)
```

### GPU pass-through (vLLM)

To enable GPU access for vLLM, uncomment the `reservations.devices` block in `docker-compose.yml` under the `vllm` service and set `VLLM_GPU_COUNT` in your `.env`. The host must have the NVIDIA Container Toolkit installed.

### LiteLLM gateway

`infra/litellm/config.yaml` is mounted read-only into the LiteLLM container. It defines model routes for Ollama and vLLM using internal Docker hostnames. To add routes, edit that file and restart:

```bash
docker compose --profile litellm restart litellm
```

Never store real API keys in `config.yaml`. Use environment-variable references (`os.environ/MY_VAR`) or the `LITELLM_MASTER_KEY` env var instead.

---

## Model profiles

Model profiles (F220) allow per-task provider and model configuration. They take precedence over env defaults and are set via the admin UI at `/admin/model-profiles` or the API.

### Task types

| Task type | Default use | Notes |
|---|---|---|
| `chat` | Question answering in ChatPage | Most critical — warm path |
| `summarization` | Document summary generation | Can tolerate higher latency |
| `comparison` | Side-by-side run comparison | Requires `json_mode=true` |
| `embeddings` | Query and ingestion embeddings | Affects vector dimension — see [FAQ](#faq) |
| `evaluations` | RAGAS evaluation scoring | Requires `json_mode=true` |
| `agentic` | Agent run generation | Experimental |

### Configuration precedence

```
env_default  →  org_profile  →  request_override (requires feature flag)
(lowest)                         (highest)
```

The admin UI shows the resolved effective policy for all tasks at `GET /model-profiles/effective`.

### Setting a local model profile via API

```bash
curl -X PUT http://localhost:8000/api/v1/model-profiles/chat \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_type": "local",
    "base_model": "llama3.2",
    "context_window": 8192,
    "max_tokens": 1024,
    "temperature": 0.1,
    "json_mode": false,
    "streaming": false
  }'
```

The API validates the profile before persisting. Policy violations (e.g. `local_llm_disabled` when `FEATURE_ENABLE_LOCAL_LLM_PROFILES=false`) return 422 with details.

---

## Provider routing and fallback

When a model profile is set with `fallback_provider_key`, and `FEATURE_ENABLE_PROVIDER_FALLBACK=true`, the system will retry on the fallback provider if the primary fails.

### Fallback behavior

- Fallback triggers on **transient errors only**: timeout, service unavailable, quota exceeded, internal server error.
- **Permanent errors do not fall back** (e.g. invalid API key, model not found, 400 Bad Request).
- Fallback uses the fallback provider's own configured model — not the primary's model name.
- When fallback is used, a warning banner is shown to the user in ChatPage.
- The `fallback_used`, `fallback_from`, and `fallback_to` fields appear in the debug panel (admin only) and in Langfuse traces.

### Disabling fallback for privacy

If your deployment must never send document context to a cloud provider, set:

```env
FEATURE_ENABLE_PROVIDER_FALLBACK=false
```

Or use governance controls (see [Security and privacy](#security-and-privacy)) to enforce `local_only_mode`.

---

## Security and privacy

### Cloud fallback is a privacy boundary

When `FEATURE_ENABLE_PROVIDER_FALLBACK=true` and a cloud provider is configured as fallback, the full RAG prompt — including retrieved private document chunks — is sent to the cloud provider on fallback. **This must be explicitly approved before enabling in production.**

The governance settings (admin only, at `PATCH /api/v1/admin/governance`) require acknowledgment (`cloud_fallback_warning_acknowledged: true`) before the flag can be saved.

### Governance controls

All governance settings are available in the admin UI under **Settings → Provider Security**.

| Setting | Effect |
|---|---|
| `local_only_mode` | When `true`, any profile configured with a cloud provider key is blocked by `check_provider_governance()`. Cloud fallback is also blocked regardless of other settings. |
| `cloud_fallback_allowed` | When `false`, fallback to cloud is blocked even if `FEATURE_ENABLE_PROVIDER_FALLBACK=true`. |
| `allowed_provider_profiles` | Allowlist of provider profile keys. If non-empty, only listed profiles are permitted. |
| `admin_only_model_selection` | When `true` (default), only admins and owners can change model profiles. |
| `retention_warning_acknowledged` | Must be `true` before enabling `cloud_fallback_allowed`. Saved to database. |

### Local provider security

Local model endpoints and their logs are sensitive production infrastructure:

- Run local model services **inside the internal Docker network** — do not bind host ports in production.
- Model logs may contain prompt text and retrieved document context. Restrict access to these logs as you would any production secret.
- Rotate `LITELLM_MASTER_KEY` before sharing configuration with team members. Never commit real keys.
- If `LOCAL_LLM_API_KEY` is required by your gateway, inject it as an env var — never store it in source control.
- Treat `VLLM_HF_TOKEN` as a secret; it grants access to gated HuggingFace repositories.

### Provider audit trail

Every model profile change is recorded in `org_model_profile_change_log` (immutable). Provider test connections (from the diagnostics page) are recorded in audit events. Governance policy changes are also audited.

---

## Admin diagnostics

The model diagnostics page (`/admin/model-diagnostics`) shows per-provider health cards and capability badges. Use the **Test connection** button to probe each configured provider without sending user data.

```
GET /api/v1/admin/model-diagnostics
Authorization: Bearer <admin token>
```

The test-connection probe is rate-limited and only sends safe, static payloads — no document content or user prompts are used.

---

## Evaluation and release gates

Before promoting a local model to default, run the benchmark suites to compare quality against the cloud baseline.

### Benchmark suites

| Suite ID | What it tests |
|---|---|
| `qa_basic` | General question answering, retrieval hit rate, relevance |
| `not_found` | Not-found detection rate (when no grounding exists) |
| `citation_strictness` | Citation accuracy and faithfulness |
| `multilingual` | Cross-language retrieval and answer quality |
| `long_context` | Behaviour with large documents / long prompts |
| `prompt_injection` | Robustness to adversarial inputs in documents |

### Release gate thresholds

| Metric | Minimum / Maximum |
|---|---|
| `retrieval_hit_rate` | ≥ 0.70 |
| `citation_accuracy_score` | ≥ 0.75 |
| `faithfulness_score` | ≥ 0.70 |
| `answer_relevance_score` | ≥ 0.70 |
| `not_found_rate` | ≤ 0.20 |
| `invalid_json_rate` | ≤ 0.05 |
| `timeout_rate` | ≤ 0.10 |
| `fallback_frequency` | ≤ 0.15 |

The cloud baseline profile is **never** evaluated against release gates — only local and fallback profiles are checked.

### Running benchmarks

```bash
# Via make (requires running API and exported env vars)
export RUDIX_API_BASE_URL=http://localhost:8000/api/v1
export RUDIX_API_TOKEN=<admin token>
make benchmark-local-model
```

Exit codes: `0` = all gates pass, `1` = one or more gates fail, `2` = API error.

The comparison report is also available from the admin UI at the **Evaluations → Model Profile Comparison** panel.

### Triggering individual suite runs via API

```bash
curl -X POST http://localhost:8000/api/v1/evaluations/benchmark-suites/qa_basic/run \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"provider_profile": "local_profile"}'
```

---

## Provider observability

The admin observability page (`/admin/observability`) includes a **Provider Health** section showing per-provider cards with:

- Health badge (healthy / degraded / unavailable)
- Average and p95 latency
- Error rate, timeout rate, fallback frequency
- SLO suggestions when thresholds are exceeded

```
GET /api/v1/admin/provider-observability?start_date=2026-06-01&end_date=2026-06-14
Authorization: Bearer <admin token>
```

SLO suggestion triggers:

| Signal | Threshold |
|---|---|
| Failure rate | > 5% |
| Timeout rate | > 2% |
| Fallback frequency | > 10% |
| Average latency | > 5 s |
| p95 latency | > 10 s |

---

## Rollout checklist

Follow this sequence when introducing local models to an environment.

### Phase 1 — Read-only diagnostics

- [ ] Start the local model container (`make up-ollama` / `make up-vllm` / `make up-litellm`)
- [ ] Pull a model (`make pull-local-model`)
- [ ] Verify startup probe in API logs: `INFO: local LLM reachable`
- [ ] Open `/admin/model-diagnostics` and run **Test connection** for the local provider
- [ ] Confirm provider card shows correct model name and response latency
- [ ] Review governance settings at `/admin/settings` → Provider Security — confirm `local_only_mode` and `cloud_fallback_allowed` match your policy

### Phase 2 — Run evaluations

- [ ] Ensure `FEATURE_ENABLE_LOCAL_LLM_PROFILES=true` in `.env`
- [ ] Set `local` profile for the `chat` task type via model profiles API or admin UI
- [ ] Trigger benchmark suites: `make benchmark-local-model`
- [ ] Review the Model Profile Comparison panel — verify all release gates pass
- [ ] Pay special attention to `invalid_json_rate` (set `LOCAL_LLM_JSON_MODE_ENABLED=false` for Ollama if non-zero)
- [ ] Check `timeout_rate` — increase `LOCAL_LLM_TIMEOUT_SECONDS` if needed

### Phase 3 — Enable for internal org

- [ ] In the admin UI, set `admin_only_model_selection=true` so only admins can switch profiles
- [ ] Create or update the `chat` model profile for your internal org with `provider_type=local`
- [ ] Run a set of representative chat queries through the UI — observe confidence scores and citations
- [ ] Watch `/admin/provider-observability` for latency and error rates
- [ ] Check Langfuse (if enabled) for fallback_used flags and provider spans

### Phase 4 — Monitor and validate

- [ ] Monitor for 24 hours (or a representative traffic sample) using the observability dashboard
- [ ] Confirm error rate < 5%, timeout rate < 2%, fallback frequency < 10% (or 0% if `FEATURE_ENABLE_PROVIDER_FALLBACK=false`)
- [ ] Compare confidence scores and not_found rates against the cloud baseline period
- [ ] Review any SLO suggestions that appear on provider cards
- [ ] Verify model logs are not accessible from outside the Docker network

### Phase 5 — Promote to default

- [ ] Set `LLM_DEFAULT_PROVIDER=local` in production `.env`
- [ ] Restart API and worker with `docker compose restart api worker`
- [ ] Confirm startup probe logs show local provider reachable
- [ ] Re-run benchmark suites against production env
- [ ] Update on-call runbook with local provider details and contact for GPU infra

---

## Runbooks

### Provider unavailable

**Symptoms:** API returns 503 or chat returns an error banner. Startup log shows `WARNING: local LLM not reachable`. Provider health card shows `unavailable`.

**Steps:**
1. Check container status: `make ps` — verify the local model service is running.
2. Check logs: `make logs-local-llm` — look for OOM kills, port conflicts, or model load errors.
3. Test connectivity from inside the API container:
   ```bash
   docker compose exec api curl -sf http://ollama:11434/v1/models
   ```
4. Verify `LOCAL_LLM_BASE_URL` in `.env` matches the container's internal hostname and port.
5. If the container OOM-killed, increase `OLLAMA_MEMORY_LIMIT` / `VLLM_MEMORY_LIMIT` in `.env` and restart.
6. If provider cannot be recovered, temporarily set `LLM_DEFAULT_PROVIDER=openai` and restart to restore service.

### Model too slow / timeouts

**Symptoms:** Answers eventually appear but timeout errors appear in logs. `timeout_rate` rises on the observability dashboard. Users see delayed responses.

**Steps:**
1. Check model size vs. available memory. Quantized models (e.g. `llama3.2:3b` instead of `llama3.2:70b`) are significantly faster.
2. Increase `LOCAL_LLM_TIMEOUT_SECONDS` in `.env` (max 300) and restart API.
3. Check if GPU pass-through is configured for vLLM — CPU inference is 10–50x slower than GPU.
4. For Ollama, pull a smaller variant: set `OLLAMA_MODEL=llama3.2:1b` and `make pull-local-model`.
5. If using LiteLLM, check the gateway logs for upstream latency (`make logs-local-llm`).
6. Consider increasing `context_window` in the model profile if long prompts are being truncated and retried.

### Invalid JSON responses

**Symptoms:** Evaluation metrics show high `invalid_json_rate`. Answer parsing errors in API logs. Citations missing from some answers.

**Steps:**
1. Set `LOCAL_LLM_JSON_MODE_ENABLED=false` in `.env`. Ollama and many local providers do not support `response_format=json_object`. Rudix's prompt already requests JSON output — the API-level parameter is not needed.
2. Restart API: `docker compose restart api`.
3. Re-run the `qa_basic` and `citation_strictness` benchmark suites to verify the rate drops.
4. If rate remains high, consider switching to a model with stronger instruction following (e.g. `llama3.2` over smaller variants, or `mistral-7b-instruct`).
5. For the `evaluations` and `comparison` task types, `json_mode=true` is **required** by policy — these tasks always need a model that supports structured output. Keep a cloud or capable local model for these tasks if your primary model does not support it.

### Embedding dimension mismatch

**Symptoms:** Ingestion or query fails with a vector dimension error. Qdrant returns 400. New documents index but are not retrieved.

**Cause:** The embedding model was changed after documents were already indexed. The existing vectors in Qdrant use a different dimension than the new model produces.

**Steps:**
1. Identify the old and new embedding dimensions by checking `LOCAL_EMBEDDING_MODEL` before and after the change.
2. **Do not mix models** — all documents in a collection must use the same embedding dimension.
3. To switch embedding models safely:
   a. Delete the existing Qdrant collection (or rename it).
   b. Re-index all documents: trigger a full reindex via the admin API or worker task.
   c. Confirm the new dimension in the Qdrant collection settings before re-enabling chat.
4. If you need to keep old embeddings temporarily, configure a second Qdrant collection and route new ingestion there while the reindex completes.
5. After switching, update monitoring to alert on dimension mismatch errors (look for `Qdrant 400` in structured logs).

### Fallback disabled / CloudFallbackDisabledError

**Symptoms:** Chat returns an error when the local provider fails and `FEATURE_ENABLE_PROVIDER_FALLBACK=false`. Logs show `CloudFallbackDisabledError`.

**Steps:**
1. This is the expected behavior when fallback is intentionally disabled for privacy.
2. To restore service, either:
   - Fix the local provider (see [Provider unavailable](#provider-unavailable) runbook), or
   - Temporarily set `LLM_DEFAULT_PROVIDER=openai` and restart (this routes all requests to cloud — review privacy implications first), or
   - Enable fallback: set `FEATURE_ENABLE_PROVIDER_FALLBACK=true`, acknowledge the cloud fallback warning in governance settings, and restart.
3. If `local_only_mode=true` in governance, fallback cannot be enabled without an admin governance change. Contact your security team before changing this setting in production.

### Re-index required

**Symptoms:** Vector search quality degrades after an embedding model change. Retrieval hit rate drops in benchmarks. Documents uploaded before the change return poor results.

**Steps:**
1. Confirm the current `LOCAL_EMBEDDING_MODEL` value: `GET /api/v1/admin/model-profiles/embeddings`.
2. Trigger a full reindex from the admin worker task or via the admin API. This re-embeds all existing document chunks using the current model.
3. Monitor the reindex task in the failed jobs dashboard (`/admin/failed-jobs`) for errors.
4. After reindex completes, run the `qa_basic` benchmark suite to confirm retrieval hit rate recovers.
5. Avoid changing embedding models on a live production system during peak hours — schedule reindex during low-traffic windows.

---

## FAQ

### What is the difference between local generation and local embeddings?

**Local generation** (`LLM_DEFAULT_PROVIDER=local`) routes the final answer-generation step to a local model. This is what users interact with directly — the quality and style of answers changes when you switch generation models.

**Local embeddings** (`EMBEDDING_DEFAULT_PROVIDER=local`) routes the embedding step to a local model. This affects how documents and queries are represented as vectors. Switching embedding models requires a full reindex of all documents because existing vectors in Qdrant become incompatible.

You can run generation locally and embeddings on OpenAI (or vice versa). The two providers are configured independently.

### What happens to existing vectors if I change the embedding model?

Existing Qdrant vectors become invalid because the new model produces embeddings in a different dimensional space. Cosine similarity comparisons between old and new vectors are meaningless, so retrieval will degrade silently — documents indexed with the old model will not match queries embedded with the new model.

Always plan a full reindex when switching embedding models. The reindex process re-embeds every document chunk using the new model. Do not enable the new embedding model in production until the reindex is complete.

### Does cloud fallback transmit private document content to an external provider?

Yes. When cloud fallback triggers, the full RAG prompt is sent to the cloud provider. This prompt includes the retrieved document chunks — the private content you chose to keep on-premises.

Before enabling `FEATURE_ENABLE_PROVIDER_FALLBACK=true` with a cloud fallback key:
- Review your data privacy requirements and legal obligations.
- Get explicit approval from your security and compliance teams.
- Acknowledge the risk in the governance settings (`retention_warning_acknowledged: true`, `cloud_fallback_allowed: true`).
- Consider setting `local_only_mode=true` in governance to make it impossible to accidentally route to cloud.

If you cannot accept any risk of cloud transmission, disable fallback entirely (`FEATURE_ENABLE_PROVIDER_FALLBACK=false`) and monitor the local provider's availability proactively.

### What are the GPU and memory requirements?

Requirements depend on the model you choose:

| Model | Minimum RAM | Recommended RAM | GPU |
|---|---|---|---|
| `llama3.2:1b` | 2 GB | 4 GB | Optional (CPU works) |
| `llama3.2` (3B) | 4 GB | 8 GB | Strongly recommended |
| `llama3.2:70b` | 40 GB | 80 GB | Required (A100 or equivalent) |
| `mistral-7b` | 8 GB | 16 GB | Strongly recommended |
| Embedding models | 1–4 GB | 4 GB | Optional |

For CPU-only inference, expect 5–60 seconds per answer depending on model size and prompt length. GPU inference is typically 10–50x faster.

For production use, GPU-based inference is strongly recommended. For vLLM, uncomment the `reservations.devices` block in `docker-compose.yml` and ensure the NVIDIA Container Toolkit is installed on the host.

### Can I use a remote OpenAI-compatible API that is not running on this server?

Yes. Set `LOCAL_LLM_BASE_URL` to any reachable OpenAI-compatible endpoint — it does not have to be on the same host. The `local` provider kind is a naming convention, not a network locality constraint.

For example, to use a privately hosted vLLM cluster:

```env
LLM_DEFAULT_PROVIDER=local
LOCAL_LLM_BASE_URL=https://vllm.internal.yourcompany.com/v1
LOCAL_LLM_API_KEY=your-gateway-key
LOCAL_LLM_MODEL=meta-llama/Llama-3.1-8B-Instruct
LOCAL_LLM_PROVIDER_KIND=vllm
```

Treat the `LOCAL_LLM_API_KEY` as a production secret — rotate it regularly and never commit it to version control.
