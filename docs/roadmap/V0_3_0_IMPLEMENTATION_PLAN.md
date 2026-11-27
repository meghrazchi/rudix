# v0.3.0 — Detailed Implementation Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [V0_3_0_TEST_AND_RELEASE_FOUNDATION.md](./V0_3_0_TEST_AND_RELEASE_FOUNDATION.md),
  [V0_2_0_IMPLEMENTATION_PLAN.md](./V0_2_0_IMPLEMENTATION_PLAN.md),
  [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../14_GITHUB_ACTIONS_CI_CD_PIPELINE.md](../14_GITHUB_ACTIONS_CI_CD_PIPELINE.md)

## 1. Purpose

Turn the `0.3.0` spec into steps with exact files, symbols, tests, and ownership of shared files.
Every reference below was read on `develop` at `adc824a` (all of `0.2.0` merged, not yet
tagged). Line numbers drift; search for the quoted symbol if a line does not match.

The work runs as four parallel chains in one working tree, so section 4 assigns an owner and an
anchor to every file that more than one item touches.

## 2. Plan check: what the code review confirmed or changed

| Item | Result |
|---|---|
| R03-01 | **Partly done by R02-15.** `pg_session`/`pg_session_factory` exist in `tests/conftest.py`, five `requires_postgres` files exist, and the lane runs as one step of the `backend-alembic` job. The fixture only *checks* `alembic_version`; `make test-postgres` migrates. Keyword-retrieval tests are all mocks and `plainto_tsquery`/`ts_rank` cannot run on SQLite, so FTS needs a new Postgres-only test. |
| R03-02 | Confirmed. 4,512 tests, 4 to 6.5 minutes locally; `db_session` runs `create_all` per test (two more module-local copies in `test_guardrails_f145.py` and `test_safety_eval_f146.py`). `main.py` mounts `api_router` three times when `ENVIRONMENT=test`. A probe that removed the two aliases failed **1,159 tests in 115 files**: "mount once" is a mechanical test migration, not a one-line change. Frontend has `@vitest/coverage-v8` installed but no coverage config. |
| R03-03 | **Changed.** The three workflows are manual only, and `accuracy_eval_runner.py` and `quality_gate_runner.py` call a *deployed* API with secrets, so they cannot test a pull request's code. PR smoke becomes a deterministic in-process suite over pinned fixtures with stubbed providers (as the spec's failure-modes section asks); the live model runs nightly against staging. `docs/14` claims a nightly schedule that does not exist. Path-filtered workflows leave required checks pending, so gating uses job-level change detection. |
| R03-04 | Confirmed. The integration compose has no frontend and no LLM stub. Frontend images bake staging or production URLs at build time, so the e2e run builds the frontend on the runner. |
| R03-05 | Confirmed. `pip install .` from ranges. `uv` approved. uv-created virtualenvs have no `pip`, which breaks `security.yml` (`.venv/bin/pip install pip-audit`) and pip-audit's environment mode; the Makefile becomes the only install and audit entry point. |
| R03-06 | Confirmed. Root user, no `HEALTHCHECK`, tag-pinned bases, one runtime with Tesseract and Poppler. OCR runs only in the worker (`document_tasks.py` → `ocr_service.run_ocr`). Frontend runtime runs a second `npm ci` and `npm start`. |
| R03-07 | **Changed.** A `v*` tag rebuilds all images; `deploy-production` needs build and smoke, not staging. On a tag push the staging job is not part of the run, so production cannot `needs` it directly: a `verify-staged` job checks a `staging-passed-<sha>` tag instead. The production **frontend** image cannot equal the staging digest (URLs are baked in): the release promotes the `frontend-production` image built in the same `main` run; digest equality is required for `api` and `worker`. Terraform state is local and discarded per CI run. The version lives in seven places (see B2). `docs/CHANGELOG.md` `[Unreleased]` holds the untagged `0.2.0` entries. |
| R03-08 | **Changed.** `pip-audit` only warns. `security_severity_gate.py` reads GitLab report files nobody produces; pip-audit JSON has no severity field. The gate is wired with Trivy and pip-audit adapters (pip-audit findings count as high unless allowlisted). `npm audit --audit-level=high` fails today on 7 transitive dev-tool advisories; production dependencies have none, so the blocking gate uses `--omit=dev`. The local venv's pip-audit shows `cryptography` fixed only in `50.x`, outside the `<50` range: needs a decision. CSP enforcement moves to D1 because D1 owns the same file. |
| R03-09 | Confirmed. Also: no DB pool or per-request query metrics exist, so they are added. Locust has no WebSocket client; use `websockets.sync.client` (already installed through `uvicorn[standard]`). |
| R03-10 | **Changed.** `frontend/openapi.json` is a curated 38-path, 101-schema subset that already differs from the export (407 paths, 749 schemas). `backend/scripts/export_openapi.py` and `npm run api:update-schema` exist. The export reads `.env` files and triples routes when `ENVIRONMENT=test`. Plan: commit the full export, compare parsed JSON, format with Prettier. |
| 0.2.0 follow-ups | Scope-inventory answers (`_build_scope_inventory_result`, `chat.py:887`) list and cite documents without the `Action.cite` check that normal retrieval applies. The contact form's captcha is a typed token today (no widget script), so CSP hosts are added only for a known provider name. `next` is at 16.4.3 with advisories; 16.4.x patches exist. |

## 3. Sequence

| Chain | Order | Task | Items | Model |
|---|---|---|---|---|
| A | 1 | A1 | R03-01 Postgres lane | opus |
| A | 2 | A2 | R03-02 speed and coverage | opus |
| B | 1 | B1 | R03-03 gates, R03-10 OpenAPI contract | opus |
| B | 2 | B2 | R03-08 security, R03-07 release | opus |
| C | 1 | C1 | R03-09 load harness and DB metrics | opus |
| C | 2 | C2 | R03-05 uv lockfile | sonnet |
| C | 3 | C3 | R03-06 hardened images | opus |
| D | 1 | D1 | Next.js patch, CSP hosts and enforce flag, scope-inventory cite filter | sonnet |
| D | 2 | D2 | R03-04 integration e2e and LLM stub | opus |

Cross-chain contracts (section 4.2) let every task land without waiting for another chain. A2
measures coverage last in its chain; the release verification re-measures on the merged tree.

## 4. Shared files

### 4.1 Owners and anchors

Every task re-reads a shared file immediately before editing it and edits only its anchor.

| File | Task: anchor |
|---|---|
| `.github/workflows/ci.yml` | A1: job `backend-alembic` (rename, delete the step `Run PostgreSQL and Redis marked tests`). A2: job `frontend`, step `Run frontend tests`. B1: the `on:` block only. B2: job `validate`, step `Setup Terraform` only if needed. |
| `.github/workflows/release.yml` | B1: new job `quality-gate` inserted before the `deploy-staging:` key, and `- quality-gate` in its `needs`. B2: everything else, including D2's job. No other task edits it. |
| `.github/workflows/security.yml` | B2 only. |
| `playwright.yml`, `accuracy-eval.yml`, `quality-gate.yml` | B1 only. |
| New workflows | A1 `backend-postgres.yml`; B1 `accuracy-smoke.yml`, `openapi-contract.yml`; B2 `image-scan.yml`, `secret-scan.yml`, `.github/dependabot.yml`; D2 `e2e-integration.yml`. |
| `backend/pyproject.toml` | A1: none. A2: append `[tool.coverage.run]`/`[tool.coverage.report]` at end of file. B1: marker line after `"requires_redis: ..."`. C1: new extra `load = [...]` after the `dev = [...]` list. C2: `[tool.uv]` after `[tool.hatch.build.targets.wheel]`. B2: none (the bump script edits `version` at release time only). |
| `backend/tests/conftest.py` | A1, then A2. Nobody else. |
| `backend/Makefile` | A1: `test-postgres`. A2: new `test-cov`. C2: `install`, `audit`, new `audit-report`, `lock`, `PIP` variable. C1: new `load-*` targets appended at end. |
| Root `Makefile` | C1 only: targets appended after `eval-nightly`. |
| `backend/Dockerfile` | C2, then C3. |
| `frontend/Dockerfile`, `frontend/next.config.ts` | C3 only. |
| `frontend/package.json` | A2: `"test:coverage"` after `"test:watch"`. B1: the `"api:update-schema"` line. D2: `"test:e2e:integration"` after `"test:e2e"`. D1: `next` and `eslint-config-next` versions. |
| `frontend/package-lock.json` | D1 only. |
| `frontend/vitest.config.ts` | A2 only. `playwright.config.ts`: nobody (D2 adds `playwright.integration.config.ts`). |
| `frontend/config/security-headers.mjs` (+ test) | D1 only. |
| Compose files | C3: `docker-compose.yml` build targets, staging and production compose. D2: new `deploy/compose/docker-compose.integration-stub.yml`. Integration compose: nobody. |
| `deploy/scripts/*`, `deploy/terraform/*` | B2 only. |
| `docs/CHANGELOG.md` | One line per task, inserted directly after the anchor line that starts with: A1 "- `backend/README.md` and `docs/14_GITHUB"; A2 "- `docs/DOCUMENT_TEMPLATE.md`"; B1 "- `docs/DOCUMENT_REVIEW_CHECKLIST.md`"; B2 "- Deployment fixes:" (B2 also rewrites line 3); C1 "- Celery `beat` service"; C2 "- Atomic document processing claim"; C3 "- Security headers:"; D1 "- Frontend production-like builds"; D2 "- Production retrieval filters". |
| `docs/14_GITHUB_ACTIONS_CI_CD_PIPELINE.md` | A1: new `### backend-postgres.yml` before `### playwright.yml`, and the `ci.yml` text. A2: coverage in `### ci.yml`. B1: `### playwright.yml`, `### quality-gate.yml`, `### accuracy-eval.yml`; new `### accuracy-smoke.yml`, `### openapi-contract.yml` before `## CI Inputs`; new `## Required status checks` before `## Notes`. B2: `### security.yml`, `### release.yml`, new subsections before `### release.yml`, and the secrets sections. D2: new `### e2e-integration.yml` before `### quality-gate.yml`. |
| `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` | D1: `## Security headers`. B2: `## Secrets`, `### Deployment`, new `## Supply chain and release integrity` before `## Logging safety`. C2 creates `## Reproducible builds and container hardening` before `## Production checklist`; C3 appends to it. |
| `docs/12_EVALUATION_AND_MONITORING.md` | B1: `## Continuous evaluation`. C1: new `## Load testing and performance baseline` before `## Continuous evaluation`. |
| `docs/10_DEPLOYMENT_DOCKER.md` | C2: `## Backend requirements`. C3: `## Backend Dockerfile`, `## Frontend deployment`. |
| `DEPLOYMENT.md` | B1: `## 11. Set Up Accuracy Evaluation`. B2: `## 6. Add GitHub Secrets`, `## 8.`, `## 13. Rollback`. |
| `backend/README.md` | A1: `## PostgreSQL integration tests`. A2: new `## Test speed and coverage` before `## Useful task commands`. B1: `## OpenAPI schema export`. C2: `## Development commands`. |
| `frontend/README.md` | A2: new `### Coverage` right after the `## Testing` heading. B1: `## API type generation`. D1: `### Security headers`. D2: new `### Integration E2E` before `## Responsive / Supported Viewports`. |
| `README.md` | B2: `## Deployment and CI/CD`. C2: `### Backend Commands`. |
| `docs/26_...` | B2: section 4.1. C1: section 4.6. |
| `docs/README.md` | C1: one line after the `V0_3_0_IMPLEMENTATION_PLAN.md` line. |

### 4.2 Contracts between chains

1. **LLM stub (D2 owns).** `ci/stubs/llm_stub.py`, standard library only. `GET /health`,
   `GET /v1/models`, `POST /v1/chat/completions`, `POST /v1/embeddings`. Environment:
   `STUB_LLM_PORT` (8080), `STUB_LLM_LATENCY_MS` (0), `STUB_LLM_LATENCY_JITTER_MS` (0),
   `STUB_EMBEDDING_DIM` (1536). Overlay `deploy/compose/docker-compose.integration-stub.yml`
   adds service `llm-stub` and points `api` and `worker` at it (`LLM_DEFAULT_PROVIDER=local`,
   `LOCAL_LLM_BASE_URL`, `LOCAL_EMBEDDING_BASE_URL`, `OPENAI_BASE_URL`, all
   `http://llm-stub:8080/v1`). C1 uses it by these names only.
2. **E2E reusable workflow (D2 owns the file, B2 wires it).** `.github/workflows/e2e-integration.yml`,
   `on: workflow_call` with required string inputs `api_image` and `worker_image`, plus
   `workflow_dispatch`. B2 adds job `e2e-integration` (`needs: build-images`) to `release.yml`
   and adds it to `deploy-staging.needs`.
3. **Quality gate (B1).** `quality-gate.yml` gains `workflow_call`; `release.yml` job
   `quality-gate` runs before `deploy-staging`.
4. **Backend image targets (C3 defines, B2 consumes).** `backend/Dockerfile` stages `api` and
   `worker`; `worker` is the last stage so an untargeted build stays complete. B2 builds
   `--target api` and `--target worker`.
5. **Install and audit (C2 defines, B2 consumes).** `make -C backend install` stays the only
   install command and keeps `backend/.venv`. `make -C backend audit-report
   AUDIT_OUTPUT=<abs path>` writes pip-audit JSON for the locked set.
6. **Check names (B1 documents).** `Validate config`, `Backend lint and tests`,
   `Backend Alembic validation`, `Backend PostgreSQL tests`, `Frontend quality checks`,
   `Frontend Playwright`, `Accuracy smoke`, `OpenAPI contract`, `Backend dependency audit`,
   `Frontend dependency audit`, `Filesystem vulnerability scan`, `Secret scan`, `Image scan`.

## 5. Steps per item

### R03-01 — Postgres test lane (A1)

1. `tests/conftest.py`: session-scoped sync fixture `pg_migrated_url` runs
   `sys.executable -m alembic upgrade head` in a subprocess from `backend/` with
   `DATABASE_URL=TEST_DATABASE_URL` (env.py reads `settings.database_url` and calls
   `asyncio.run`, so it cannot run in-process inside the test loop). `pg_engine` depends on it.
2. Dual-dialect porting: marker `both_dialects`; `pytest_generate_tests` parametrizes
   `db_backend` (`sqlite`, `pytest.param("postgres", marks=requires_postgres)`) for tests that
   use `db_session`; `db_session` returns the SQLite session or a `pg_session`-style rolled-back
   session. A suite is ported by adding the marker to its `pytestmark`.
3. Port, in order: `test_rag_isolation_f144.py`, `test_tenant_isolation_f336.py`,
   `test_index_version_isolation.py`, `test_chat_transport_parity.py`, `test_quotas_f154.py`,
   `test_quota_atomic.py`, `test_document_processing_claim.py`. New
   `test_keyword_retrieval_fts_pg.py` (Postgres only): ranking, org filter, document filter,
   `index_version` filter.
4. New `.github/workflows/backend-postgres.yml`, job `Backend PostgreSQL tests`, no `paths`
   filter, Postgres 16 and Redis 7 services, `make -C backend test-postgres`.
5. Done when: the four suites run on Postgres in the new job. Making it required is manual.

### R03-02 — Faster and measured suite (A2)

1. Measure `make test` wall time twice before any change.
2. Schema once: a session-scoped template SQLite file built with `create_all`, copied per test
   into `tmp_path`, same `to_tsvector` registration and `StaticPool`. Savepoint isolation only
   if it is measurably faster and stable; otherwise revert it.
3. Mount once: delete the `ENVIRONMENT == "test"` alias block in `app/main.py` and move the
   1,159 tests to `settings.api_prefix` paths.
4. Coverage: measure, then set `fail_under` (backend) and `coverage.thresholds` (Vitest) to the
   measured figures rounded down to one decimal.

### R03-03 and R03-10 — Gates and OpenAPI contract (B1)

1. Playwright on all PRs and `main`, with a `changes` job; `Frontend Playwright` runs only when
   `frontend/` changed (a skipped job satisfies a required check).
2. `accuracy-smoke.yml` runs `pytest -m accuracy_smoke` when chat, retrieval, prompt, AI, RAG
   profile, or config paths change. Suite: `tests/test_accuracy_smoke.py` plus
   `tests/fixtures/accuracy_smoke/`. It runs the real HTTP chat pipeline with deterministic
   fake embeddings, Qdrant, and LLM, and checks the results against the `smoke` thresholds in
   `ci/config/accuracy_eval_thresholds.yml`. It catches pipeline regressions, not model quality.
3. `accuracy-eval.yml`: nightly `schedule`. `quality-gate.yml`: `workflow_call`;
   `quality_gate_runner.py` accepts `EVALUATION_RUN_ID=latest` (newest completed run for
   `ACCURACY_EVAL_SET_ID` from `GET /evaluations/runs`, rejected if older than
   `QUALITY_GATE_MAX_RUN_AGE_HOURS`, default 36). The release `quality-gate` job runs the smoke
   at the commit, then the F149 gate on the latest staging nightly run.
4. `ci.yml` `on:` loses its `paths` lists so required checks always report.
5. OpenAPI: `export_openapi.py` forces `ENVIRONMENT=development` and `API_PREFIX=/api/v1`,
   gains `--check PATH` (compares parsed JSON, prints added, removed, and changed paths). New
   `openapi-contract.yml`. `api:update-schema` runs Prettier on `openapi.json`. Commit the full
   export and the regenerated `schema.d.ts`, and fix type errors in its four consumers.

### R03-08 and R03-07 — Security pipeline and release (B2)

1. `secret-scan.yml` (gitleaks CLI, pinned version and checksum, `.gitleaks.toml` allowlisting
   only the known placeholders); `npm audit --omit=dev --audit-level=high` blocking, full audit
   as an artifact; pip-audit through `make -C backend audit-report` and the severity gate;
   `image-scan.yml` and a release `scan-images` job with Trivy; `.github/dependabot.yml`.
2. `security_severity_gate.py`: CLI `--trivy`/`--pip-audit` report paths, Trivy severities,
   pip-audit counted as high, allowlist entries need `reason` and `expires`.
3. `scripts/bump_version.py` with `--check` and `--changelog`, and
   `scripts/extract_release_notes.py`.
4. `release.yml`: no rebuild on tags; `build-images` (two backend targets, buildx SBOM and
   provenance, cosign keyless signing, digests from `--metadata-file`); `scan-images`;
   `e2e-integration`; B1's `quality-gate`; `deploy-staging`, which tags `staging-passed-<sha>`;
   on tags `verify-staged` → `deploy-production` (cosign verify, digest equality) →
   `github-release`. The rollback dispatch takes `environment` and `version` and keeps the old
   image inputs as a fallback.
5. `deploy/scripts/ssh_common.sh` writes the pinned `*_SSH_KNOWN_HOSTS` and uses
   `StrictHostKeyChecking=yes`; Terraform `connection.host_key`; `backend "s3" {}` with partial
   configuration; new `deploy/scripts/rollback.sh <environment> <version>` with the database
   downgrade policy.

### R03-09 — Load harness (C1)

`ci/load/` Locust package with five scenarios, `collect_metrics.py`, and `README.md`.
`app/core/db_metrics.py` adds `rudix_db_queries_per_request` and pool gauges.
`docs/roadmap/V0_3_0_LOAD_BASELINE.md` is marked "not yet measured".

### R03-05 — uv lockfile (C2)

`backend/uv.lock` (hashes), the Makefile through uv, and the Dockerfile builder using
`uv sync --frozen --no-dev --no-editable`. Two builds produce identical `pip freeze` output.

### R03-06 — Hardened images (C3)

Digest-pinned bases, `api` and `worker` targets, non-root, `HEALTHCHECK`, standalone frontend
running `node server.js`, compose limits, `stop_grace_period`, log rotation, and worker and
frontend healthchecks.

### D1 — Next.js patch and 0.2.0 follow-ups

`next` and `eslint-config-next` upgraded to the latest `16.x` patch, plus `npm audit fix` without
`--force`. CSP: the contact submit origin in `connect-src`, a known-provider captcha host map, and
`NEXT_PUBLIC_CSP_ENFORCE` (default `false`). The scope inventory filters its first chunks through
`filter_chunks_by_cite_access` on both transports.

### R03-04 — Integration e2e (D2)

LLM stub and overlay (contract 1), `playwright.integration.config.ts`,
`e2e-integration/critical-path.spec.ts` (skipped unless `RUDIX_E2E_INTEGRATION=1`), and the
reusable workflow (contract 2).

## 6. Verification for the release

Run on the merged tree:

```bash
cd backend && make lint && make test && make test-cov
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://... make test-postgres
cd backend && .venv/bin/python scripts/export_openapi.py --check ../frontend/openapi.json
cd frontend && npm run typecheck && npm run lint && npm run test:coverage && npm run build
cd frontend && npm run test:e2e
python3 scripts/bump_version.py --check
```

If merged coverage is below a ratchet, record the merged figure and set the threshold to it in
the release MR, with the reason. Then, on GitHub and staging (manual):

1. Mark the checks in section 4.2 item 6 as required on `main`.
2. Push a branch with a seeded fake secret; `Secret scan` fails. Delete the branch.
3. Provision the Terraform state bucket and add host-key and state secrets (see `DEPLOYMENT.md`).
4. Merge to `main`: `quality-gate`, `e2e-integration`, `scan-images`, and staging deploy pass.
5. Tag `v0.2.0` first if not done, then run `scripts/bump_version.py 0.3.0 --changelog`, merge,
   and tag `v0.3.0`. The production `api` and `worker` digests equal the staging ones, `cosign
   verify` passes, and the GitHub Release has the changelog section.
6. Run the load baseline and fill `V0_3_0_LOAD_BASELINE.md`, then revise
   `docs/26` section 4.6.

## 7. Change Notes

- 2026-11-26: Initial version, written after checking the `0.3.0` spec against the code at
  `adc824a`.
