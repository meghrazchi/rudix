# v0.5.0 — Chat Pipeline and Streaming

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../03_RAG_WORKFLOW.md](../03_RAG_WORKFLOW.md), [../07_API_DESIGN.md](../07_API_DESIGN.md)

## 1. Purpose

Replace the two diverging 1,400 to 2,300 line chat pipelines with one staged pipeline, stream
tokens as they are generated, bound latency and cost, and rebuild the chat UI so streaming is
cheap to render.

## 2. Target design

```text
HTTP adapter ─┐
WS adapter  ──┼─> ChatPipeline.run(request, emitter) ─> events
SSE adapter ─┘

Stages (app/application/chat/stages/):
  1 authorize      quota, scope, document access
  2 resolve_config policy, RAG profile, model profile (cached, R04-05)
  3 guard          prompt-injection check on the question
  4 shortcut       verified-answer match (skip retrieval and generation on a hit)
  5 rewrite        optional query rewriting and decomposition
  6 retrieve       vector, keyword, graph in parallel
  7 rerank_pack    rerank, context packing, source conflict detection
  8 generate       streamed generation
  9 verify         citation validation, grounded verifier, refiner
 10 persist        message, citations, trust metadata, usage (one short transaction)
```

- Each stage is a class with `async def run(ctx) -> ctx`, its own timeout, and its own file.
- Adapters translate transport only. They contain no business logic.
- The pipeline emits typed events through an `emitter`. The WebSocket adapter forwards them,
  the SSE adapter serialises them, and the plain HTTP adapter collects them into one response.

## 3. Work items

### R05-01 — Single pipeline (L)

- **Change:** Build `ChatPipeline` and the stages above by extracting from `query_chat`.
  Move confidence, intent inference, and trust-metadata assembly (`chat.py:1725-2646`) into
  `app/domains/chat/services/`. Switch the HTTP path first, then WebSocket, each behind
  `CHAT_PIPELINE_V2` (default off in the first merge, on by the end of the version). Delete
  both old functions when parity holds.
- **Safety net:** Before extraction, record golden transcripts (question, retrieved chunk
  IDs, citations, confidence, trust metadata) through the old code with a stubbed provider.
  The new pipeline must reproduce them.
- **Done when:** `chat.py` contains only route definitions and is under 500 lines, and the
  parity test from `R02-01` passes against one implementation.

### R05-02 — Short database sessions (M)

- **Change:** Stages 1, 2, and 4 share one read session that is closed before stage 5.
  Stages 5 to 9 hold no connection. Stage 10 opens a new session and commits once.
  Retrieval branches each use their own session (`R02-06`).
- **Done when:** A test asserts zero checked-out connections while the stubbed model is
  "generating", and the load test holds 200 concurrent streams on one replica.

### R05-03 — Real token streaming (L)

- **Change:**
  - Add `stream_answer()` to the provider interface. Implement it for OpenAI and for the
    OpenAI-compatible adapter. Providers without streaming fall back to one chunk.
  - Events: `generation.delta` (incremental text), `generation.final` (authoritative answer,
    citations, confidence), and `generation.replace` when verification or policy changes text
    that was already streamed. Existing clients that treat one `delta` as the full answer keep
    working because `generation.final` carries the full text.
  - Add `POST /api/v1/chat/query/stream` returning Server-Sent Events for clients that cannot
    use WebSockets.
  - Client disconnect cancels the provider call and records partial usage.
- **Policy note:** In strict verification mode the answer may be withheld. For strict mode,
  buffer until verification completes and stream the verified text.
- **Done when:** Time to first token is measured as a metric and meets the target, and
  `docs/07_API_DESIGN.md` documents the event protocol.

### R05-04 — Latency budget and parallelism (M)

- **Change:**
  - `CHAT_TOTAL_DEADLINE_MS` and per-stage budgets. The context carries a deadline. A stage
    that would exceed it is skipped or degraded according to a per-stage policy, and the
    skip is recorded in trust metadata (no silent degradation).
  - Run rerank batches concurrently with a semaphore.
  - Run stages with no data dependency concurrently. Determine the dependency graph during
    extraction; at minimum, query-embedding and configuration resolution can overlap.
- **Done when:** p95 full-answer latency meets the target with rewriting and reranking on.

### R05-05 — Caches on the query path (M)

- **Change:**
  - Query-embedding cache in Redis keyed by model and normalised text hash.
  - Verified-answer shortcut (F255) as stage 4. Confirm how the existing match service is
    wired today before building; the audit found no reference to it in `chat.py`.
  - Do **not** add a semantic answer cache in this version. It is permission-sensitive and
    is listed as a post-1.0 candidate.
- **Done when:** Repeated questions skip the embedding call, and a verified-answer hit
  returns without any generation call.

### R05-06 — Provider resilience (M)

- **Change:** Add a circuit breaker per provider and model, a per-organisation concurrency
  limit (Redis semaphore) so one tenant cannot exhaust provider rate limits, and prompt
  caching for the static system prompt where the provider supports it.
- **Done when:** A fault-injection test shows the breaker opening and fallback engaging.

### R05-07 — Complete cost accounting (S)

- **Change:** Every LLM call in the pipeline reports tokens to a per-request ledger. The
  usage event stores totals and a per-stage breakdown. Quota uses the total.
- **Done when:** A test with all stages enabled asserts the usage event equals the sum of the
  stubbed calls.

### R05-08 — Profile-based model routing for auxiliary stages (S)

- **Change:** Rewrite, rerank, conflict detection, verifier, and refiner resolve their model
  from model profiles (F220) instead of `settings.openai_llm_model`.
- **Done when:** With a local default provider, no stage calls an OpenAI model name.

### R05-09 — Prompt-injection hardening (M)

- **Change:**
  - Wrap retrieved chunks in explicit delimiters with per-request random boundaries.
  - Add the untrusted-context rule to every auxiliary prompt template.
  - Scan retrieved chunks with `PromptInjectionGuard` and down-rank or flag matches.
  - Extend the safety evaluation set (F146) with injection cases for each auxiliary stage.
- **Done when:** The new safety cases pass in CI. Update
  `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md`.

### R05-10 — Split the chat page (L)

- **Change:** Break `ChatPage.tsx` (one 4,300-line function) into a route shell plus
  `ChatThread`, `ChatComposer`, `ChatSidebar`, `ScopeControls`, `StreamingMessage`, and
  hooks (`useChatSession`, `useChatSettings`, `useChatStream`). No file over 500 lines.
  Split `AnswerTrustPanel.tsx` by section and load it lazily.
- **Done when:** Existing chat tests pass unchanged, and the skipped submit test in
  `ChatPage.msw.test.tsx` is restored.

### R05-11 — Cheap streaming render (M)

- **Change:**
  - Keep streamed text in a ref-backed store and flush to state once per animation frame.
    Only `StreamingMessage` subscribes.
  - Memoise completed messages.
  - Virtualise the thread with `@tanstack/react-virtual` (already installed).
  - Load history with cursor pagination (`R04-04`), newest page first.
  - Scroll only when the user is at the bottom, without smooth scrolling per token.
- **Done when:** A React Profiler test shows only the streaming message commits during a
  stream, and a 2,000-message session scrolls without dropped frames.

### R05-12 — Rich answer rendering (M, needs approval)

- **Change:** Render answers as sanitised Markdown with tables, lists, and code blocks.
  Raw HTML is disabled. Citation markers stay interactive.
- **Fallback:** Keep plain text.

### R05-13 — Resilient chat connection (M)

- **Change:** Reconnect with exponential backoff and jitter. On reconnect, resume by
  `message_id` and last received sequence number; the server replays from a short Redis
  buffer or returns the final message if generation finished. Use the ticket flow from
  `R02-10` and set `CHAT_WS_ALLOW_QUERY_TOKEN=false` by default. Namespace
  `rudix.chat.settings.v1` by user and organisation.
- **Done when:** A Playwright test drops the socket mid-stream and the answer completes.

## 4. Exit criteria

- One pipeline, both old functions deleted, golden transcripts match.
- Time to first token and full-answer p95 meet the master-plan targets under load.
- Database queries per chat request are 12 or fewer.
- Accuracy gates pass with no regression against `0.4.0`.
- `RLS_ENFORCEMENT=strict` is the default.

## 5. Failure Modes and Recovery

| Failure | Recovery |
|---|---|
| New pipeline changes answers | `CHAT_PIPELINE_V2=false` restores the old path until deletion |
| Streamed text later fails verification | `generation.replace`; strict mode buffers |
| Provider stream stalls | Per-stage timeout, breaker, fallback provider |
| Reconnect replays duplicate tokens | Sequence numbers; client discards already-seen deltas |

## 6. Security Considerations

Authorization runs in stage 1 for every transport, so no adapter can bypass it. The streaming
endpoints apply the same quota and rate limits as the non-streaming one. Resume buffers are
keyed by user and session and expire in minutes.

## 7. Observability and Operations

Metrics: `rudix_chat_stage_seconds{stage}`, `rudix_chat_ttft_seconds`,
`rudix_chat_stage_skipped_total{stage,reason}`, `rudix_llm_breaker_state`,
`rudix_chat_tokens_total{stage}`. Add a Grafana chat dashboard and a time-to-first-token
alert.

## 8. Change Notes

- 2026-11-26: Initial version.
