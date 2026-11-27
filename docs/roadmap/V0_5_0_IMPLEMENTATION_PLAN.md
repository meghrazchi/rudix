# v0.5.0 — Detailed Implementation Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Planned
- `Last Updated`: 2026-11-27
- `Related Docs`: [V0_5_0_CHAT_PIPELINE_AND_STREAMING.md](./V0_5_0_CHAT_PIPELINE_AND_STREAMING.md),
  [V0_4_0_IMPLEMENTATION_PLAN.md](./V0_4_0_IMPLEMENTATION_PLAN.md),
  [01_EXECUTION_PLAN.md](./01_EXECUTION_PLAN.md),
  [../03_RAG_WORKFLOW.md](../03_RAG_WORKFLOW.md), [../07_API_DESIGN.md](../07_API_DESIGN.md),
  [../22_AUTHORIZATION_SYSTEM.md](../22_AUTHORIZATION_SYSTEM.md)

## 1. Purpose

Turn the `0.5.0` spec into nine work packages with exact files, symbols, tests, and owners of
shared files. Every reference was read on `develop` at `21bdb6a` (`0.2.0` to `0.4.0` merged,
not tagged). Line numbers drift; search for the quoted symbol.

Evidence rule: there is no load test, no real provider, and no Redis here. Latency and
concurrency claims rest on statement counts, session-lifetime and pool-checkout assertions,
event-order tests, and tests with the stub provider plus artificial latency. No latency figure
is written down.

## 2. Plan check: what the code confirmed or changed

| Item | Result |
|---|---|
| R05-01 | **Changed.** `chat.py` is 7,998 lines: `query_chat` (2,204 lines), `_run_ws_chat_pipeline` (1,438), helpers at lines 290–2673 (not only 1725–2646), and 26 other routes. The transports diverge: the WebSocket path has no query rewriting, context packing, grounded verifier (so strict-mode refusals do not apply on WebSocket), tree search, freshness, OCR, table, or extraction-quality handling; it resolves the prompt template whenever `scope_mode != "none"`; it emits the planner, routing, and tool-orchestration steps before they are computed (they are never sent); and its event `sequence` collides with the connection counter. A third caller exists: `bot_service.py` calls `chat_api.query_chat(...)` with a fake request. Tests rebind module globals of `chat.py` (`_openai_client` in F144 and the accuracy smoke, `SessionLocal` and `ensure_chat_quota` in the parity test, `authenticate_ws_handshake` and `_run_ws_chat_pipeline`), and call `_run_ws_chat_pipeline(websocket, payload, principal, request_id, sequence_start)` directly. **Resolution:** the pipeline reproduces the HTTP semantics; the WebSocket converges in S2 with a reviewed golden diff; `chat.py` keeps a small compatibility surface (contract 4.2.2) and stays under 500 lines with routes split into sibling modules. |
| R05-02 | Confirmed: HTTP uses the request session for the whole request; WebSocket holds one `SessionLocal()` across the LLM call. `ParallelRetrievalOptimizer` already opens per-branch sessions from `SessionLocal` for concurrent keyword branches; the graph branch reuses the caller session. `SessionLocal` has `expire_on_commit=False`, so ending the read phase with `commit()` keeps loaded values. New chat sessions are created at stage 1 today; they move to stage 10 with pre-assigned UUIDs. |
| R05-03 | **Changed.** The model answers in JSON (`answer`, `not_found`, `citations`), so token streaming needs an incremental extractor of the `answer` string. The existing terminal event is `chat.completed`; `generation.final` and `generation.replace` are added before it. The stub `ci/stubs/llm_stub.py` already serves `stream: true`. R05-03 says disconnect cancels; R05-13 wants resume after a drop: WebSocket runs get a grace window (A2), SSE cancels at once. |
| R05-04 | Confirmed: no deadline exists; rerank batches run sequentially. The stage runner (S1) carries the deadline and per-stage timeout hooks with defaults off; B2 sets the policies. |
| R05-05 | **Changed.** The verified-answer match (`VerifiedAnswerRepository.find_published_match`, `ILIKE %question%`) is only used by `GET /verified-answers/search/match` for UI suggestions; nothing in the chat path calls it. It is too loose to skip generation. Stage 4 uses an exact normalised match, checks citation permissions, and is off by default (`CHAT_VERIFIED_ANSWER_SHORTCUT_ENABLED`). `CACHE_TTL_POLICIES_SECONDS` and `CACHE_TTL_PROFILES_SECONDS` already exist for the deferred namespaces. |
| R05-06 | **Changed.** The configured providers (OpenAI, OpenAI-compatible) have no explicit prompt-cache API; OpenAI caches long prefixes automatically. The answer template inserts dynamic text (`strategy_instruction`, `conflict_context`, language rule) inside the static prefix, but templates are versioned and org-editable, so reordering is a behaviour change. This version records cached prompt tokens only. The breaker wraps providers in the factory and in `LLMService`. |
| R05-07 | Confirmed: the usage event counts only embedding and generation tokens. `QuotaType.tokens` exists but chat never records it. A per-stage breakdown goes into `usage_events.metadata_json`; no migration. |
| R05-08 | Confirmed: `settings.openai_llm_model` in `query_rewriting_service.py`, `rerank_service.py`, `conflict_detection_service.py`, `grounded_answer_verifier.py`, `answer_refiner_service.py`. **Changed:** auxiliary calls use the resolved `chat` profile (no new `TaskType`); query embeddings stay on the index's embedding model. |
| R05-09 | Confirmed: the default answer template already has untrusted rules and question delimiters; context blocks have none. The accuracy smoke's fake LLM parses the block format (`[n]`, `key=value`, `text:`), so B1 may update that parser only. |
| R05-10 | **Changed.** `ChatPage.tsx` is 5,521 lines (spec: 4,300); `ChatComposer.tsx` already exists at 533 lines and is split too; `AnswerTrustPanel.tsx` is 2,060 lines. The skipped test is `ChatPage.msw.test.tsx` "submits a new question and renders the successful response". |
| R05-11 | **Changed.** `GET /chat/sessions/{id}/messages` pages ascending only; newest-first needs an additive `order=desc`. Playwright runs one dev server with `NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED` unset. |
| R05-12 | Not planned: `frontend/package.json` has no Markdown renderer or sanitiser. See section 6. |
| R05-13 | Confirmed: `chat-ws-auth.ts` still falls back to `?token=` on a 404/405 ticket endpoint; `CHAT_WS_ALLOW_QUERY_TOKEN` defaults to `true`; the settings key `rudix.chat.settings.v1` is global per browser. |
| 0.4.0 deferrals | Tenant binding on WebSocket sessions: S2. `strict` as default: S3 for `development` and `test` only; staging and production stay `soft` until the soft-denial week and Celery binding (`R06-01`) are done. `FORCE ROW LEVEL SECURITY` ships as operator SQL, not a migration, because it only changes deployments that still connect as the owner. Cache namespaces for AI policy, RAG and model profiles, tool and quota policy: B2. Error codes for the chat routers: S3 (string details registered; the existing lower-snake structured codes such as `document_not_found` are not renamed). |

## 3. Sequence

| Chain | Order | Task | Items | Model | Review |
|---|---|---|---|---|---|
| S | 1 | S1 | R05-01 part 1: golden transcripts, domain extraction, pipeline, HTTP adapter (flag off) | opus | api |
| S | 2 | S2 | R05-01 part 2: WebSocket adapter and convergence, R05-02 short sessions, tenant binding | opus | api |
| S | 3 | S3 | R05-01 part 3: delete old paths, routes split, bots, chat error codes, `strict` readiness | opus | api |
| A | 1 | A1 | R05-03 token streaming, SSE, cancellation | opus | api |
| A | 2 | A2 | R05-06 provider resilience, R05-13 server side (resume, ticket default) | opus | api |
| B | 1 | B1 | R05-08 model routing, R05-07 cost ledger, R05-09 injection hardening | opus | api |
| B | 2 | B2 | R05-05 caches and shortcut, R05-04 latency budget, 0.4.0 cache namespaces | opus | api |
| C | 1 | C1 | R05-10 chat page split | sonnet | api |
| C | 2 | C2 | R05-11 streaming render, R05-13 client side, newest-first history | opus | api |

S runs first, one package at a time; A, B, and C start after S3 is merged. No package adds an
Alembic migration; the head stays `20261127_0005`. If an implementer finds one necessary, it
goes into S3 as `20261128_0001` with `down_revision = "20261127_0005"` and nowhere else.

## 4. Shared files and contracts

### 4.1 Owners and anchors

Every task re-reads a shared file immediately before editing it, edits only its anchor with
`Edit` (never a whole-file `Write` of a shared file), and re-reads after a failed `Edit`.

| File | Task: anchor |
|---|---|
| `backend/app/interfaces/http/chat.py` | S1–S3 own it. After S3: A1 adds `query_chat_stream` directly after `query_chat`; A2 edits the command loop of `chat_websocket` (new `chat.resume` branch after the `chat.cancel` branch) and its `finally`. No other task. |
| `backend/app/interfaces/http/chat_sessions.py` (S3) | C2: `list_chat_session_messages` only. |
| `app/application/chat/pipeline/context.py` (S1) | Fields go directly after the marker comment of the task: `# anchor: A1 streaming`, `# anchor: A2 resilience`, `# anchor: B1 ledger routing injection`, `# anchor: B2 budget caches`. |
| `app/application/chat/pipeline/events.py` (S1) | A1, then A2 (same chain). |
| `app/application/chat/pipeline/stages/generate.py` | A1 owns. B1 edits only `stages/_tree_search.py` (ledger lines). |
| `stages/rewrite.py`, `rerank_pack.py`, `verify.py`, `persist.py`, `shortcut.py`, `resolve_config.py`, `retrieve.py` | Chain B (B1, then B2). A1 edits `verify.py` only to emit `generation.final` after the `# anchor: A1 final event` marker. |
| `app/application/chat/transports/ws.py` (S2) | A1: `WsEmitter.emit`. A2: `stream_sequence`, buffering wrapper construction, grace handling. |
| `app/domains/chat/services/llm_service.py`, `app/domains/ai/providers/**` | Chain A only. |
| Auxiliary services (`query_rewriting_service.py`, `rerank_service.py`, `conflict_detection_service.py`, `grounded_answer_verifier.py`, `answer_refiner_service.py`, `tree_search_service.py`, `prompt_service.py`), `prompt_templates/services/defaults.py` | Chain B only. |
| `app/domains/chat/schemas/chat_ws.py` | Chain A only: A1 adds events after `"generation.delta",`; A2 adds `"chat.resumed"` after `"chat.cancelled",`, `"chat.resume"` to the command type, and safe codes `provider_busy` (after `plan_limit_exceeded`) and `resume_unavailable` (after `rate_limiter_unavailable`). |
| `app/domains/chat/schemas/trust_metadata.py`, `app/domains/chat/services/trust_metadata_builder.py` (S1) | Chain B only. |
| `app/core/metrics.py` | S1 after the `rudix_chat_quota_denied_total` block; A1, A2 after `rudix_chat_ws_auth_total`; B1, B2 after `rudix_llm_retries_total`. |
| `app/core/settings/features.py` | S1 after `chat_ws_allow_query_token`; A1 after `ws_chat_heartbeat_interval_seconds`; A2 after `chat_ws_ticket_ttl_seconds`. |
| `app/core/settings/ai_providers.py` | A2 after `llm_retry_max_seconds`. |
| `app/core/settings/rag.py` | B1 after `feature_enable_grounded_answer_verification`; B2 after `rerank_default_batch_size`. |
| `app/core/settings/redis_rate_limit.py` | B2 after `cache_ttl_profiles_seconds`. |
| `.env.example` | S1 after `CHAT_WS_ALLOW_QUERY_TOKEN=`; A1 after S1's `CHAT_PIPELINE_V2=`; A2 after `LLM_RETRY_MAX_SECONDS=` and after `CHAT_WS_TICKET_TTL_SECONDS=`; B1 after `FEATURE_ENABLE_CONFLICT_DETECTION=`; B2 after `RERANK_MMR_DUPLICATE_SIMILARITY_THRESHOLD=` and after `CACHE_TTL_PROFILES_SECONDS=`. |
| `app/core/cache_invalidation.py` | B2 only. |
| `app/db/tenant_context.py`, `app/core/config.py` (`effective_rls_enforcement`) | S2 (binding helper), S3. |
| `backend/tests/redis_fakes.py` | A2 adds methods after `smembers`; B2 after `getdel`. |
| `backend/tests/fixtures/chat_golden/*` | S owns. Later re-records only for the reasons in contract 4.2.4. |
| `backend/tests/accuracy_smoke_support.py` | B1: `_parse_context_blocks` only. |
| `frontend/src/lib/use-chat-websocket.ts`, `chat-websocket.ts`, `chat-ws-auth.ts`, `chat-ws-errors.ts`, `src/components/chat/**` | Chain C only (C1, then C2). |
| `frontend/playwright.config.ts`, `frontend/next.config.*` | C2 only. |
| `frontend/openapi.json`, `frontend/src/lib/api/generated/*` | Regenerated with `npm run api:update-schema` by A1, B1, B2, C2 after their API changes. On a merge conflict, regenerate; never hand-merge. |
| `infra/observability/prometheus/alerts.yml` | A1 then A2: new groups appended at the end. |
| `infra/observability/grafana/dashboards/06-rudix-chat-pipeline.json` | A1 creates it with panels for every metric in spec section 7. |
| `docs/07_API_DESIGN.md` | S3: body of `## Error format` (chat codes table). A1: new `### Chat event protocol` and `### POST /chat/query/stream` after `### POST /chat/ws-ticket`. A2: new `#### Resume` after `#### Handshake authentication`, and the `?token=` bullet. B2: bullets at the end of `### POST /chat`. C2: `### GET /chat/sessions/{session_id}/messages` (new, before `### POST /chat`). |
| `docs/03_RAG_WORKFLOW.md` | S2: `### Steps` under `## Query pipeline`. B1: `## Prompt builder`. B2: new `### Caches and shortcuts` before `## Re-ranking`. |
| `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` | S3: `## Authorization`, `### Database`. A2: last bullet of `### API`. B1: `## Prompt injection defenses`. B2: `## Caching of security-sensitive data`. |
| `docs/12_EVALUATION_AND_MONITORING.md` | S1, A1, A2, B1, B2: one `###` subsection each, inserted before `## Continuous evaluation`. |
| `backend/README.md` | S1: `## Chat pipeline` before `## Application cache`. A1, A2, B1, B2: bullets at the end of that section. |
| `frontend/README.md` | C1, C2: bullets in the chat entry under `## Implemented Pages`. |
| `docs/CHANGELOG.md` | One line per task under `[Unreleased]` `### Added`, directly after the line starting "- `docs/roadmap/V0_5_0_IMPLEMENTATION_PLAN.md`". |

### 4.2 Contracts between chains

1. **Databases and worktrees.** Branch `feat/v0.5.0-<task>` in worktree `../rudix-v050-<task>`
   cut from the current `develop`; `cd backend && make install`. Each chain uses its own
   database (`rudix_test_s`, `rudix_test_a`, `rudix_test_b`, `rudix_test_c`) on
   `127.0.0.1:55432`, created with the snippet in the `0.4.0` plan section 4.2 item 1. Next.js
   commands rewrite `frontend/AGENTS.md` and `frontend/tsconfig.json`; restore both with
   `git checkout --` before each commit.
2. **Compatibility surface of `chat.py` (S1 defines, S3 keeps, `tests/test_chat_module_compat.py`
   checks).** Same objects as the pipeline uses: `_llm_service`, `_query_retrieval_service`,
   `_rerank_service`, `_grounded_verifier`, `_query_rewriting_service`, `_graph_retrieval_service`,
   `_feature_flag_service`, `chat_repository`, `settings`. Rebindable globals the adapters read at
   call time: `_openai_client`, `SessionLocal`, `ensure_chat_quota`, `authenticate_ws_handshake`,
   `_run_ws_chat_pipeline`. Functions: `query_chat` (same signature, also used by bots until S3),
   `chat_websocket`, `_run_ws_chat_pipeline(websocket, payload, principal, request_id,
   sequence_start)`. Re-exported helpers imported by tests (`_with_table_metadata`,
   `_build_tool_orchestration_record`, `_build_retrieval_method_record`,
   `_resolve_planner_critic_controls`, `_build_planner_critic_record`, `_parse_uuid_or_none`,
   `_build_conflict_context`, `_compute_conflict_multiplier`, `_with_conflict_status`, the F315
   names, `GraphRetrievalResult`, `GraphRetrievedChunk`, `AuthenticatedPrincipal`).
3. **Test edits.** `test_chat_transport_parity.py`, `test_rag_isolation_f144.py`,
   `test_index_version_isolation.py`, `test_tenant_isolation_f336.py`, `test_accuracy_smoke.py`,
   and `test_guardrails_f145.py` are not edited in S. Elsewhere an S task may change only import
   paths and `patch(...)` targets (for example `app.interfaces.http.chat.settings` in
   `test_f339_planner_critic_refiner.py`), never an assertion; each such edit is listed in the
   merge request.
4. **Golden transcripts (S1).** `tests/fixtures/chat_golden/<scenario>.<transport>.json`,
   rewritten only with `CHAT_GOLDEN_UPDATE=1`. Consecutive `generation.delta` events are
   collapsed into one; UUIDs become stable labels; timestamps, latencies, request ids, and
   `sequence` are dropped; prompt hashes are taken after normalising UUIDs and the B1 boundary
   token. Allowed re-records, each in its own commit with the diff in the merge request: S2
   (WebSocket convergence), A1 (new `generation.final` events and `generation.started`
   payload), B1 (prompt hashes and the new trust fields), B2 (new trust fields only).
5. **Ledger (S1 defines).** `TokenLedger.record(stage, provider_key, model, prompt_tokens,
   completion_tokens, cached_tokens=0, cost_usd=None, estimated=False)` and `totals()`. S1
   records embedding and generation only, which equals today's usage event. A1 uses it for
   cancelled runs; B1 records every auxiliary call and switches the usage event to the totals.
6. **Event protocol (A1 defines, C2 consumes).** Envelope unchanged plus, from A2, an optional
   `stream_sequence` (1, 2, … per assistant message). Per answer: `generation.started`
   (`payload.mode = "live" | "buffered"`), any number of `generation.delta` (`{"text": <increment>}`),
   optional `generation.replace` (`{"text": <full text>, "reason": "verification" | "policy" |
   "retry" | "fallback" | "normalisation"}`), then `citation.validation.*`, then
   `generation.final` (`{"answer", "not_found", "citations", "confidence_score",
   "confidence_category", "citation_validation_failed"}`), then the existing `chat.completed`
   after persistence. Text before `generation.final` is provisional; on `generation.replace` the
   client replaces all streamed text; `chat.completed` stays the source of truth.
   `message_id` (pre-assigned in S2) is set on every event from `generation.started` on.
7. **Resume protocol (A2 defines, C2 consumes).** Command `{"command": "chat.resume",
   "payload": {"message_id": "<uuid>", "last_stream_sequence": <int>}}` on a new connection
   authenticated with a fresh ticket. The server sends `chat.resumed` (`{"message_id",
   "replayed": <int>}`), replays buffered events with a higher `stream_sequence` in order, then
   continues live. If the run finished and the buffer expired, it sends one `chat.completed`
   rebuilt from the stored message. Otherwise `chat.error` with `resume_unavailable`. The client
   discards events whose `(message_id, stream_sequence)` it has already applied.
8. **Safe error codes.** New WebSocket codes: `provider_busy` (A2, organisation concurrency
   limit; HTTP `429` with `detail.code = "provider_busy"`) and `resume_unavailable` (A2). C2 maps
   both in `chat-ws-errors.ts`. `tests/test_chat_ws_error_codes.py` stays in sync.
9. **Tenant binding (S2 defines).** `bind_pipeline_session(session, organization_id)` in
   `app/db/tenant_context.py` binds the session and the context variable with
   `enforce_guard` in `strict` and runs `apply_tenant_context`. Every pipeline session uses it.

## 5. Steps per item

### R05-01 part 1 — Goldens, extraction, HTTP pipeline (S1)

1. First commit, before any code moves: `tests/chat_golden_support.py`,
   `tests/test_chat_golden_transcripts.py`, and the fixtures, recorded through the current code
   with fake providers. Scenarios on both transports: grounded, not found, question injection,
   policy topic block, guidance, scope inventory, cite-access drop (member), rerank, planner/
   critic/refiner, conflict, invalid model chunk id, LLM failure, follow-up in an existing
   session, unknown session; HTTP behaviour recorded for rewriting, context packing, strict
   verifier, tree search, and stale sources (also recorded on WebSocket as it is today).
2. Pure moves to `app/domains/chat/services/`: `query_intent_service.py` (`_infer_query_intent`,
   `_query_complexity`, `_guidance_label`, `_build_query_interpretation_record`),
   `confidence_calibration.py` (`_compute_*_multiplier`, evidence-quality helpers,
   `_to_confidence_signals`, `_confidence_category_from_score`), `trust_metadata_builder.py`
   (`_build_trust_metadata`, record builders, `_build_retrieval_diagnostics_payload`),
   `citation_enrichment.py` (`_with_*`), `retrieved_chunk.py` (`RetrievedChunk`, converters,
   merge). Scope inventory goes to `app/application/chat/scope_inventory.py`.
3. `app/application/chat/pipeline/`: `context.py`, `events.py` (typed events, `Emitter`,
   `CollectingEmitter`), `deps.py` (`ChatPipelineDeps`), `ledger.py`, `sessions.py` (scope
   interface, single-session mode), `runner.py` (per-stage timeout, deadline, skip recording,
   background-task cleanup; all off by default), `pipeline.py`, and one file per stage under
   `stages/` (helpers `_evidence.py`, `_packing.py`, `_tree_search.py`, `_confidence.py`).
   Stage 4 `shortcut.py` is a pass-through. Every file under 500 lines.
4. `app/application/chat/transports/http.py`; `query_chat` delegates when `CHAT_PIPELINE_V2=true`
   (default `false`), otherwise runs the old body unchanged.
5. Metric `rudix_chat_stage_seconds{stage}`. Docs: backend README, docs/12, CHANGELOG.

### R05-01 part 2 and R05-02 — WebSocket, sessions, binding (S2)

1. `transports/ws.py` (`WsEmitter`, one sequence counter for the connection and the run);
   `_run_ws_chat_pipeline` becomes a wrapper that passes `SessionLocal` and `ensure_chat_quota`
   read from `chat.py` at call time.
2. Convergence commit: the WebSocket runs every stage; re-record WebSocket goldens (4.2.4).
3. Session scopes: one read session for stages 1, 2, 4, ended with `commit()`; config resolved
   into DTO snapshots; short sessions for DB reads in stages 6 and 7, closed before return; no
   session during generation or verifier calls; one write session for stage 10 with one
   commit. Chat session and assistant message ids are pre-assigned (`create_chat_session` and
   `create_chat_message` gain optional ids). HTTP uses the request session for both phases.
4. Tenant binding (4.2.9) for every pipeline session and the run's context variable.
5. `CHAT_PIPELINE_V2` defaults to `true`.
6. Tests: zero checked-out connections and `in_transaction() is False` while the stub generates
   (both transports, with a control test); 20 concurrent WebSocket runs on a pool of 2 with
   200 ms stub latency succeed on PostgreSQL; a failure before stage 10 leaves no session row;
   a statement-count baseline for one HTTP question; a WebSocket run under `strict`.

### R05-01 part 3 and strict readiness — Cleanup (S3)

1. Delete the old bodies of `query_chat` and `_run_ws_chat_pipeline`; `CHAT_PIPELINE_V2=false`
   logs a deprecation warning and is ignored (kept one milestone).
2. Routes move to `chat_sessions.py`, `chat_shares.py`, `chat_feedback.py`,
   `chat_answer_shares.py`, `chat_trust.py`, included into `chat.router` in the original order;
   `scripts/export_openapi.py --check` shows no change; `chat.py` under 500 lines.
3. `bot_service.py` calls `transports/internal.py` and binds the tenant from the installation.
4. Chat detail strings registered in `DETAIL_ERROR_CODES`; docs/07 lists the chat codes.
5. `effective_rls_enforcement`: unset means `strict` in `development` and `test`. Bind the
   tenant on the shared agent trace page and on pre-authentication audit writes. F144 runs
   under the probe role on PostgreSQL. `deploy/sql/force_rls.sql` and `unforce_rls.sql`
   rendered by `scripts/render_force_rls_sql.py` from `app.db.rls` (test checks they match).

### R05-03 — Token streaming (A1)

`StreamingChatProvider.stream()` for OpenAI and OpenAI-compatible adapters (usage from the last
chunk), one-chunk fallback; `LLMService.stream_answer()` with the same retry and fallback;
`AnswerFieldStreamExtractor` (escapes and surrogate pairs split across chunks). Buffered mode
when grounded verification is strict, when the effective AI policy has a post-generation block
rule, or for tree search. `POST /chat/query/stream` (SSE, `id`/`event`/`data` frames, same
roles, rate limit, and quota; failures in stages 1–3 return the same HTTP errors as `POST
/chat`). Cancellation by `chat.cancel` or SSE disconnect closes the provider stream and records
a `chat.completion.cancelled` usage event (provider usage, else estimates flagged
`usage_estimated`), no message, no question count. `rudix_chat_ttft_seconds{transport}`,
dashboard, and alert.

### R05-06 and R05-13 server — Resilience and resume (A2)

Circuit breaker per provider and model (`resilience.py`, `ResilientChatProvider`, open breaker
skips retries and goes to the fallback provider), stream idle timeout, Redis semaphore per
organisation (`LLM_ORG_MAX_CONCURRENT_CALLS`, 0 = off, fails open when Redis is down),
cached-prompt-token accounting. Resume buffer in Redis keyed by organisation, user, and
message, TTL `CHAT_RESUME_BUFFER_TTL_SECONDS` (300), grace `CHAT_WS_RESUME_GRACE_SECONDS` (30;
0 restores cancel-on-drop), `chat.resume`, `chat.resumed`, `stream_sequence`.
`CHAT_WS_ALLOW_QUERY_TOKEN` defaults to `false`.

### R05-08, R05-07, R05-09 — Auxiliary stages (B1)

Auxiliary services take the resolved `chat` profile. Every provider call records into the
ledger; the usage event stores totals and `metadata.token_ledger`; `QuotaType.tokens` records
the total; `rudix_chat_tokens_total{stage,kind}`. Context blocks wrapped with a per-request
random boundary; the untrusted-context rule in the system message of every call that carries
document text; `PromptInjectionGuard.scan_context`; `CHAT_CONTEXT_INJECTION_ACTION`
(`flag|downrank|drop`, default `downrank`); new F146 cases per auxiliary stage.

### R05-05, R05-04, cache namespaces — Query path (B2)

Query-embedding cache (`query_embedding` namespace, organisation scope, normalised text hash);
verified-answer stage 4 (exact normalised match, permission and scope checks on every citation,
no provider call on a hit); cached AI policy, RAG profile, model profile, chat tool policy,
quota policy (limits only), published verified-answer candidates, and active prompt version,
each invalidated from ORM flushes. Deadline and per-stage budgets with a skip policy recorded in
`stage_degradations`; strict verification is never skipped (the answer is withheld); rerank
batches concurrent (`RERANK_MAX_CONCURRENT_BATCHES`, order-preserving); original-question
embedding overlapped with configuration resolution. Statement count of a warm-cache question at
12 or fewer.

### R05-10 — Chat page split (C1)

`ChatPage.tsx` becomes a route shell; `ChatThread`, `ChatTurnItem`, `ChatComposer` (split),
`ChatSidebar`, `ScopeControls`, `StreamingMessage`, hooks `useChatSession`, `useChatSettings`,
`useChatStream`, and pure helpers in `chat-*.ts`; `AnswerTrustPanel` split by section and lazy
where tests allow. No file over 500 lines; every `vi.mock` path stays valid; the skipped MSW
submit test is restored.

### R05-11 and R05-13 client — Render and reconnect (C2)

Ref-backed streaming store flushed once per animation frame (`useSyncExternalStore` in
`StreamingMessage` only), memoised turns, virtualised thread above a threshold, newest-first
cursor history (`order=desc`, additive), scroll only at the bottom. Reconnect with exponential
backoff and full jitter, fresh ticket, `chat.resume`, de-duplication, `generation.replace`;
no `?token=` fallback; settings key namespaced by organisation and user. Playwright drops the
socket mid-stream in a second project with WebSocket chat enabled.

## 6. Deferred

- `R05-12` rich answer rendering. Nothing installed renders Markdown. Decision needed: approve
  `react-markdown` with `remark-gfm` (no `rehype-raw`), or approve an in-house renderer that
  builds React elements for a fixed subset (paragraphs, lists, emphasis, code, tables) with no
  HTML strings. Plain text stays.
- `strict` as the default in staging and production, and applying `force_rls.sql`: after the
  `0.4.0` soft-denial week and the role split. Tenant binding in Celery tasks: `R06-01`.
- Reordering the answer template for prefix caching (versioned, org-editable templates).
- Semantic answer cache (post-`1.0`, per spec). Error codes for routers other than chat, and
  any rename of existing structured codes. Cross-organisation design for identity tables.
- Splitting `DocumentPreviewModal.tsx` (1,217 lines) and `SourceScopeSelector.tsx` (798).
- A frontend SSE client (`R07-07` consumes the protocol).

## 7. Verification for the release

```bash
cd backend && make check-revisions && make lint && make test && make test-cov
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://rudix:rudix@127.0.0.1:55432/rudix_test make test-postgres
cd backend && .venv/bin/pytest -m "isolation or guardrails or accuracy_smoke" tests/test_chat_transport_parity.py tests/test_chat_golden_transcripts.py
cd backend && .venv/bin/python scripts/export_openapi.py --check ../frontend/openapi.json
cd frontend && npm run typecheck && npm run lint && npm run test:coverage && npm run build
cd frontend && npm run test:e2e
wc -l backend/app/interfaces/http/chat.py frontend/src/components/chat/ChatPage.tsx
```

Coverage must stay at or above the ratchets (backend 77.3; frontend lines 64.8, statements
63.9, functions 58.0, branches 57.6). The Playwright count must be at least 232 plus the new
tests. `alembic heads` must report `20261127_0005` (or `20261128_0001` if S3 added one).

## 8. Manual steps (staging and production)

1. Run the load baseline (`R03-09`) with streaming on: time to first token, full answer, 200
   concurrent streams on one replica, statement count per question, pool wait.
2. Run the `requires_redis` lane: semaphore and resume scripts against Redis 7; resume across
   two replicas.
3. Exercise streaming against the real OpenAI and local providers (usage in the last chunk,
   `stream_options` support, cancellation).
4. After the soft-denial week and the role split: apply `deploy/sql/force_rls.sql`, then set
   `RLS_ENFORCEMENT=strict`. Rollback: `unforce_rls.sql` and `RLS_ENFORCEMENT=soft`.
5. Turn on `CHAT_VERIFIED_ANSWER_SHORTCUT_ENABLED` per environment after reviewing the
   published verified answers.

## 9. Change Notes

- 2026-11-27: Initial version, written after checking the `0.5.0` spec against the code at
  `21bdb6a`.
