# v0.3.0 — Test and Release Foundation

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../14_GITHUB_ACTIONS_CI_CD_PIPELINE.md](../14_GITHUB_ACTIONS_CI_CD_PIPELINE.md)

## 1. Purpose

Make it safe to refactor. After this version, tests exercise the real database, the existing
quality gates block merges, builds are reproducible, and a release is a signed, promoted
artifact with a version number.

## 2. Work items

### R03-01 — Postgres test lane (L)

- **Problem:** All backend tests run on in-memory SQLite with JSONB and TSVECTOR shims. The
  `requires_postgres` and `requires_redis` markers exist but no test uses them. Row-level
  security, indexes, FTS, and locking are untested.
- **Change:**
  - Extend the minimal job from `R02-15` into its own required CI job that runs
    `pytest -m "requires_postgres or requires_redis"` against Postgres 16 and Redis.
  - The fixture creates the schema with `alembic upgrade head`, not `create_all`, so
    migrations are what gets tested.
  - Each test runs in a transaction that is rolled back.
  - Mark and port tests in this order: tenant isolation (F144), quota, keyword retrieval,
    document claim (`R02-02`), then anything using `FOR UPDATE` or JSONB operators.
- **Done when:** At least the isolation, quota, FTS, and claim suites run on Postgres in CI,
  and the job is required for merge.

### R03-02 — Faster and measured test suite (M)

- **Change:**
  - Build the SQLite schema once per session and isolate tests with savepoints instead of
    running `create_all` for 118 tables per test.
  - Mount the router once in test runs (`main.py:50-56` mounts it three times).
  - Add coverage thresholds as a ratchet: record the current figure, fail when it drops.
    Backend in `pyproject.toml`, frontend in `vitest.config.ts`.
- **Done when:** CI prints coverage for both sides and fails on a decrease.

### R03-03 — Gates that gate (M)

- **Problem:** Playwright, accuracy-eval, and quality-gate workflows run only on manual
  dispatch.
- **Change:**
  - Playwright: run on pull requests that touch `frontend/` and on `main`.
  - Accuracy smoke (F302): run on pull requests that touch `backend/app/domains/chat`,
    retrieval, prompts, or RAG settings. Full run nightly.
  - Quality gate (F149): required on `main` before the staging deploy job.
- **Done when:** Branch protection lists the three checks as required.

### R03-04 — End-to-end against the real backend (M)

- **Problem:** Playwright runs against `npm run dev` with fake local auth.
- **Change:** Add a second Playwright project that runs a small critical-path suite against
  the integration compose stack: log in, upload, wait for `indexed`, ask, see a citation.
  Use a stubbed LLM provider through the existing OpenAI-compatible adapter so the run is
  deterministic.
- **Done when:** The suite runs in the release workflow before the staging deploy.

### R03-05 — Reproducible Python builds (S, needs approval)

- **Problem:** The backend image runs `pip install .` from version ranges with no lockfile.
- **Change:** Generate a hashed lockfile and install from it in the Dockerfile and CI.
  Tool choice is an open decision in the master plan.
- **Done when:** Two builds of the same commit produce the same installed package set.

### R03-06 — Hardened images (M)

- **Change:**
  - Backend: non-root `USER`, `HEALTHCHECK`, base image pinned by digest. Split Tesseract and
    Poppler into a worker-only stage so the API image is smaller.
  - Frontend: `output: "standalone"`, non-root user, run `node server.js`, drop the second
    `npm ci` in the runtime stage.
  - Add resource limits, `stop_grace_period`, and log rotation to production compose
    services, and healthchecks for worker and frontend.
- **Done when:** Trivy image scan (see `R03-08`) passes and containers run as non-root.

### R03-07 — Versioned release process (M)

- **Change:**
  - Add `scripts/bump_version.py` that sets the version in both manifests.
  - `release.yml`: a `v*` tag promotes the image **digest** that passed staging. It does not
    rebuild. The production job `needs` the staging job.
  - Create a GitHub Release from the tag with notes taken from `docs/CHANGELOG.md`.
  - Extend `docs/CHANGELOG.md` to cover product changes per version, not only docs.
  - Generate an SBOM and sign images.
  - Rollback script accepts an environment and a version, and documents when a database
    downgrade is and is not safe.
  - Replace `StrictHostKeyChecking=no` with a pinned host key. Move Terraform state to a
    remote backend.
- **Done when:** `v0.3.0` is released by tag, and the production image digest equals the
  staging one.

### R03-08 — Security pipeline (M)

- **Change:** Add secret scanning, `npm audit` at high severity, Trivy scans of the built
  images, and automated dependency update pull requests. Make `pip-audit` fail on high
  severity. Wire the existing `ci/scripts/security_severity_gate.py` and its allowlist into
  `security.yml`, or delete them. Enforce the CSP from `R02-09`.
- **Done when:** A seeded test secret in a branch fails CI.

### R03-09 — Load-test harness and first baseline (M, needs approval)

- **Problem:** There are no load or performance tests, so no target in the master plan is
  measured.
- **Change:** Add `ci/load/` with scenarios: chat over WebSocket, chat over HTTP, document
  list, upload and ingest, admin dashboard. Run against the integration stack with the
  stubbed LLM, with a configurable artificial model latency. Record p50, p95, error rate,
  DB pool usage, and queries per request.
- **Done when:** A baseline report is committed under `docs/roadmap/` and the targets in the
  master plan section 4.6 are revised against it.

### R03-10 — OpenAPI contract check (S)

- **Problem:** `frontend/openapi.json` covers 38 paths and CI only checks it against the
  generated types, not against the backend.
- **Change:** Add a backend command that exports the live OpenAPI document. CI fails when the
  committed `frontend/openapi.json` differs from the export.
- **Done when:** A backend schema change without a regenerated frontend file fails CI.
  (`R07-05` then migrates clients to the generated types.)

## 3. Exit criteria

- Required checks on `main`: lint, type check, SQLite tests, Postgres tests, frontend tests,
  build, Playwright, accuracy smoke, security scans, OpenAPI contract.
- `v0.3.0` is released by tag with a signed image and a GitHub Release.
- A measured performance baseline exists.

## 4. Failure Modes and Recovery

- Postgres tests are slower than SQLite tests. Keep the SQLite lane for fast feedback and run
  the Postgres lane in parallel.
- The accuracy smoke can be flaky with a live model. Run it against pinned fixtures and a
  stubbed provider on pull requests, and the live model nightly.

## 5. Security Considerations

Secret scanning and signed images are new controls. Record them in
`docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md`.

## 6. Change Notes

- 2026-11-26: Initial version.
