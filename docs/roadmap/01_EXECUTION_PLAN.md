# Roadmap Execution Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Active
- `Last Updated`: 2026-11-27
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [00_AUDIT_BASELINE.md](./00_AUDIT_BASELINE.md)

## 1. Purpose

Describe how the roadmap from `0.4.0` to `1.0.0` is executed: who plans, who implements, how
work is checked, how branches are committed, merged, and deleted, and what in each version
cannot be finished without a decision or an environment that the implementers do not have.

The per-version specs say what to build. This document says how the work is run.

## 2. Status

| Version | Theme | State |
|---|---|---|
| `0.2.0` | Correctness and safety | Implemented on `develop`. Not tagged, not deployed. |
| `0.3.0` | Test and release foundation | Implemented on `develop`. No workflow has run on GitHub yet. |
| `0.4.0` | Data layer performance | Implemented on `develop`. Partition conversion and strict RLS in production are deferred; see [V0_4_0_IMPLEMENTATION_PLAN.md](./V0_4_0_IMPLEMENTATION_PLAN.md). |
| `0.5.0` | Chat pipeline and streaming | Implemented on `develop`, except `R05-12` (needs a decision). See the Status section of [V0_5_0_IMPLEMENTATION_PLAN.md](./V0_5_0_IMPLEMENTATION_PLAN.md). |
| `0.6.0` | Ingestion and workers | Implemented on `develop` (all nine packages); staging checks pending. See the Status section of [V0_6_0_IMPLEMENTATION_PLAN.md](./V0_6_0_IMPLEMENTATION_PLAN.md). |
| `0.7.0` | Frontend performance | Implemented on `develop` (all nine packages, no migrations); the `/documents` bundle budget fails and staging checks are pending. See the Status section of [V0_7_0_IMPLEMENTATION_PLAN.md](./V0_7_0_IMPLEMENTATION_PLAN.md). |
| `0.8.0` | Production infrastructure | Implemented on `develop` (all nine packages, no migrations); provisioning, drills, load tests, and the CI-only config checks are pending. See the Status section of [V0_8_0_IMPLEMENTATION_PLAN.md](./V0_8_0_IMPLEMENTATION_PLAN.md). |
| `0.9.0` | Product completeness | Planned: nine packages in five chains, three migrations in S1, decisions taken (Stripe behind a provider port and off by default, TOTP MFA, no self-serve signup, connector placeholders removed). See [V0_9_0_IMPLEMENTATION_PLAN.md](./V0_9_0_IMPLEMENTATION_PLAN.md). |
| `1.0.0` | See section 5 | Not started. |

Measured on `develop` after `0.5.0`: backend coverage 79.7%; frontend coverage 64.9% statements,
58.2% branches, 58.8% functions, 65.8% lines. Measured after `0.6.0`: backend 82.2%;
frontend 65.1% statements, 58.5% branches, 59.1% functions, 66.0% lines. Measured after
`0.7.0` (backend without `.env`, as in CI): backend 82.46%; frontend 68.66% statements, 60.88%
branches, 62.19% functions, 69.57% lines (ratchets raised to 82.4, 68.6, 60.8, 62.1, 69.5).
Measured after `0.8.0` (same conditions): backend 83.01%; frontend 68.76% statements, 60.96%
branches, 62.34% functions, 69.66% lines (ratchets raised to 83.0, 68.7, 60.9, 62.3, 69.6). CI
fails when a figure drops.

## 3. Roles

| Role | Model | Does |
|---|---|---|
| Planner | Opus | Reads the version spec and the current code. Writes `V<version>_IMPLEMENTATION_PLAN.md`. Splits the version into at most eight work packages, assigns them to chains, and picks the implementer model for each. |
| Implementer | Sonnet or Opus | Builds one work package on its own branch in its own git worktree. |
| Reviewer | Opus | Reads the whole branch diff against the spec, runs every check, fixes defects, commits the fixes. |
| Integrator | Sonnet | Merges one reviewed branch at a time into `develop`, then deletes the branch and its worktree. |
| Release integrator | Opus | After all packages: checks `develop` as a whole and records the version status. |

Model choice: Sonnet for mechanical or fully specified work. Opus where tenant isolation,
authentication, authorization, concurrency, migrations on large tables, cache invalidation,
or release integrity is involved. The planner states the reason for each choice in the
implementation plan.

## 4. Process for one version

1. **Plan.** The planner writes the implementation plan after the previous version is merged,
   because later versions rewrite files that earlier ones change.
2. **Branch per package.** Each package gets `feat/v<version>-<package>` cut from the current
   `develop`, in its own worktree, with its own test database. Packages that touch the same
   files or carry migrations are placed in one chain and run in order. Independent chains run
   in parallel.
3. **Commit when stable.** The implementer commits each time a coherent step passes
   formatting, lint, type checks, and its targeted tests. The pre-commit hooks are never
   bypassed.
4. **Review.** The reviewer checks the branch against each item's "Done when", runs lint, the
   SQLite suite, the Postgres lane, coverage, and the contract and frontend checks that apply.
   A branch that fails review is not merged, and later packages in its chain do not start.
5. **Merge and delete.** One branch at a time: merge `develop` into the branch, rerun the
   suites, fast-forward `develop`, delete the branch, its worktree, and its test database.
   The next package in the chain is cut from the new `develop`.
6. **Integrate.** The release integrator runs every check on `develop`, including the full
   Playwright suite and the dependency audit, raises the coverage ratchets to the new measured
   values, and writes a status section into the implementation plan.

Rules that hold throughout:

- Nothing is pushed, tagged, or merged to `main` without the owner asking.
- No new production dependency, external service, or major upgrade without approval.
- Changes are additive and backward compatible; behaviour changes sit behind a setting whose
  default keeps current behaviour unless the spec says otherwise.
- Every changed line of application code has a test that executes it. Locking, index, RLS,
  and partition behaviour is tested on PostgreSQL.
- No measurement is written down unless the command that produced it was run.

## 5. Versions and what blocks them

### 0.4.0 — Data layer performance

Eight packages in four chains (see the implementation plan). All migrations are in one chain.
No approval needed. Limits: RLS strict mode stays off by default; converting existing large
tables to partitions is deferred to a tested procedure; no latency figures, only query counts
and query plans, because no load test can run without the integration stack.

### 0.5.0 — Chat pipeline and streaming

Thirteen items. The single pipeline (`R05-01`) comes first and alone, because it replaces the
WebSocket and HTTP paths in `chat.py`; everything else in the version builds on it.
Suggested chains: pipeline, sessions, streaming, latency (`R05-01` to `R05-04`); caches,
provider resilience, cost, routing, prompt-injection hardening (`R05-05` to `R05-09`);
frontend chat page split, streaming render, resilient connection (`R05-10`, `R05-11`,
`R05-13`).
Needs approval: `R05-12` rich answer rendering needs a markdown renderer dependency.
Cannot be verified locally: time-to-first-token and concurrent-stream targets.

### 0.6.0 — Ingestion and workers

Thirteen items. Staged ingestion (`R06-01`) comes first and alone, because it replaces
`document_tasks.py`. Then memory bounds, task limits, pools, dead-letter queues; embedding and
Qdrant work; keyword search; graph, connector, evaluation, and agent workers.
Needs a decision: the cross-encoder reranker, if it is taken up here.
Cannot be verified locally: anything that needs RabbitMQ, Qdrant, MinIO, or Neo4j running
(worker-kill chaos test, alias-swap reindex, queue isolation under load).

### 0.7.0 — Frontend performance

Twelve items, mostly independent, so four chains run in parallel: static pages and message
catalogue; code splitting, icons, fonts, images; generated API client and pagination;
push updates, route boundaries, token storage and server-side gate.
Needs approval: the field-measurement part of `R07-11`.
Depends on: `0.4.0` keyset pagination for `R07-06`, `0.5.0` event protocol for `R07-07`.

### 0.8.0 — Production infrastructure

Thirteen items. Most of this version is infrastructure that cannot be applied or verified
from a development machine. What can be done in the repository: manifests and configuration,
runbooks, backup and restore scripts with local tests, Prometheus multiprocess mode, alert
rules, and migration policy checks.
Needs decisions before planning: orchestrator (`R08-02`), managed Postgres (`R08-04`),
OpenTelemetry (`R08-10`).
Needs the owner or an operator: provisioning, DNS and TLS, secrets, restore drills, failover
tests, autoscaling tests.

### 0.9.0 — Product completeness

Ten items. Independent chains: verification, password reset, and MFA (no self-serve signup); bots and email
admin UI; public API documentation and deprecation policy; flag graduation; cost controls;
enterprise identity verification.
Needs decisions before planning: payment provider (`R09-03`), connector catalogue including
the Jira connector (`R09-06`).
Flag graduation (`R09-08`) depends on the accuracy gates and load baseline being green.

### 1.0.0 — General availability

Six items. Contract freeze, removal of deprecated behaviour, and the documentation pass can be
done in the repository. Performance sign-off needs a measured load baseline against the
`0.8.0` environment. The security review needs a reviewer outside the implementing team.
Operational readiness needs an on-call rota and a completed restore drill.

## 6. Open items carried forward

| Item | Needed from |
|---|---|
| Push `develop` and run the new GitHub workflows for the first time | Owner |
| Tag `v0.1.0` on `main`, then `v0.2.0` and `v0.3.0` | Owner |
| Branch protection for the required checks | Owner |
| Staging checks listed in the `0.2.0` and `0.3.0` implementation plans | Operator |
| Load-test baseline ([V0_3_0_LOAD_BASELINE.md](./V0_3_0_LOAD_BASELINE.md) is not yet measured) | Operator, integration stack |
| Real-backend Playwright suite, never run | Integration stack |
| Decisions in the master plan section on open decisions | Owner |

## 7. Failure Modes and Recovery

| Failure | Recovery |
|---|---|
| A run is interrupted | Work is on package branches in worktrees; rerun resumes from the last finished step and each implementer continues from its branch. |
| Review fails for a package | The branch stays unmerged and is reported; later packages in the chain wait. |
| Merge conflict needs a design decision | The merge is aborted, the branch is kept, and the conflict is reported. |
| Two Alembic heads after a merge | The later branch re-points its migration to the current head before landing. |
| A gate on `develop` turns red | The release integrator fixes it on `fix/v<version>-integration` before the version is declared done. |

## 8. Change Notes

- 2026-11-27: Initial version.
- 2026-11-27: The `0.5.0` row points at its implementation plan.
- 2026-11-27: Status after `0.4.0` and `0.5.0`; coverage figures updated.
- 2026-11-27: The `0.6.0` row points at its implementation plan.
- 2026-11-27: `0.6.0` status after seven packages merged; coverage figures updated.
- 2026-11-27: `0.6.0` implemented on `develop`; coverage figures updated.
- 2026-11-27: The `0.7.0` row points at its implementation plan.
- 2026-11-28: `0.7.0` implemented on `develop`; coverage figures updated.
- 2026-11-28: The `0.8.0` row points at its implementation plan.
- 2026-11-28: The `0.9.0` row points at its implementation plan.
