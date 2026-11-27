# Versioned Roadmap and Release Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [roadmap/00_AUDIT_BASELINE.md](./roadmap/00_AUDIT_BASELINE.md),
  [01_ARCHITECTURE_OVERVIEW.md](./01_ARCHITECTURE_OVERVIEW.md),
  [03_RAG_WORKFLOW.md](./03_RAG_WORKFLOW.md),
  [11_SECURITY_AND_PRODUCTION_CHECKLIST.md](./11_SECURITY_AND_PRODUCTION_CHECKLIST.md),
  [14_GITHUB_ACTIONS_CI_CD_PIPELINE.md](./14_GITHUB_ACTIONS_CI_CD_PIPELINE.md)

## 1. Purpose

This document is the release plan from the current state (`0.1.0`, untagged) to `1.0.0`
general availability. It assigns every product area to a version, and it schedules the
correctness, performance, and scalability work found in the November 2026 full-application
audit. Each version has its own implementation spec under [roadmap/](./roadmap/).

Everything in this document is **planned** unless a section says otherwise. Nothing here
describes shipped behaviour except the baseline in section 4.2.

## 2. Scope

In scope: backend, frontend, workers, RAG pipeline, infrastructure, CI/CD, and release process.

Out of scope: pricing, marketing content, and staffing. No calendar dates are given. Versions
are ordered by dependency, and each work item carries a relative size (S, M, L).

## 3. Assumptions and Constraints

- The audit read code at commit `f3447b83`. It did not run the test suites, load tests, or a
  live deployment. Findings marked "verify first" in the specs are inferred from code.
- Backward compatibility is the default (see `AGENTS.md`). Renames and removals keep an alias
  for at least one minor version and are removed no earlier than `1.0.0`.
- New production dependencies, external services, and infrastructure need approval before
  work starts. Section 8 lists every such decision.
- No file should grow past roughly 500 lines. Several work items exist only to split files
  that already exceed this.

## 4. Design or Procedure

### 4.1 Versioning scheme

- Semantic Versioning. Backend (`backend/pyproject.toml`) and frontend
  (`frontend/package.json`) share one version number and are bumped together.
- Git tags are `vMAJOR.MINOR.PATCH`. A tag is the only trigger for a new production release;
  a production dispatch can only redeploy an existing tag (`version` input), and neither
  rebuilds images.
- `0.x` minors may change defaults behind feature flags. They MUST NOT break API payload
  shapes without an alias.
- Patch releases (`0.x.y`) carry fixes only and never include migrations that drop data.
- Release candidates use `vX.Y.Z-rc.N` and deploy to staging only. `release.yml` runs no
  jobs for an `-rc` tag: staging is deployed from every `main` push, and production skips
  `-rc` tags.
- Version strings live in seven places: `backend/pyproject.toml`, `frontend/package.json`,
  `frontend/package-lock.json` (top-level and `packages[""]`), the `api_version` default in
  `backend/app/core/settings/app.py`, `API_VERSION` in `.env.example`, and `info.version` in
  `frontend/openapi.json`. `python3 scripts/bump_version.py X.Y.Z [--changelog] [--dry-run]`
  rewrites all of them (SemVer with an optional `-rc.N`, downgrades refused), and
  `--changelog` moves the `[Unreleased]` body of `docs/CHANGELOG.md` under
  `## [X.Y.Z] - <date>`. `--check` verifies that they agree and, on a tag, that the tag is
  `v<version>`; the release's `verify-staged` job runs it. `scripts/extract_release_notes.py
  vX.Y.Z` prints that changelog section for the GitHub Release.
- Release order: bump on a branch, merge to `main`, wait for the staging deploy of the merge
  commit (it tags `staging-passed-<sha>`), then tag that commit `vX.Y.Z`.
- Work items are identified as `R<minor>-<nn>`, for example `R02-05` is item 5 of `0.2.0`.
  They are local to this roadmap and do not collide with the `rudix#NNN` / `FNNN` feature IDs.

### 4.2 Baseline: v0.1.0 (tag the current state)

The application already contains 26 product areas (feature IDs #10 to #366). Tag the current
`main` as `v0.1.0` before any roadmap work so every later change has a reference point. The
full catalogue, per-area status, and audit evidence are in
[roadmap/00_AUDIT_BASELINE.md](./roadmap/00_AUDIT_BASELINE.md).

### 4.3 Release train

| Version | Theme | Outcome | Spec |
|---|---|---|---|
| `0.1.0` | Baseline | Current state tagged and catalogued | [00](./roadmap/00_AUDIT_BASELINE.md) |
| `0.2.0` | Correctness and safety | Known defects in chat, ingestion, scheduling, and deploy are fixed | [V0_2_0](./roadmap/V0_2_0_CORRECTNESS_AND_SAFETY.md) |
| `0.3.0` | Test and release foundation | Tests run on Postgres, gates block merges, releases are reproducible and signed | [V0_3_0](./roadmap/V0_3_0_TEST_AND_RELEASE_FOUNDATION.md) |
| `0.4.0` | Data layer performance | Pooling, indexes, caching, tenant RLS, retention | [V0_4_0](./roadmap/V0_4_0_DATA_LAYER_PERFORMANCE.md) |
| `0.5.0` | Chat pipeline and streaming | One pipeline for HTTP and WebSocket, real token streaming, latency budget | [V0_5_0](./roadmap/V0_5_0_CHAT_PIPELINE_AND_STREAMING.md) |
| `0.6.0` | Ingestion and workers | Staged resumable ingestion, isolated worker pools, vector index tuning | [V0_6_0](./roadmap/V0_6_0_INGESTION_AND_WORKERS.md) |
| `0.7.0` | Frontend performance | Static marketing pages, split bundles, typed API client, push instead of polling | [V0_7_0](./roadmap/V0_7_0_FRONTEND_PERFORMANCE.md) |
| `0.8.0` | Production infrastructure | TLS, replicas, HA data stores, backups, zero-downtime deploys, alerting | [V0_8_0](./roadmap/V0_8_0_PRODUCTION_INFRASTRUCTURE.md) |
| `0.9.0` | Product completeness | Signup, MFA, payments, missing admin UIs, flag graduation | [V0_9_0](./roadmap/V0_9_0_PRODUCT_COMPLETENESS.md) |
| `1.0.0` | General availability | API frozen, SLOs proven under load, security review passed | [V1_0_0](./roadmap/V1_0_0_GENERAL_AVAILABILITY.md) |

Ordering rationale:

1. `0.2.0` goes first because it fixes defects that affect users today, including a quota and
   citation-authorization gap on the default chat transport.
2. `0.3.0` precedes all refactoring. The large rewrites in `0.4.0` to `0.6.0` are unsafe while
   tests run only on SQLite and end-to-end gates are manual.
3. `0.4.0` precedes `0.5.0` because the chat pipeline depends on the cache layer and on short
   database sessions.
4. `0.7.0` can run in parallel with `0.5.0` and `0.6.0` once `0.3.0` is done. Its chat items
   depend on the `0.5.0` streaming protocol.
5. `0.8.0` needs the stateless-replica work from `0.4.0` and `0.5.0`.
6. `0.9.0` adds product surface last so that new features are built on the hardened base.

### 4.4 Product area to version map

"Baseline" means built and wired at `0.1.0`. The other columns list the versions that harden,
complete, or change the area.

| # | Product area | Baseline status | Hardened or completed in |
|---|---|---|---|
| 1 | Auth and sessions | Partial | `0.2` (WS ticket), `0.4` (auth cache), `0.7` (token storage), `0.9` (signup, reset, MFA) |
| 2 | Org, team, roles, permissions | Complete | `0.4` (permission cache, RLS) |
| 3 | SSO, SCIM, API keys, service accounts | Complete | `0.4` (usage-write batching), `1.0` (real IdP test) |
| 4 | Ingestion and upload security | Complete | `0.2` (retry fix), `0.6` (staged pipeline) |
| 5 | Chunking | Complete, flags off | `0.6`, `0.9` (flag graduation) |
| 6 | Retrieval | Complete, advanced flags off | `0.2` (index isolation), `0.5`, `0.6`, `0.9` |
| 7 | Answer generation and trust | Complete, flags off | `0.5` (streaming, cost, injection hardening), `0.9` |
| 8 | Chat UX | Complete | `0.2`, `0.5` (pipeline, UI split, reconnect) |
| 9 | Knowledge organisation | Complete | `0.4` (N+1 fixes), `0.7` (pagination) |
| 10 | Connectors | Partial (4 providers) | `0.6` (sync engine), `0.9` (Jira decision) |
| 11 | GraphRAG | Complete, opt-in | `0.6` (batched writes, separate task) |
| 12 | Agents | Partial | `0.6` (worker execution, resume, stream) |
| 13 | MCP | Complete, off | `0.8` (replica validation), `0.9` (flag decision) |
| 14 | Org memory | Complete, off | `0.9` (flag decision) |
| 15 | Evaluation and quality | Complete | `0.2` (task registration), `0.3` (CI gating), `0.6` (isolation) |
| 16 | Model providers and local LLM | Complete, opt-in | `0.5` (profile routing for auxiliary stages) |
| 17 | Admin ops and observability | Complete | `0.8` (production stack, alert routing, tracing) |
| 18 | Reports and analytics | Complete | `0.4` (retention, export streaming), `0.8` (read replica) |
| 19 | Billing, plans, quotas | Stub for payments | `0.2` (atomic quota), `0.5` (full cost), `0.9` (payments) |
| 20 | Notifications, email, webhooks | Partial | `0.7` (push channel), `0.9` (email admin UI) |
| 21 | Collaboration bots | Backend only | `0.9` (admin UI) |
| 22 | Settings | Complete | `0.9` (MFA, billing) |
| 23 | i18n and RTL | Complete, half translated | `0.7` (namespace split, remaining strings) |
| 24 | Public site, legal, onboarding, help | Complete | `0.7` (static generation) |
| 25 | Data lifecycle and portability | Complete | `0.4` (retention jobs), `0.8` (backups) |
| 26 | Platform and CI | Complete | `0.3`, `0.8` |

### 4.5 Feature flag graduation

25 of 44 `FEATURE_*` flags default to off. A flag graduates to on only when the accuracy
gates (F302, F149) pass with the flag enabled and the latency budget in section 4.6 holds.

| Flag group | Target default | Version | Gate |
|---|---|---|---|
| `hybrid_retrieval`, `context_packing` | On | `0.6.0` | Multilingual FTS and index isolation done |
| `query_rewriting`, `dynamic_retrieval_routing` | On | `0.9.0` | Latency budget met with streaming |
| `grounded_answer_verification` | On (standard mode) | `0.9.0` | Streaming correction event shipped in `0.5.0` |
| `conflict_detection`, `planner_critic_refiner` | Per-profile opt-in | `0.9.0` | Cost accounting covers all stages |
| `chunking_profiles`, `adaptive_chunking` | On | `0.9.0` | Staged ingestion done |
| `graph_rag` and extraction flags | Opt-in (needs Neo4j) | unchanged | Not applicable |
| `mcp`, `org_memory`, `chat_tool_orchestration` | Decide at `0.9.0` | `0.9.0` | Product decision |
| `tree_search_reasoning`, `experimental_profiles` | Off | unchanged | Not applicable |

### 4.6 Performance and scale targets

These are **proposed targets**, not measurements. `R03-09` establishes the first measured
baseline, and the targets are revised against it before `0.4.0` starts.
The baseline template is
[`roadmap/V0_3_0_LOAD_BASELINE.md`](./roadmap/V0_3_0_LOAD_BASELINE.md), still marked "not yet
measured"; these targets are revised once it is measured.

| Metric | Target at `1.0.0` |
|---|---|
| Chat time to first token, default profile, p95 | 2.5 s or less |
| Chat full answer, default profile, p95 | 12 s or less |
| Non-LLM API read endpoints, p95 | 300 ms or less |
| Ingestion of a 50-page text PDF to `indexed`, p95 | 90 s or less |
| Concurrent chat streams per API replica | 200, with no pool exhaustion |
| Database queries per chat request | 12 or fewer |
| API availability | 99.9% monthly |
| Recovery point / recovery time | 15 min / 4 h |

Scaling model the plan converges on:

- API replicas are stateless. Shared state lives in Postgres and Redis only.
- Workers scale per queue: ingestion, connector sync, evaluation, and default pools.
- One Qdrant collection per embedding model version, tenant-partitioned by payload, swapped
  with aliases.
- Postgres is the system of record, fronted by a pooler, with a read replica for analytics.

### 4.7 Definition of done for a version

A version is tagged when every item in its spec meets its "Done when" line, the checks in
`AGENTS.md` pass, the spec's exit criteria hold on staging, and `docs/CHANGELOG.md` has an
entry for the version.

## 5. Failure Modes and Recovery

| Risk | Mitigation |
|---|---|
| A refactor regresses behaviour that SQLite tests cannot see | `0.3.0` lands before `0.4.0` to `0.6.0` |
| The chat unification changes answers | Golden-transcript tests and the accuracy gate run on both transports before the old code is deleted |
| A migration locks a large table | Indexes are created concurrently and schema changes follow expand-contract (`R08-08`) |
| A flag graduation raises latency or cost | Graduation is per flag, gated, and reversible per organisation |
| An approval in section 8 is delayed | Each affected item names a fallback that needs no new dependency |

## 6. Security Considerations

Security-relevant work is front-loaded. `0.2.0` closes the WebSocket quota and citation gap,
removes the token from the WebSocket URL, and adds response security headers. `0.4.0` turns on
database-level tenant isolation. `0.9.0` adds MFA. `1.0.0` requires an external security
review. Details of exploitable findings stay in the specs and are not copied into public
issue text.

## 7. Observability and Operations

Every performance item names the metric that proves it. Metrics, dashboards, and alert rules
already exist in `infra/observability/` but are a development overlay. `0.8.0` moves them
into staging and production and routes alerts to a real receiver.

## 8. Open Questions

Each of these needs an approval before the listed item starts.

| Decision | Needed for | Recommended | Fallback without approval |
|---|---|---|---|
| Orchestrator: Kubernetes with Helm, or stay on Compose | `R08-02` | Kubernetes for autoscaling and rolling deploys | Compose with a reverse proxy and manual replicas |
| Managed Postgres or self-hosted HA | `R08-04` | Managed, with PITR | Self-hosted primary plus streaming replica and WAL archiving |
| Payment provider | `R09-03` | One provider behind the existing billing service interface | Keep usage-derived invoices |
| Python lockfile tool (`uv` or `pip-tools`) | `R03-05` | `uv` | `pip-tools` |
| Load-test tool (k6 or Locust) | `R03-09` | k6 | Locust, already Python |
| Markdown renderer for answers | `R05-12` | A maintained renderer with sanitisation | Keep plain text |
| OpenTelemetry tracing | `R08-10` | Yes | Request IDs and Langfuse only |
| Official Sentry SDK in the frontend | `R07-11` | Yes | Keep the hand-rolled client |
| Cross-encoder reranker service | Post-1.0 | Evaluate after `0.5.0` latency data | Keep LLM reranking |
| Restore or drop the Jira connector | `R09-06` | Product decision | Remove the "coming soon" card |

## 9. Change Notes

- 2026-11-26: Initial version, written from the full-application audit at commit `f3447b83`.
