# v0.9.0 — Product Completeness

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [00_AUDIT_BASELINE.md](./00_AUDIT_BASELINE.md), [../07_API_DESIGN.md](../07_API_DESIGN.md)

## 1. Purpose

Close the product gaps that block a self-serve, paid, generally available service, and turn
on the retrieval and trust features that are built but off by default.

## 2. Work items

### R09-01 — Email verification and password reset (L)

> **Decision (2026-11-27):** self-serve signup is out of scope. Accounts are created only by
> workspace administrators (invitations, SCIM, SSO); the frontend `/signup` route redirects
> to `/login`. Do not add `POST /auth/register`.

- **Problem:** `interfaces/http/auth.py` has no forgot-password or verify-email route.
- **Change:**
  - `POST /auth/verify-email` and `POST /auth/resend-verification` for invited users.
  - `POST /auth/forgot-password` and `POST /auth/reset-password`.
  - Tokens are single-use, hashed at rest, short-lived, and sent through the existing
    transactional email service (F251). Responses do not reveal whether an email exists.
  - Rate limits per IP and per email on reset and verification requests.
  - Password policy and breach check are settings. Reset revokes all sessions.
  - Frontend: add verify and reset pages in all six locales.
- **Done when:** A Playwright test accepts an invitation, verifies, logs in, resets the
  password, and confirms the old session is rejected.

### R09-02 — Multi-factor authentication (L)

- **Problem:** `mfa_required=False` is hardcoded and no TOTP or WebAuthn code exists.
- **Change:** TOTP enrolment with recovery codes, challenge on login, step-up for sensitive
  actions (API key creation, role changes, SSO configuration). Organisation policy
  `mfa_required` enforced at login with a grace period. Secrets encrypted at rest. SSO users
  defer to the identity provider. WebAuthn is a post-1.0 candidate.
- **Done when:** An organisation with `mfa_required` blocks a member without a second factor,
  and recovery codes are single-use.

### R09-03 — Payments (L, needs decision)

- **Problem:** Invoices are synthesised from usage cost and the "portal" returns the app's
  own settings URL.
- **Change:** Integrate one payment provider behind the existing `billing_service` interface:
  checkout, subscription lifecycle, plan changes with proration, customer portal, real
  invoices, and signed webhook handling with idempotency keys. Plan state drives the existing
  quota policies (F154). Failed payment enters a grace period before downgrade. No card data
  touches Rudix servers.
- **Fallback:** Keep usage-derived invoices and manual plan assignment.
- **Done when:** Provider test-mode covers subscribe, upgrade, cancel, failed payment, and
  webhook replay.

### R09-04 — Collaboration bots admin UI (M)

- **Change:** Admin page for Slack and Teams (F261): connect, channel-to-collection mapping,
  allowed scopes, usage, and disconnect. Typed client and translations.
- **Done when:** A bot can be configured without calling the API by hand.

### R09-05 — Email administration UI (S)

- **Change:** Admin page for the five existing `admin_email` routes: provider status, test
  send, delivery log with filters, template preview.

### R09-06 — Connector catalogue decision (M, needs decision)

- **Change:** Either restore the Jira connector (F242, removed in commit `81c856fa`) on the
  provider SDK with the `0.6.0` sync engine, or remove the "coming soon" cards. Do not ship
  placeholders at `1.0.0`.

### R09-07 — Public API documentation and deprecation policy (M)

- **Change:**
  - Publish curated API reference from the OpenAPI export: tagged, with examples, error
    codes (`R04-10`), pagination (`R04-04`), rate limits, and authentication with API keys
    and service accounts.
  - Hide internal and admin-only routes from the public document.
  - Write the versioning and deprecation policy: what `/api/v1` guarantees, how long a
    deprecated field lives, how it is announced (`Deprecation` and `Sunset` headers).
  - Generate a typed client from the same OpenAPI document as a first SDK.
- **Done when:** A new developer can authenticate, upload, and query using only the docs.

### R09-08 — Feature flag graduation (L)

- **Change:** For each flag in the master plan section 4.5, in this order:
  1. Run the accuracy and safety gates with the flag on.
  2. Run the load test with the flag on and check the latency budget and cost per question.
  3. Change the default, keeping the per-organisation override.
  4. Update `.env.example`, `docs/03_RAG_WORKFLOW.md`, and the changelog.
- **Decide** `mcp`, `org_memory`, and `chat_tool_orchestration`: graduate, keep opt-in, or
  mark experimental.
- **Clean up:** Remove flags that have been on by default since `0.1.0` and have no
  per-organisation use, after one release with a deprecation note.
- **Done when:** Every flag has a recorded decision and gate result.

### R09-09 — Plan-aware cost controls (M)

- **Change:** With full cost accounting (`R05-07`), expose per-plan limits on optional
  stages (for example, verifier and planner-critic only on plans that include them) through
  the existing RAG profile and quota policies. Show per-stage cost in the usage dashboard.
- **Done when:** A plan without a stage never incurs its cost.

### R09-10 — Enterprise identity verification (M)

- **Change:** Run SAML SSO (F160) and SCIM (F161) against at least two real identity
  providers in staging. Record the supported matrix and fix what the tests find.

## 3. Exit criteria

- A new user can sign up, verify, subscribe, upload, and ask a question with no manual step.
- No 501 responses and no "coming soon" UI remain, other than routes marked deprecated.
- Flag graduation complete with gate evidence.
- Accuracy and latency targets hold with the graduated defaults.

## 4. Failure Modes and Recovery

| Failure | Recovery |
|---|---|
| Payment webhook lost or replayed | Idempotent handlers; periodic reconciliation job |
| Verification email undelivered | Resend with rate limit; delivery log (F251) |
| User locked out by MFA | Recovery codes; owner-initiated reset with audit log |
| Graduated flag regresses a tenant | Per-organisation override back to off |

## 5. Security Considerations

- Account enumeration: register, reset, and resend return identical responses.
- All new tokens are hashed at rest and single-use.
- MFA secrets and recovery codes are encrypted; step-up events are audit-logged.
- Payment webhooks verify signatures and reject stale timestamps.
- Update `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` and `docs/22_AUTHORIZATION_SYSTEM.md`.

## 6. Observability and Operations

Metrics: invitation-acceptance funnel (extends F353), verification and reset rates, MFA enrolment, payment
failures, webhook lag, cost per question by plan.

## 7. Change Notes

- 2026-11-26: Initial version.
