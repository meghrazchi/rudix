# v0.9.0 — Detailed Implementation Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Planned (no package started)
- `Last Updated`: 2026-11-28
- `Related Docs`: [V0_9_0_PRODUCT_COMPLETENESS.md](./V0_9_0_PRODUCT_COMPLETENESS.md),
  [V0_8_0_IMPLEMENTATION_PLAN.md](./V0_8_0_IMPLEMENTATION_PLAN.md),
  [01_EXECUTION_PLAN.md](./01_EXECUTION_PLAN.md),
  [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../07_API_DESIGN.md](../07_API_DESIGN.md),
  [../11_SECURITY_AND_PRODUCTION_CHECKLIST.md](../11_SECURITY_AND_PRODUCTION_CHECKLIST.md),
  [../22_AUTHORIZATION_SYSTEM.md](../22_AUTHORIZATION_SYSTEM.md)

## 1. Purpose

Turn the `0.9.0` spec (`R09-01` to `R09-10`), three items carried over from `0.5.0` and `0.7.0`
(rich answer rendering, the official Sentry SDK, automated accessibility checks), and the open
points of the `0.8.0` Status section into nine work packages with exact files, shared-file
anchors, migrations, tests, and owners. Every reference was read on `develop` at `05e5b5c0`
(`0.2.0` to `0.8.0` merged, not tagged). Line numbers drift; search for the quoted symbol.

Evidence rule: no gate result, latency, cost per question, deliverability, or identity-provider
result is written down unless the command that produced it ran. Accuracy and safety gates run
here only against the stub LLM (`ci/stubs/llm_stub.py`); that is a plumbing check, not
graduation evidence. Payments, email delivery, identity providers, and staging are operator
steps (section 8).

## 2. Decisions taken

The owner asked for the roadmap to run to the end, taking the recommended option where a
decision is open.

| Decision | Option taken | Why | Fallback that remains |
|---|---|---|---|
| Self-serve signup (`R09-01`) | Out of scope (owner, 2026-11-27): no `POST /auth/register`, `/signup` keeps redirecting to `/login`, no trial calls to action. Exit criterion "a new user can sign up" is read as "an invited user can accept, verify, and sign in" | Accounts come from invitations, SCIM, and SSO | Revisit with the owner after `1.0.0` |
| Proof of mailbox | Accepting an invitation sets `users.email_verified_at` (the token arrived by email); verification emails serve users whose address was never proven (SCIM or admin-created without acceptance, legacy, auto-provisioned) | No second email right after the invitation | `POST /auth/resend-verification` for anyone |
| Verification enforcement | `AUTH_EMAIL_VERIFICATION_REQUIRED=false` (current behaviour); when true, users created before `AUTH_EMAIL_VERIFICATION_ENFORCED_FROM` count as verified | Existing users keep signing in | Leave it off |
| Recovery mail path | `forgot-password` and `resend-verification` only rate-limit and enqueue; the worker looks the user up, mints the token, and sends through `EmailService` | Same response and handler time whether or not the email exists; the raw token never enters the broker, task arguments, `FailedJob`, or logs | — |
| Breach check | `AUTH_PASSWORD_BREACH_CHECK=off` (default) or `local_list` (bundled common-password list, file path setting) | An online range API is a new external service | Deferred: online check needs approval |
| Payments (`R09-03`) | Stripe behind a provider-neutral `PaymentProvider` port; HTTPS API through `httpx`, webhook signatures with `hmac`/`hashlib`; no SDK dependency; `BILLING_PROVIDER=none` default | Recommended; no new dependency; another provider is one adapter | `none` keeps usage-derived invoices and manual plan assignment |
| Plan catalogue | Table `billing_plans` (quota limits, stage limits, provider price ids) imported by `scripts/billing_plans.py` from JSON | No plan concept exists; quotas are per-organisation JSON | Manual `OrgQuotaPolicy` edits, as today |
| Webhooks | Verify signature and timestamp (`BILLING_WEBHOOK_TOLERANCE_SECONDS=300`), dedupe on `(provider, event_id)`, apply inline, ignore events older than the stored state; beat reconciliation job repairs drift | Idempotent, replay-safe, no lost state | Reconciliation alone restores state |
| Failed payment | `past_due` plus `BILLING_GRACE_PERIOD_DAYS=7`, then downgrade to `BILLING_FALLBACK_PLAN_KEY` limits | Spec | Unset fallback key: limits stay, status shows `past_due` |
| MFA (`R09-02`) | TOTP (RFC 6238, SHA-1, 6 digits, 30 s, ±1 step) with the standard library; secret encrypted with `CredentialCipher` (`AUTH_MFA_ENCRYPTION_KEY`, falling back to the connector credential key); recovery codes HMAC-hashed and single-use; QR with `qrcode.react` (approved, loaded on demand) plus the secret as text | No backend dependency | WebAuthn post-1.0 (spec) |
| Login contract | `POST /auth/login` returns `AuthSessionResponse` unchanged for users without a factor, and `AuthMfaChallengeResponse` (`mfa_required: true`, challenge token) otherwise; `POST /auth/mfa/verify` completes the login | Additive for every existing user and client | — |
| Session rules | Confirming a factor revokes the user's other sessions; refresh needs an MFA-verified session when the user has a factor; org policy after the grace period blocks refresh, login, and organisation switching for members without a factor; SSO sessions defer to the IdP; API keys and service accounts are unaffected | No login path skips the challenge | `mfa_required` stays false by default |
| Step-up | Single-use 5-minute token from `POST /auth/mfa/step-up`, sent as `X-Rudix-Step-Up`; `AUTH_STEP_UP_MODE=mfa_enrolled` (users with a factor must step up for API key creation, role changes, SSO configuration, MFA changes) | Users without a factor keep today's behaviour | `off` |
| MFA lockout | Owner resets a member's MFA (owner's own step-up, audit record, sessions revoked, security email); `scripts/reset_user_mfa.py` for a sole owner, audit-logged | Spec failure mode | Recovery codes |
| SAML validation (`R09-10`) | In-house XML signature and assertion validation with `lxml` and `cryptography` (both installed); `SSO_SAML_REQUIRE_SIGNATURE=true` by default, settable false only in development and test | Security fix: overrides the compat default; validation was incomplete | Replace with a maintained SAML library after approval (deferred) |
| SSO callback | No access token in the redirect URL (`SSO_CALLBACK_TOKEN_IN_URL=false`); the callback page refreshes with the cookie; `true` kept one release | Tokens in URLs reach logs and history | Legacy flag, removed in `1.0.0` |
| Connector catalogue (`R09-06`) | Fallback: remove the placeholder cards and entries; Jira is not restored | No option recommended; lower risk | Jira on the provider SDK is a post-1.0 candidate |
| Rich answers (`R05-12`) | `react-markdown` only (no raw HTML by default), safe link schemes, no images, citations kept, loaded on demand; `NEXT_PUBLIC_CHAT_RICH_ANSWERS` default on only if C2's criteria pass (section 6) | Approved; one renderer that sanitises by default | Plain text (`off`); tables (GFM plugin) deferred |
| Sentry SDK (`R07-11`) | `@sentry/browser` loaded on demand; `NEXT_PUBLIC_SENTRY_CLIENT=sdk` (default) or `legacy` for one release; same DSN, off without it, no replay, no PII, scrubbed by `redaction.ts` | Approved | `legacy` hand-rolled client |
| Accessibility (`R07` carry-over) | `@axe-core/playwright` (dev) on main public and app pages; serious and critical fail; `e2e/a11y-allowlist.json` with reasons | Approved | — |
| Public API (`R09-07`) | `docs/api/openapi.public.json` generated with an explicit audience per route (test fails on an unclassified route); SDK = generated TypeScript types in `sdk/typescript/` | No runtime client dependency approved | Runtime client deferred |
| Deprecation | `Deprecation` (RFC 9745) and `Sunset` (RFC 8594) headers plus `Link rel="deprecation"`; the two scaffold 501 routes are marked deprecated; avatar upload without storage returns 503 | Exit criterion: no 501 outside deprecated routes | — |
| Flag graduation (`R09-08`) | Decision table with existing evidence; flip only plumbing flags with tests (candidate `chunking_profiles`); `mcp` and `org_memory` keep opt-in; `chat_tool_orchestration` experimental; quality-sensitive flags "graduate after staging gates"; deprecation notes only | No real gate or load evidence here | Per-organisation override back to off |
| Plan stage limits (`R09-09`) | `org_quota_policy.stage_limits` (null = everything allowed, as today), enforced in a pipeline stage gate and by the token ledger; the plan wins over flags, profiles, and AI policy | Server-side guarantee | — |
| Shared foundation | All migrations, the one-time token model, settings modules, anchors, empty message namespaces, the approved frontend dependencies, and the hermetic test guard in S1 | Chains then never touch migrations or lockfiles | — |
| Package count | Nine; D1 joins `R09-07` with the `0.8.0` hardening | Planner limit of nine | — |
| Email test send | Allowed in production only to the caller's own address | Useful, cannot relay | Non-production only, as today |

## 3. Plan check: what the code confirmed or changed

| Item | Result |
|---|---|
| R09-01 | **Changed.** `interfaces/http/auth.py` (1,393 lines) has no recovery routes and `users` has no verification column; new routes go in new modules. `POST /team/invitations/accept` sets a password even when the account already has one, and has no rate limit; A1 stops it changing an active password. Login answers an unknown email without hashing (A1 adds a dummy verification). `email_delivery_logs` has a CHECK on `event_type`; S1 extends it. |
| R09-02 | **Changed.** `mfa_required=False` is set in `security_settings._policy_from_sso`; the login policy is derived from the SSO row, and `GET/DELETE /security/sessions*` return placeholder data. A2 adds `org_login_policies` and wires the session routes to `AuthSessionRepository`. Access tokens resolve through a cached principal snapshot; revocation already invalidates it after commit. |
| R09-03 | **Changed.** `BillingService` (504 lines) is concrete, has no provider seam, synthesises invoices, returns its own settings URL as the portal, and `update_billing_contact` does not persist. No plan catalogue exists. B1 splits it into a port, adapters, and services. |
| R09-04 | **Changed.** Bots have `default_source_scope_json` and free-form `config_json`, no channel mapping and no usage endpoint; C1 adds both (validated, narrowing only). |
| R09-05 | **Changed.** `admin_email` has preview, test-send, delivery logs, and two preference routes; no provider status route, untyped log response, no filters. |
| R09-06 | **Changed.** Placeholders are the frontend `CATALOG` entries `slack`, `github`, `gitlab` (`available: false`, "Notify me"); `NotificationCenter` also shows "Per-category preferences are coming soon", and the empty state names Jira. |
| R09-07 | **Changed.** Three routes still answer 501: documents upload URL and chat session messages (scaffolds), avatar upload without object storage. |
| R09-08 | **Changed.** Organisation overrides exist for 21 registry flags only; seven of the section 4.5 flags have none. `query_rewriting` has an override in the admin API but the pipeline reads `settings` directly, so it is ignored; B2 wires it (existing overrides take effect; release note). RAG profiles replace the system flag for the verifier and planner-critic. `chat_pipeline_v2` was due for removal in `0.6.0`. |
| R09-09 | **Changed.** Per-stage tokens are written only for cancelled runs; completed runs record rerank fields only. An AI response policy can force verification on. |
| R09-10 | **Changed.** SAML response validation is incomplete (signature, audience, recipient, validity window, replay, request correlation) and the callback puts the access token in the URL; A3 completes it. SCIM returns the Rudix id but looks users up by `externalId`, ignores unsupported filters, misreads string booleans in PATCH, answers some errors outside the SCIM schema, and deprovisioning does not revoke sessions. |
| 0.8.0 points | **Confirmed in code:** label-less `rudix_beat_heartbeat_timestamp_seconds` and `rudix_db_replica_lag_seconds` (`metrics_infra.py`); no caller of `record_document_indexing_job`; global `traceparent` injection on every `httpx` host (`tracing._instrument_httpx`); provider credentials from a developer `.env` reach tests; `test_documents_cursor_page_uses_index` seeds no statistics; the frontend Deployment uses `rudix.envFrom` (whole backend Secret); MCP Ingress falls back to the API TLS secret; `rudix.c1.dataClientComponents` adds `pgbouncer` to every data store; dead children's multiprocess files are never compacted. |
| Migrations | Head `20261128_0003`. S1 adds `20261129_0001` (down `20261128_0003`), `20261129_0002` (down `20261129_0001`), `20261129_0003` (down `20261129_0002`). No other package adds one; a package that needs one stops and reports. |

## 4. Sequence

| Chain | Order | Task | Items | Model | Review |
|---|---|---|---|---|---|
| S | 1 | S1 | Foundation: schema and migrations, one-time tokens, settings modules, anchors, namespaces, frontend dependencies, hermetic tests | opus | data |
| A | 1 | A1 | R09-01 verification and password reset | opus | api |
| A | 2 | A2 | R09-02 MFA, org policy, step-up, real session routes | opus | api |
| A | 3 | A3 | R09-10 SAML and SCIM validation, supported matrix | opus | api |
| B | 1 | B1 | R09-03 payments | opus | data |
| B | 2 | B2 | R09-09 plan stage limits and stage cost; R09-08 flag decisions and org overrides | opus | data |
| C | 1 | C1 | R09-04 bots admin; R09-05 email admin; R09-06 catalogue; notification preferences | opus | api |
| C | 2 | C2 | R05-12 rich answers; Sentry SDK; axe checks | opus | api |
| D | 1 | D1 | R09-07 public API, deprecation, SDK; `0.8.0` hardening | opus | api |

S1 runs first and alone; A, B, C, and D start after S1 is merged. Model reasons: S1 migrations
and token storage; A tokens, MFA, session revocation, enumeration, SAML; B payment webhooks,
signatures, and default retrieval and trust gating; C admin-only, organisation-scoped visibility
and untrusted content rendering; D route audience classification, trace propagation, and secret
exposure in the chart.

## 5. Shared files and contracts

### 5.1 Owners and anchors

Every task re-reads a shared file before editing, edits only its anchor with `Edit`, never
rewrites or reformats a shared file, and re-reads after a failed `Edit`. Anchors use `v090-`.

| File | Task: anchor |
|---|---|
| `backend/alembic/versions/`, `backend/app/models/*`, `app/models/__init__.py`, `app/db/rls.py` | S1 only (new tuples `RLS_LOOKUP_TABLES_0_9_0`, `RLS_STRICT_TABLES_0_9_0`; `tests/test_rls_coverage.py` stays green). |
| `backend/app/core/config.py` | S1 registers `AccountSecuritySettings` (`settings/account_security.py`) and `BillingSettings` (`settings/billing.py`). Fields: A1, A2, A3 under `# v090-A1/A2/A3` in `account_security.py`; B1, B2 under `# v090-B1/B2` in `billing.py`; D1 at the end of `TracingSettings`, `ObservabilitySettings`, `DatabaseSettings`; A1 alone extends `email_provider`'s pattern with `capture` (`email_bots.py`). |
| `backend/app/core/settings/snapshot.py` | S1 adds `"product_completeness"` with `# anchor: v090-<task>` lines; booleans and sanitized values only. |
| `backend/app/api/router.py` | S1 adds `# anchor: v090-<task>` comment lines in the public block (after `web_vitals`) and the protected block (after `events`). Each task includes its routers only under its own anchor. |
| `backend/app/workers/celery_app.py` | S1 adds `# anchor: v090-S1/A1/B1/D1` in `INCLUDE`, `TASK_ROUTES`, `BEAT_SCHEDULE` and registers `auth.tokens.purge_expired`. |
| `backend/tests/conftest.py` | S1 (hermetic guard). Others add fixtures in their own `tests/*_support.py`. |
| `backend/pyproject.toml`, `backend/uv.lock` | Nobody (no backend dependency in this release). |
| `frontend/package.json`, `frontend/package-lock.json` | S1 only: `qrcode.react`, `react-markdown`, `@sentry/browser` (dependencies), `@axe-core/playwright` (dev), exact versions released at least two weeks earlier, installed with `npm install --save-exact`. |
| `frontend/openapi.json`, `src/lib/api/generated/schema.d.ts`, `docs/api/openapi.public.json` | Every task that changes the API regenerates (`npm run api:update-schema`; after D1 also `export_openapi.py --public`). Never hand-merge: on conflict take `develop`'s copy and regenerate. |
| `frontend/src/i18n/messages/{en,de,es,fr,ar,fa}.json` | S1 adds empty top-level namespaces `authAccount` (A1), `authMfa` (A2), `adminBots`, `adminEmail` (C1) after `auth` and `adminVectorIndex` respectively. Edits inside existing namespaces: A1 `auth.login`; A3 `adminSso`, `adminScim`; B1 `settings.billing`; B2 `adminUsage`, `adminQuotas`, `adminFeatureFlags`; C1 `connectors.page`, `notificationCenter`, `adminLanding`; C2 `chat`. Every key in all six files. |
| `frontend/src/i18n/namespaces.ts` | S1 adds `ACCOUNT_NAMESPACES = ["authAccount", "authMfa"]` (shipped by A1's account layout, not by marketing pages) and the admin namespaces to `APP_NAMESPACES`. |
| `frontend/config/public-runtime-keys.mjs`, `config/security-headers.mjs` | C2 only. |
| `frontend/src/components/admin/AdminLandingPage.tsx` | C1 only (bots and email cards). |
| `frontend/e2e/a11y.spec.ts` (C2) | A task merged after C2 adds its new pages to the page list. |
| `.env.example` (root) | S1 adds `# --- Product completeness (0.9.0) ---` with `# anchor: v090-A1` … `# anchor: v090-D1`. |
| `docs/07_API_DESIGN.md` | A1, A2, A3: `###` sections after `#### Session hint cookie` in that order; B1 `## Billing and payments` after `## Quotas and plan limits`; B2 a paragraph at the end of `## Quotas and plan limits` and `### GET /admin/usage/stage-costs` after `### GET /admin/usage`; C1 the end of `## Collaboration bots` and `## Email administration` before `## Search/debug endpoints`; D1 `## Versioning and deprecation` before `## Rate limits` and the 501 line in `## Status codes`. |
| `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` | A1, A2, A3 `###` subsections at the end of `## Authentication` in order; B1 `## Payments` before `## Secrets`; C1 one bullet at the end of `## Rate limiting`; C2 `### Rich answer rendering` at the end of `## LLM output validation` and one bullet at the end of `## Security headers`; D1 bullets at the end of `## Tracing` and under `### Deployment`. Unchecked bullets end with `(operator, 0.9.0)`. |
| `docs/22_AUTHORIZATION_SYSTEM.md` | A2 `### Multi-factor authentication and step-up` at the end of section 7; A3 a paragraph in section 9 (SSO and SCIM audit events); B1 a `billing:manage` row note in section 3; C1 a bots paragraph in section 3. |
| `docs/03_RAG_WORKFLOW.md` | B2 only: `## Plan stage limits` and `## Feature flag decisions (0.9.0)` before `## Evaluation pipeline`. |
| `docs/12_EVALUATION_AND_MONITORING.md` | One `###` per task (A1, A2, B1, B2, D1) before `## Continuous evaluation`. |
| `docs/26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md` | B2 section 4.5 (decision column); D1 nothing. |
| New docs | D1 `docs/29_PUBLIC_API_AND_DEPRECATION_POLICY.md`; A3 `docs/30_IDENTITY_PROVIDER_SUPPORT_MATRIX.md`; each adds itself to `docs/README.md` as item 30 or 31 under "Architecture and Implementation" (whoever merges second appends). |
| `backend/README.md`, `frontend/README.md` | One bullet list per task at the end of the section its settings belong to. |
| `docs/CHANGELOG.md` | One line per task under `[Unreleased]` `### Added`, directly after the line starting "- `docs/roadmap/V0_9_0_IMPLEMENTATION_PLAN.md`". |
| `deploy/helm/rudix/**`, `infra/observability/**` | D1 only. |

### 5.2 Contracts between chains

1. **Worktrees and checks.** Branch `feat/v0.9.0-<task>` in `../rudix-v090-<task>` from the
   current `develop`. Backend changes run `make install`, `make lint`, the SQLite suite, and the
   Postgres lane on `rudix_test_<chain>` at `127.0.0.1:55432` (if `rudix-test-pg` is not running,
   report it; never start it). Frontend changes run `npm ci` once, `format:write`, `typecheck`,
   `lint`, `test:coverage`, `build`, `api:check`, `check-bundle-budgets.mjs`, and Playwright when
   routes, layouts, runtime configuration, auth, or public pages change. Restore
   `frontend/AGENTS.md` and `frontend/tsconfig.json` with `git checkout --` before committing.
   No container is started, stopped, or created; no provider is called over the network.
2. **One-time tokens (S1).** `app/domains/auth/services/one_time_tokens.py`: `issue(session,
   *, purpose, user_id, organization_id, ttl_seconds, session_id=None, metadata=None) -> str`
   (32 random bytes, URL-safe; only SHA-256 stored); `consume(session, *, purpose, raw_token)
   -> OneTimeToken | None` (one conditional `UPDATE … WHERE consumed_at IS NULL AND expires_at >
   now() RETURNING`, so a race consumes once); `record_failed_attempt(...)` (attempt count,
   invalid at `max_attempts`); `revoke_for_user(session, *, user_id, purpose)`; `purge_expired`.
   Purposes: `email_verification`, `password_reset`, `mfa_challenge`, `mfa_enrolment`,
   `step_up`, `saml_request`, `saml_assertion`. Metadata never holds secrets or email text.
3. **Schema (S1).** `20261129_0001`: `auth_one_time_tokens`, `users.email_verified_at`,
   `email_delivery_logs` event types `email_verification` and `password_reset`.
   `20261129_0002`: `user_mfa_factors`, `user_mfa_recovery_codes`, `org_login_policies`
   (`mfa_required` false, `mfa_grace_period_days` 7, `mfa_required_since`),
   `auth_refresh_sessions.auth_method` (default `password`) and `.mfa_verified_at`.
   `20261129_0003`: `billing_plans`, `billing_customers`, `billing_subscriptions`,
   `billing_invoices`, `billing_webhook_events`, `org_quota_policy.stage_limits` (nullable JSON).
   All additive; downgrade drops them (loses enrolments, tokens, billing state: documented).
4. **Auth failures.** Recovery endpoints answer one body for every email (`202 {"accepted":
   true}`); invalid, expired, consumed, or wrong-purpose tokens all answer `400
   {"code": "invalid_or_expired_token"}`. MFA and step-up errors use codes `mfa_required`,
   `mfa_enrolment_required`, `step_up_required`, `invalid_mfa_code`.
5. **Stage gate (B2) and MFA principal check (A2)** both read cached per-organisation rows;
   neither adds a per-request query on a warm cache (`tests/test_chat_query_count.py` must not
   rise).
6. **Billing to quotas (B1, B2).** A plan change writes `OrgQuotaPolicy.limits` and
   `.stage_limits` through `upsert_policy_with_log` with change note `billing:<plan_key>`; B2
   reads `stage_limits` only from the policy, never from billing tables.
7. **Route audience (D1).** Every route is `public`, `internal`, or `admin` by
   `app/api/openapi_surface.py`; `tests/test_openapi_surface.py` fails on an unclassified route.
   A task merged after D1 classifies its new routes there.
8. **Hermetic tests (S1).** Tests run as in CI: provider credentials from `.env` are pinned to
   placeholders, `EMAIL_PROVIDER=console`, `BILLING_PROVIDER=none`, and an autouse guard fails
   any socket connection to a non-loopback host other than the configured test database and
   Redis. No assertion is weakened.

## 6. Steps per item (summary; the task briefs hold the detail)

- **S1:** three migrations and models; RLS classification; one-time token service and purge task;
  settings modules with anchors and startup validation stubs; router, Celery, `.env.example`,
  snapshot anchors; enum values for new email event types; empty namespaces and
  `ACCOUNT_NAMESPACES`; approved frontend packages; hermetic guard; statistics seeding in
  `test_documents_cursor_page_uses_index` (as `seed_usage_event_statistics` does).
- **A1 (R09-01):** `auth_account.py` router (`verify-email`, `resend-verification`,
  `forgot-password`, `reset-password`); worker tasks; templates; password policy service used by
  reset, invitation accept, and change-password; per-IP and per-email limits (hashed keys);
  reset revokes every session and outstanding reset token; dummy hash on unknown emails;
  verification enforcement setting; `capture` email provider (development and test only) for the
  integration suite; funnel steps in F353; frontend `forgot-password`, `reset-password`,
  `verify-email` pages under an account layout, translated accept-invite page; Playwright flow.
- **A2 (R09-02):** TOTP and recovery-code services, enrolment and challenge routes, login union,
  refresh and principal checks, org policy routes with grace, step-up dependency on the named
  routes, owner reset and operator script, real `/security/sessions` routes, metrics, frontend
  enrolment (QR on demand), challenge step, step-up modal, policy controls.
- **A3 (R09-10):** signature, digest, reference, audience, recipient, destination, issuer,
  validity, `InResponseTo`, replay; generic errors with audit detail; safe `RelayState`; callback
  without URL token; SSO sessions `auth_method=sso`; SCIM id lookup, filters, PATCH forms,
  error schema, discovery endpoints, session revocation on deprovision, `is_active` on refresh;
  IdP-shaped fixtures signed with test keys; `docs/30` matrix marked "not yet verified".
- **B1 (R09-03):** port, `none` and Stripe adapters, plan import script, checkout, plan change
  with proration preview, cancel, portal, invoices from webhooks, webhook route, grace and
  downgrade task, reconciliation task, metrics, billing tab UI; fakes for every flow.
- **B2 (R09-09, R09-08):** `stage_gates.py` resolving plan, org flag override, profile, and policy
  once per request; ledger guard; skip reason in trust metadata; `stage_costs` in usage metadata;
  `GET /admin/usage/stage-costs`; quota policy `stage_limits` in the admin API and UI; org
  overrides for the seven flags and wiring of `query_rewriting`; decision table; stub-only gate
  run recorded as such; deprecation notes.
- **C1 (R09-04, R09-05, R09-06):** channel scopes and allowed modes (validated, narrowing),
  usage endpoint, typed email status and filtered logs, production test-send to self,
  `/admin/bots` and `/admin/email` pages, notification preferences wired to the API, placeholder
  connector entries removed.
- **C2:** rich answer component with an XSS corpus, citation chips, streaming without flicker,
  shared answer page; Sentry SDK on demand with scrubbing and tunnel; axe spec and allowlist.
- **D1:** audience registry and public document, examples, error codes, pagination, rate limits,
  API-key and service-account authentication guide, quickstart test, deprecation helper and
  policy, types-only SDK; beat and replica gauges, indexing instrumentation and stage filter,
  first-party trace propagation, chart secret scope, MCP TLS, pgbouncer policy, multiprocess
  compaction.

C2 criteria for `NEXT_PUBLIC_CHAT_RICH_ANSWERS=true` by default: the XSS corpus renders no
element or attribute outside the allowlist; every citation marker renders as a chip; the streaming
test shows no layout shift above 0 between consecutive frames once a block is closed; `/chat`
first-load size unchanged. Any failure: default `false`, recorded in the Status section.

## 7. Verification for the release

```bash
cd backend && make install && make lint && make test && make test-cov
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://rudix:rudix@127.0.0.1:55432/rudix_test make test-postgres
cd backend && make check-revisions && .venv/bin/python scripts/check_migration_safety.py --all
cd backend && .venv/bin/python scripts/export_openapi.py --check ../frontend/openapi.json
cd backend && .venv/bin/python scripts/export_openapi.py --public --check ../docs/api/openapi.public.json
cd backend && .venv/bin/pytest -m "isolation or guardrails or accuracy_smoke"
deploy/scripts/check_helm_chart.sh && deploy/scripts/check_compose_config.sh
deploy/scripts/check_observability_config.sh
cd frontend && npm ci && npm run format && npm run lint && npm run typecheck && npm run test:coverage
cd frontend && npm run build && node scripts/check-prerendered-routes.mjs && npm run api:check
cd frontend && node scripts/check-bundle-budgets.mjs && PLAYWRIGHT_USE_BUNDLED_BROWSER=true npx playwright test
```

Coverage stays at or above the ratchets (backend 83.0; frontend statements 68.7, branches 60.9,
functions 62.3, lines 69.6). `alembic heads` reports `20261129_0003`; `downgrade 20261128_0003`
and `upgrade head` pass on a scratch PostgreSQL database. The prerender check finds all 144
static routes and the parity tests pass; no budget is raised.

## 8. Operator steps (not done in the repository)

1. Stripe account: create products and prices, import them with `scripts/billing_plans.py`, set
   `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, register the webhook
   URL, and run test mode: subscribe, upgrade with proration, cancel, failed payment into grace
   and downgrade, webhook replay. Tax settings are the operator's.
2. Email: configure a real provider, SPF, DKIM, and DMARC; send verification and reset mail to a
   test mailbox; confirm the delivery log and the resend limit.
3. Identity providers: configure at least two (for example Okta and Microsoft Entra ID) against
   staging for SAML and SCIM; record results in `docs/30`; then enable `mfa_required` on one
   staging organisation and confirm SSO members are not challenged.
4. MFA keys: set `AUTH_MFA_ENCRYPTION_KEY` before the first enrolment (rotation needs
   re-encryption).
5. Run the accuracy and safety gates and the load test on staging with each candidate flag on;
   record results in the decision table before flipping any quality-sensitive default.
6. Sentry: source-map upload with an auth token; confirm scrubbed events; enable the tunnel if
   used. Publish the SDK package if wanted.
7. Run the `e2e-integration` suite (account recovery, MFA) against the integration stack.

## 9. Exit criteria that stay staging-only

- "Provider test-mode covers subscribe, upgrade, cancel, failed payment, and webhook replay"
  (`R09-03`): fakes pass here; the provider run is step 1 of section 8.
- An invited user accepts, verifies, subscribes, uploads, and asks with no manual step on staging.
- "Flag graduation complete with gate evidence" and "accuracy and latency targets hold": only the
  decision table and stub-only results are produced here.
- `R09-10` supported matrix verified against real identity providers.

Checked here instead: every flow above against fakes and the stub LLM, the Playwright flows with
mocked APIs, the PostgreSQL lane, migration round trip, OpenAPI and public-document checks,
chart render with every values file.

## 10. Deferred

- WebAuthn (post-1.0, spec); an online breach-check service (needs approval); SAML encrypted
  assertions, signed AuthnRequests, and single logout; replacing in-house XML signature checks
  with a maintained library (needs a dependency approval; recommended before the `1.0.0` review).
- A second payment provider; tax and VAT handling inside Rudix.
- GFM tables in rich answers (plugin not approved); a runtime TypeScript client (not approved).
- Jira on the provider SDK (post-1.0 candidate); SCIM Groups.
- Default flips for quality-sensitive flags until staging gates pass; removal of deprecated flags
  and `chat_pipeline_v2` (not before `1.0.0`).
- Self-serve signup (owner decision). Items still deferred from `0.8.0` section 10.

## 11. Change Notes

- 2026-11-28: Initial version, written after checking the `0.9.0` spec against the code at
  `05e5b5c0`, with the owner's instruction to take the recommended option on each open
  decision and the fallback where none is recommended.
