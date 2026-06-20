# Frontend

Next.js frontend for Rudix. The current implementation includes an authenticated application shell, login/signup session flows, the Documents workspace at `/documents`, the Graph Explorer at `/graph`, and the Pipeline Explorer at `/rag-pipeline`.

## Stack

- Next.js App Router
- React + TypeScript
- Tailwind CSS v4
- React Flow (`@xyflow/react`)
- TanStack Query
- Zustand
- React Hook Form + Zod
- Vitest + Testing Library
- Playwright

## Implemented Pages

- Public marketing routes (outside the authenticated app shell):
  - `/` landing page
  - `/product`
  - `/solutions`
  - `/security`
  - `/pricing` (configurable/contact-placeholder packaging)
  - `/contact` (validated contact/demo form)
  - `/demo` (alias redirect to `/contact`)
  - `/status`
- `/login` credential-based sign-in form with auth-provider entry points
- `/signup` account creation form with workspace create/join entry points
- `/organization-onboarding` authenticated workspace setup flow (workspace, domain allowlist, access defaults, invites)
- `/onboarding` compatibility redirect to `/organization-onboarding`
- `/forbidden` unauthorized route destination
- `/403` alias route for forbidden destination
- Protected product pages inside the shared shell:
  - `/dashboard`
  - `/documents`
  - `/graph`
  - `/graph/entities/[entityId]`
  - `/chat`
  - `/evaluations`
  - `/rag-pipeline` Pipeline Explorer
  - `/settings`
  - `/admin` (owner/admin roles only)
  - `/admin/security-center` (owner/admin roles only)
  - `/admin/governance` (owner/admin roles only)

### Shared Shell and Protection

- Reusable authenticated shell with:
  - responsive sidebar and mobile drawer navigation
  - top bar with route context, notifications, help, and profile menus
  - content container shared by all product pages
- Route metadata and role-aware navigation actions for all product routes.
- Protected-route behavior:
  - unauthenticated users are redirected to `/login?next=...`
  - unauthorized users are redirected to `/forbidden`
- Forbidden state behavior:
  - reusable `ForbiddenState` component for inline and full-page authorization failures
  - includes optional support action via environment configuration
  - displays safe trace/request ID values when available from backend responses
- Top bar behavior:
  - profile menu shows safe user and organization context with settings + sign-out actions
  - help menu links to configured docs/support/shortcuts/README resources
  - notifications menu consumes optional backend feed and shows loading, empty, and unavailable states
  - global search command menu (`Cmd/Ctrl + K`) provides:
    - quick page navigation (Dashboard, Documents, Chat, Evaluations, Pipeline Explorer, Settings, Admin when permitted)
    - document search by filename/status from organization-scoped document list data
    - recent chat session shortcuts
    - permission-aware route filtering and helpful empty states
  - menu actions are permission-aware (e.g., admin links only for owner/admin roles)
- Login behavior:
  - validates credentials using React Hook Form + Zod
  - redirects already authenticated users away from `/login`
  - redirects successful sign-in to requested protected route (`next`) or `/dashboard`
  - supports environment-driven SSO and forgot-password links when configured
- Signup behavior:
  - validates name, email, password, workspace mode, and terms acceptance using React Hook Form + Zod
  - supports create-workspace and join-workspace entry points
  - maps duplicate email, weak password, invite-only, and provider/network errors to safe messages
  - redirects successful signup to `/organization-onboarding` or `/dashboard` based on signup result state
- Organization onboarding behavior:
  - requires authenticated session and redirects unauthenticated users to `/login?next=/organization-onboarding`
  - redirects already-onboarded sessions to `/dashboard`
  - validates workspace name, optional domain allowlist, default access settings, and invite emails/roles
  - supports draft save/resume through backend endpoints when configured, with local fallback
  - completes onboarding by creating/updating organization context and routing to `/dashboard`
- Documents page behavior:
  - upload dropzone for `pdf`, `txt`, and `docx` files with permission-aware controls
  - status-aware document table (filename, type, status, page count, chunk count, created timestamp)
  - async delete and re-index actions with role-based enablement
  - polling while documents are in transitional states (`uploaded`, `processing`, `deleting`)
  - detail and chunk preview inspector with loading/empty/error states
- Dashboard page behavior:
  - KPI cards for total documents, indexed documents, total chunks, questions asked, average confidence, average latency, indexing success, and estimated cost (admin/owner only)
  - data sourced from typed document, chat, and admin usage clients with fallback handling where backend metrics are unavailable
  - admin-only usage window selector (7d / 30d / 90d) for `/admin/usage` aggregation when enabled
  - explicit loading/error states with retry actions for each KPI card
  - empty state with document/chat call-to-actions when no activity exists
- Chat page behavior:
  - supports one-shot RAG mode and explicit agentic mode toggle for plan-act-observe execution
  - agentic mode calls `/agent/runs` with typed payloads and renders final cited answer in-thread
  - context panel includes safe agent timeline (status, budgets, stop reason, and step durations)
  - step-level raw payloads are intentionally hidden from UI to avoid sensitive data exposure
- Evaluations page behavior:
  - modular dashboard layout with header/actions, KPI cards, run filters, run list, run detail, and case-inspection sections
  - primary CTA for starting a run and secondary CTA for evaluation set creation (owner/admin visibility)
  - run filters for status, dataset, owner, date range, search query, and sort order
  - run detail section with run metrics, baseline-comparison placeholder, failed-case focus, citation/source links when available, and pipeline deep-linking
  - test-case section with dataset search, test-case filters/sort, and permission-aware add-case flow
  - resilient fallback rendering for missing backend fields (for example comparison deltas, cost/owner fields, or citation payloads)
  - explicit loading, empty, unavailable-backend, error, and forbidden states with safe request-id rendering
- Settings page behavior:
  - four tabs: Profile, Organization, Security, and Billing — navigated via `?tab=<id>` query param, defaulting to `profile`
  - Profile tab: display name and email from `/me`, personal preferences from `/me/preferences`, sign-out-all-devices, and account deletion; each action shows an unavailable state when its endpoint is not configured
  - Organization tab: org profile and workspace defaults from `/organization` and `/organization/settings`, ingestion config from `/organization/ingestion`, team member management from `/team/members*`, chunking profile catalog (admin-only, preview stats without raw chunk text), and danger-zone actions when endpoint URLs are configured
  - Security tab: active sessions from `/security/sessions` with per-session revoke actions; login policy from `/security/login-policy` (owner/admin); security posture from `/security/posture`; recent audit events from `/security/audit-events` (owner/admin); role capability summary
  - Billing tab: plan info, usage, quotas, invoices, and billing contact from `/billing/*`; portal redirect for card/subscription management; restricted to billing admins and owners
  - each section renders a clear unavailable state when its backend endpoint URL is not configured or returns `501` — tabs remain navigable while backend stubs are in place
  - local fallback for preferences only: when `NEXT_PUBLIC_SETTINGS_PREFERENCES_LOCAL_FALLBACK=true`, personal preferences persist to `localStorage` under key `rudix.settings.preferences.v1` when the remote endpoint is absent or fails; no tokens, session data, or backend-derived private content are stored locally
  - role-based access: all roles can view and edit their own Profile; Organization workspace defaults and team management require admin or owner; Security login policy and audit events require owner or admin; Billing requires billing_admin or owner permissions (`billing:view` / `billing:manage`); danger-zone actions (transfer, archive, delete org) require owner
  - sensitive-value redaction: access tokens are never rendered; refresh sessions are backend-managed via HttpOnly cookies and are shown only as a cookie/status indicator; billing card numbers and CVVs are never displayed; raw chunk text, raw prompts, and retrieved document content are never shown in settings views; backend error strings are not rendered verbatim
- Document detail behavior:
  - overview panel shows safe chunk diagnostics including applied strategy, OCR flag, language, token distribution, reason codes, and profile-aware re-index controls
  - chunk preview search matches preview text plus safe metadata (`section_path`, page, language, offsets) and keeps full chunk text permission-gated
- Admin page behavior:
  - usage summary cards for events, tokens, cost, confidence, and latency
  - usage trend table sourced from `/admin/usage` with date-range filters
  - audit explorer sourced from `/admin/audit-logs` with actor/action/entity/organization/document/collection/IP/session/result/severity filters
  - authenticated export from `/admin/audit-logs/export` in CSV and JSON formats with sanitized metadata only
  - owner/admin-only access with forbidden-state fallback when authorization changes
  - quick links to documents, chat, evaluations, and pipeline explorer
- Admin security center behavior:
  - consolidated security posture summary for auth/session status, role visibility, domain restrictions, retention posture, and audit health
  - deep links for audit logs, team settings, retention controls, billing/plan controls, and optional API key/webhook controls when configured
  - unresolved warning and recommendation panels with safe operational language (no compliance over-claims)
  - owner/admin-only access with forbidden-state fallback when authorization changes
- Admin governance page behavior:
  - organization-scoped policy controls for agentic mode, MCP exposure, tool allowlists, and runtime budgets
  - external MCP server policy form with side-effect warning acknowledgment flow
  - MCP endpoint status panel showing configured transport, auth, and rate-limit posture
  - typed API client integration with `/admin/governance` and explicit loading/empty/error/forbidden states
- Pipeline Explorer remains fully functional within the shared shell:
  - run loading from backend API
  - run type and document filters
  - node status visualization
  - node detail side panel
  - loading/error and permission-aware states
- Public marketing foundation:
  - reusable marketing header, mobile navigation, footer, and CTA components
  - centralized public link resolution with environment-driven overrides
  - shared public SEO metadata helper (title, description, canonical, Open Graph, social cards)
  - skip-to-content link and semantic landmarks for accessibility

## Dashboard Design Sample

![Rudix Dashboard Sample](../docs/screenshots/dashboard_overview.png)

This image remains the visual reference for `/dashboard`.

Dashboard behavior and structure:

- Left navigation shell shared with all authenticated pages.
- Top bar with global search, alerts/help icons, and user profile access.
- System performance summary with primary CTAs (`Upload Document`, `New Chat`).
- KPI cards for total documents, indexed documents, total chunks, and questions asked.
- Performance panel showing confidence, latency, and index success trends.
- Billing/usage card with quota progress and billing action.
- Operational tables for recent activity and latest documents with status badges.

Implementation notes:

- Keep the same visual language as `/rag-pipeline` (spacing, color scale, card treatment).
- Use typed API clients and show explicit loading, empty, and error states.
- Preserve permission-aware behavior for organization-scoped data.

## Settings Dashboard

The `/settings` page provides four tab-scoped management surfaces with progressive backend rollout. Tabs remain fully navigable while some endpoint groups are still unavailable — each section shows a clear unavailable state for any endpoint that is missing or returns `501`.

### Tabs and URL navigation

| Tab          | `?tab=` value  | Default                                         |
| ------------ | -------------- | ----------------------------------------------- |
| Profile      | `profile`      | yes (fallback when `?tab` is absent or invalid) |
| Organization | `organization` | —                                               |
| Security     | `security`     | —                                               |
| Billing      | `billing`      | —                                               |

### Backend endpoints

Set `NEXT_PUBLIC_FEATURE_UNAVAILABLE_BACKEND_ENDPOINTS=false` only after all endpoints for a given tab are live and tested.

**Profile tab** — `src/lib/api/profile.ts`

| Env var                                  | Default path       | Methods       | Notes                      |
| ---------------------------------------- | ------------------ | ------------- | -------------------------- |
| `NEXT_PUBLIC_PROFILE_ME_URL`             | `/me`              | `GET` `PATCH` | User profile read/update   |
| `NEXT_PUBLIC_PROFILE_PREFERENCES_URL`    | `/me/preferences`  | `GET` `PATCH` | Personal preferences       |
| `NEXT_PUBLIC_PROFILE_SIGN_OUT_ALL_URL`   | `/me/sign-out-all` | `POST`        | Revoke all other sessions  |
| `NEXT_PUBLIC_PROFILE_DELETE_ACCOUNT_URL` | `/me`              | `DELETE`      | Permanent account deletion |

**Security tab** — `src/lib/api/security.ts`

| Env var                                        | Default path                    | Methods        | Notes                             |
| ---------------------------------------------- | ------------------------------- | -------------- | --------------------------------- |
| `NEXT_PUBLIC_SECURITY_SESSIONS_URL`            | `/security/sessions`            | `GET`          | List active sessions              |
| `NEXT_PUBLIC_SECURITY_REVOKE_SESSION_URL`      | `/security/sessions`            | `DELETE /{id}` | Revoke one session                |
| `NEXT_PUBLIC_SECURITY_REVOKE_ALL_SESSIONS_URL` | `/security/sessions/revoke-all` | `POST`         | Revoke all other sessions         |
| `NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL`        | `/security/login-policy`        | `GET` `PATCH`  | Login policy (owner/admin)        |
| `NEXT_PUBLIC_SECURITY_POSTURE_URL`             | `/security/posture`             | `GET`          | Security posture summary          |
| `NEXT_PUBLIC_SECURITY_AUDIT_URL`               | `/security/audit-events`        | `GET`          | Recent audit events (owner/admin) |
| `NEXT_PUBLIC_SECURITY_CHANGE_PASSWORD_URL`     | _(empty)_                       | link           | Optional password-change link     |
| `NEXT_PUBLIC_SECURITY_AUDIT_EXPORT_URL`        | _(empty)_                       | link           | Optional audit export download    |

**Organization tab** — `src/lib/api/organization.ts`, `src/lib/api/team.ts`

| Env var                                            | Default path                    | Methods       | Notes                       |
| -------------------------------------------------- | ------------------------------- | ------------- | --------------------------- |
| `NEXT_PUBLIC_ORGANIZATION_PROFILE_URL`             | `/organization`                 | `GET` `PATCH` | Org profile read/update     |
| `NEXT_PUBLIC_ORGANIZATION_SETTINGS_URL`            | `/organization/settings`        | `GET` `PATCH` | Workspace defaults (admin+) |
| `NEXT_PUBLIC_ORGANIZATION_INGESTION_URL`           | `/organization/ingestion`       | `GET` `PATCH` | Ingestion config (admin+)   |
| `NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL`                | `/team/members`                 | `GET`         | List team members (admin+)  |
| `NEXT_PUBLIC_TEAM_MEMBERS_INVITE_URL`              | `/team/members/invite`          | `POST`        | Invite member (admin+)      |
| `NEXT_PUBLIC_TEAM_MEMBER_ROLE_UPDATE_URL_TEMPLATE` | `/team/members/{memberId}/role` | `PATCH`       | Update role (admin+)        |
| `NEXT_PUBLIC_TEAM_MEMBER_REMOVE_URL_TEMPLATE`      | `/team/members/{memberId}`      | `DELETE`      | Remove member (admin+)      |
| `NEXT_PUBLIC_ORGANIZATION_TRANSFER_OWNERSHIP_URL`  | _(empty)_                       | `POST`        | Transfer ownership (owner)  |
| `NEXT_PUBLIC_ORGANIZATION_ARCHIVE_URL`             | _(empty)_                       | `POST`        | Archive org (owner)         |
| `NEXT_PUBLIC_ORGANIZATION_EXPORT_URL`              | _(empty)_                       | `GET`         | Export org data (owner)     |
| `NEXT_PUBLIC_ORGANIZATION_DELETE_URL`              | _(empty)_                       | `DELETE`      | Delete org (owner)          |

**Billing tab** — `src/lib/api/billing.ts`

| Env var                                  | Default path              | Methods | Notes                                        |
| ---------------------------------------- | ------------------------- | ------- | -------------------------------------------- |
| `NEXT_PUBLIC_BILLING_PLAN_URL`           | `/billing/plan`           | `GET`   | Plan info (billing_admin/owner)              |
| `NEXT_PUBLIC_BILLING_USAGE_URL`          | `/billing/usage`          | `GET`   | Usage metrics (billing_admin/owner)          |
| `NEXT_PUBLIC_BILLING_QUOTAS_URL`         | `/billing/quotas`         | `GET`   | Quota status (billing_admin/owner)           |
| `NEXT_PUBLIC_BILLING_INVOICES_URL`       | `/billing/invoices`       | `GET`   | Invoice list (billing_admin/owner)           |
| `NEXT_PUBLIC_BILLING_CONTACT_URL`        | `/billing/contact`        | `GET`   | Billing contact read (billing_admin/owner)   |
| `NEXT_PUBLIC_BILLING_CONTACT_UPDATE_URL` | `/billing/contact`        | `PATCH` | Billing contact update (billing_admin/owner) |
| `NEXT_PUBLIC_BILLING_PORTAL_SESSION_URL` | `/billing/portal-session` | `POST`  | Create billing portal session                |

### Role and permission matrix

| Capability                                               | owner | admin | member    | viewer    |
| -------------------------------------------------------- | ----- | ----- | --------- | --------- |
| Profile — view/edit own profile and preferences          | yes   | yes   | yes       | yes       |
| Profile — sign out all devices                           | yes   | yes   | yes       | yes       |
| Profile — delete account                                 | yes   | yes   | yes       | yes       |
| Organization — view org profile                          | yes   | yes   | read-only | read-only |
| Organization — edit workspace defaults                   | yes   | yes   | no        | no        |
| Organization — team invite / role / remove               | yes   | yes   | no        | no        |
| Organization — danger zone (transfer / archive / delete) | yes   | no    | no        | no        |
| Security — view / revoke own sessions                    | yes   | yes   | yes       | yes       |
| Security — login policy (view/edit)                      | yes   | yes   | read-only | read-only |
| Security — security posture                              | yes   | yes   | no        | no        |
| Security — audit events                                  | yes   | yes   | no        | no        |
| Billing — view                                           | yes   | yes   | no        | no        |
| Billing — manage subscription/contact                    | yes   | yes   | no        | no        |

### Sensitive-value redaction

- **Auth tokens**: access tokens are never rendered. Refresh sessions are backend-managed via HttpOnly cookies, and the UI only shows a cookie/status indicator.
- **Passwords**: never exposed; password-change actions use the configurable external link `NEXT_PUBLIC_SECURITY_CHANGE_PASSWORD_URL`.
- **Billing card data**: card numbers, CVVs, and expiry dates are never displayed — subscription and card management always redirect to an external billing portal session.
- **API keys and signing secrets**: never shown in any settings view.
- **Raw chunk text, prompts, and retrieved document content**: chunking profile sections display stats only (token counts, strategy, reason codes) — never raw text.
- **Backend error messages**: never rendered verbatim; only safe request/trace IDs from `ApiClientError` payloads are exposed.
- Audit export transmits sanitized metadata only — no raw document text or prompt content.

### Local fallback for preferences

Only safe personal UI preferences are stored locally. No tokens, session data, or backend-derived private content are ever saved to local storage.

When `NEXT_PUBLIC_SETTINGS_PREFERENCES_LOCAL_FALLBACK=true` (default in non-production and when explicitly set):

1. Preferences are written to `localStorage` key `rudix.settings.preferences.v1` on every save.
2. On load: remote endpoint is tried first; local storage is used as fallback; factory defaults apply when both are absent.
3. Set `NEXT_PUBLIC_SETTINGS_PREFERENCES_LOCAL_FALLBACK=false` in production to remove the local fallback and make remote failures throw.

Fields covered: `defaultTopK`, `confidenceThreshold`, `rerankEnabled`, `developerMode`, `answerDetailLevel`, `showConfidenceScore`, `expandCitations`, and all `notifications.*` booleans. The RAG profile settings tab also exposes rerank provider/model, timeout, batch size, candidate limits, and fallback behavior controls.

Profile, Organization, Security, and Billing tabs do **not** use local fallback — they show unavailable states when backend endpoints are missing.

### Rollout notes

The settings tabs support progressive rollout. Leave any endpoint URL empty to show an unavailable state for that section, or point it at a live backend endpoint when ready:

1. Set the relevant `NEXT_PUBLIC_<GROUP>_*_URL` env vars to point at real backend endpoints.
2. Leave any endpoint URL empty when the backend is not yet implemented — the UI shows an unavailable state instead of an error.
3. Set `NEXT_PUBLIC_FEATURE_UNAVAILABLE_BACKEND_ENDPOINTS=false` only after a tab's full endpoint set is live and tested.

The settings E2E spec (`e2e/settings.spec.ts`) verifies unavailable-state behavior, token-flag redaction, and permission-aware tab access against stubs — no real backend is required.

### Testing Settings locally

```bash
# 1. Start the dev server — all tabs load; backend sections show unavailable state
npm run dev
# Navigate to http://localhost:3000/settings

# 2. Unit tests: API clients and Zod schemas
npm run test -- src/lib/api/settings.test.ts src/lib/schemas/settings.test.ts

# 3. Component tests: all four tab components and supporting sections
npm run test -- src/components/settings/

# 4. MSW contract tests: 501 stubs and 422 validation-error contracts
npm run test -- src/test/msw/settings-contracts.msw.test.ts

# 5. E2E smoke tests: auth redirect, tab nav, redaction, role-gating, save/discard
npm run test:e2e -- e2e/settings.spec.ts
```

## Setup

### 1. Install dependencies

```bash
cd frontend
npm install
```

### 2. Configure environment

Create a local env file:

```bash
cp .env.example .env.local
```

Required values:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_APP_URL=http://localhost:3000
NEXT_PUBLIC_QUERY_STALE_TIME_MS=10000
NEXT_PUBLIC_QUERY_RETRY_COUNT=1
NEXT_PUBLIC_DASHBOARD_MAX_DOCUMENT_ROWS=1000
NEXT_PUBLIC_DASHBOARD_MAX_CHAT_SESSION_ROWS=1000
NEXT_PUBLIC_DASHBOARD_ENABLE_ADMIN_USAGE=false
NEXT_PUBLIC_CHAT_MAX_INDEXED_DOCS=200
NEXT_PUBLIC_CHAT_SESSION_LIST_LIMIT=10
NEXT_PUBLIC_CHAT_TOP_K_MIN=1
NEXT_PUBLIC_CHAT_TOP_K_MAX=20
NEXT_PUBLIC_CHAT_TOP_K_DEFAULT=5
NEXT_PUBLIC_CHAT_AGENTIC_ENABLED=true
NEXT_PUBLIC_CHAT_AGENTIC_DEFAULT=false
NEXT_PUBLIC_AGENT_RUN_POLL_INTERVAL_MS=3000
NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB=25
NEXT_PUBLIC_EVALUATION_TOP_K_DEFAULT=5
NEXT_PUBLIC_EVALUATION_LOW_SCORE_THRESHOLD=0.5
NEXT_PUBLIC_AUTH_PROVIDER=app
NEXT_PUBLIC_FEATURE_DEVELOPER_MODE=false
NEXT_PUBLIC_FEATURE_EXPORTS_ENABLED=true
NEXT_PUBLIC_FEATURE_UNAVAILABLE_BACKEND_ENDPOINTS=true
NEXT_PUBLIC_AUTH_LOGIN_URL=
NEXT_PUBLIC_AUTH_SSO_URL=
NEXT_PUBLIC_AUTH_FORGOT_PASSWORD_URL=
NEXT_PUBLIC_AUTH_LOCAL_FALLBACK=true
NEXT_PUBLIC_AUTH_SIGNUP_URL=
NEXT_PUBLIC_AUTH_SIGNUP_SSO_URL=
NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK=true
NEXT_PUBLIC_AUTH_INVITE_ONLY=false
NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN=
NEXT_PUBLIC_AUTH_DEFAULT_REFRESH_TOKEN=
NEXT_PUBLIC_AUTH_REFRESH_URL=
NEXT_PUBLIC_AUTH_LOGOUT_URL=
NEXT_PUBLIC_AUTH_REFRESH_SKEW_SECONDS=60
NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL=/team/members
NEXT_PUBLIC_TEAM_MEMBERS_INVITE_URL=/team/members/invite
NEXT_PUBLIC_TEAM_MEMBER_ROLE_UPDATE_URL_TEMPLATE=/team/members/{memberId}/role
NEXT_PUBLIC_TEAM_MEMBER_REMOVE_URL_TEMPLATE=/team/members/{memberId}
NEXT_PUBLIC_SETTINGS_PREFERENCES_LOAD_URL=
NEXT_PUBLIC_SETTINGS_PREFERENCES_SAVE_URL=
NEXT_PUBLIC_SETTINGS_PREFERENCES_LOCAL_FALLBACK=true
NEXT_PUBLIC_SETTINGS_BILLING_URL=
NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL=
NEXT_PUBLIC_HELP_DOCS_URL=
NEXT_PUBLIC_HELP_SUPPORT_URL=
NEXT_PUBLIC_HELP_SHORTCUTS_URL=
NEXT_PUBLIC_HELP_README_URL=
NEXT_PUBLIC_PUBLIC_SITE_URL=http://localhost:3000
NEXT_PUBLIC_PUBLIC_APP_URL=
NEXT_PUBLIC_PUBLIC_PRODUCT_URL=
NEXT_PUBLIC_PUBLIC_SOLUTIONS_URL=
NEXT_PUBLIC_PUBLIC_SECURITY_URL=
NEXT_PUBLIC_PUBLIC_PRICING_URL=
NEXT_PUBLIC_PUBLIC_DOCS_URL=
NEXT_PUBLIC_PUBLIC_TRIAL_URL=
NEXT_PUBLIC_PUBLIC_DEMO_URL=
NEXT_PUBLIC_PUBLIC_CONTACT_URL=
NEXT_PUBLIC_PUBLIC_SECURITY_CONTACT_URL=
NEXT_PUBLIC_PUBLIC_STATUS_URL=
NEXT_PUBLIC_PUBLIC_LOGIN_URL=
NEXT_PUBLIC_CONTACT_SUBMIT_API_URL=
NEXT_PUBLIC_CONTACT_SUBMIT_MAILTO=
NEXT_PUBLIC_CONTACT_SUBMIT_EXTERNAL_URL=
NEXT_PUBLIC_CONTACT_SCHEDULER_URL=
NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER=
NEXT_PUBLIC_CONTACT_CAPTCHA_SITE_KEY=
NEXT_PUBLIC_ADMIN_MONITORING_URL=
NEXT_PUBLIC_SENTRY_DSN=
NEXT_PUBLIC_SENTRY_RELEASE=
NEXT_PUBLIC_SENTRY_ENVIRONMENT=
NEXT_PUBLIC_SENTRY_ERROR_SAMPLE_RATE=1
NEXT_PUBLIC_ADMIN_USAGE_EXPORT_URL=
NEXT_PUBLIC_ADMIN_HEALTH_REFRESH_INTERVAL_MS=
NEXT_PUBLIC_ORGANIZATION_ONBOARDING_RESUME_URL=
NEXT_PUBLIC_ORGANIZATION_ONBOARDING_SAVE_URL=
NEXT_PUBLIC_ORGANIZATION_ONBOARDING_COMPLETE_URL=
NEXT_PUBLIC_ORGANIZATION_ONBOARDING_LOCAL_FALLBACK=true
NEXT_PUBLIC_SUPPORT_URL=
NEXT_PUBLIC_SUPPORT_EMAIL=
```

`NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_APP_URL` are required and validated at startup/build time.  
Missing or invalid values stop production builds and render a safe startup error in runtime environments.

Do not place private secrets (API keys, service tokens, signing secrets) in any `NEXT_PUBLIC_*` variable.  
Only non-sensitive values intended for browser exposure should use the `NEXT_PUBLIC_` prefix.

If `NEXT_PUBLIC_AUTH_PROVIDER=app` and `NEXT_PUBLIC_AUTH_LOGIN_URL` is empty, set `NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN` to a valid backend app token. The backend manages refresh sessions through HttpOnly cookies, so the frontend no longer stores or sends refresh tokens in browser storage.
If refresh/logout endpoints are available, set `NEXT_PUBLIC_AUTH_REFRESH_URL` and `NEXT_PUBLIC_AUTH_LOGOUT_URL`; otherwise refresh can still use `/auth/token/refresh` with the cookie-backed session.
Set `NEXT_PUBLIC_FEATURE_DEVELOPER_MODE=true` to default the Settings preference toggle to developer mode.
Set `NEXT_PUBLIC_CHAT_FEEDBACK_ENABLED=true` to show chat feedback controls.
Set `NEXT_PUBLIC_FEATURE_EXPORTS_ENABLED=false` to hide CSV export actions globally, even when export URLs are configured.
Set `NEXT_PUBLIC_FEATURE_UNAVAILABLE_BACKEND_ENDPOINTS=false` to require full backend endpoint coverage before any Settings tab action is enabled; keep `true` (the default) while backend stubs are in place.
Team-management endpoints default to `/team/members*` on the same API base; keep these values unless your deployment uses custom routes.
Settings endpoint URLs default to the paths shown in `.env.example`; configure each URL to point at your backend or leave empty to show an unavailable state for that section (see [Settings Dashboard](#settings-dashboard) for the full endpoint table).
Set `NEXT_PUBLIC_SETTINGS_PREFERENCES_LOAD_URL` and `NEXT_PUBLIC_SETTINGS_PREFERENCES_SAVE_URL` to persist personal preferences remotely; leave both empty to use local storage only.
Set `NEXT_PUBLIC_SETTINGS_PREFERENCES_LOCAL_FALLBACK=false` in production to make remote preference failures throw instead of falling back to local storage.
Set `NEXT_PUBLIC_SETTINGS_BILLING_URL` to override the billing portal deep link shown in the Organization tab's admin action area.
Set `NEXT_PUBLIC_SECURITY_CHANGE_PASSWORD_URL` to show a change-password link in the Security tab (useful for external identity provider or password manager flows).
Set `NEXT_PUBLIC_SECURITY_AUDIT_EXPORT_URL` to enable the audit event export download in the Security tab.
Set `NEXT_PUBLIC_ADMIN_MONITORING_URL` to enable the Admin Monitoring card and deep link.
Set `NEXT_PUBLIC_SENTRY_DSN` to enable frontend observability event capture (breadcrumbs + sanitized exceptions). Leave it empty to keep monitoring disabled.
Set `NEXT_PUBLIC_SENTRY_ERROR_SAMPLE_RATE` to control client-side error sampling (`0` to disable transport, `1` for full sampling).
Set `NEXT_PUBLIC_ADMIN_USAGE_EXPORT_URL` to enable CSV export from Admin Usage.
Set `NEXT_PUBLIC_ADMIN_HEALTH_REFRESH_INTERVAL_MS` (milliseconds) to auto-refresh `/admin/system-health`; leave empty or `0` to disable.
Set `NEXT_PUBLIC_CHAT_AGENTIC_ENABLED=false` to hide agentic-mode execution in chat.
Set `NEXT_PUBLIC_CHAT_AGENTIC_DEFAULT=true` to start chat in agentic mode by default.
Set `NEXT_PUBLIC_AGENT_RUN_POLL_INTERVAL_MS` to control timeline polling for non-terminal agent run statuses.
Set `NEXT_PUBLIC_PUBLIC_*` URLs to override public marketing navigation and CTA destinations.
Set `NEXT_PUBLIC_PUBLIC_SECURITY_CONTACT_URL` to route security-review CTAs to a dedicated contact endpoint or mailbox.
Set `NEXT_PUBLIC_CONTACT_SUBMIT_API_URL` to post validated `/contact` form submissions directly to your endpoint.
Set `NEXT_PUBLIC_CONTACT_SUBMIT_MAILTO` to use a `mailto:` fallback when no API endpoint is configured.
Set `NEXT_PUBLIC_CONTACT_SUBMIT_EXTERNAL_URL` to route form submissions to a CRM/scheduling page when needed.
Set `NEXT_PUBLIC_CONTACT_SCHEDULER_URL` to show a secondary direct scheduling CTA on the contact page.
Set `NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER` and `NEXT_PUBLIC_CONTACT_CAPTCHA_SITE_KEY` to enable CAPTCHA placeholder inputs for provider integration.

### 3. Start dev server

```bash
npm run dev
```

Open `http://localhost:3000`.

## Scripts

| Command                     | Description                                                          |
| --------------------------- | -------------------------------------------------------------------- |
| `npm run dev`               | Start dev server                                                     |
| `npm run build`             | Build production bundle                                              |
| `npm run start`             | Run production server                                                |
| `npm run typecheck`         | TypeScript checks                                                    |
| `npm run lint`              | ESLint                                                               |
| `npm run test`              | Vitest tests                                                         |
| `npm run test:watch`        | Vitest watch mode                                                    |
| `npm run test:e2e`          | Playwright tests                                                     |
| `npm run api:generate`      | Regenerate TypeScript types from committed `openapi.json`            |
| `npm run api:check`         | Fail if generated types are stale (used in CI)                       |
| `npm run api:update-schema` | Fetch fresh `openapi.json` from running backend and regenerate types |

## API type generation

Frontend API types in `src/lib/api/generated/schema.d.ts` are generated from the backend's OpenAPI schema using [`openapi-typescript`](https://github.com/openapi-ts/openapi-typescript).

**Regenerate from committed schema** (no backend needed):

```bash
npm run api:generate
```

**Refresh schema from a running backend** (requires `make up-d`):

```bash
npm run api:update-schema
```

**Check for stale types** (runs automatically in CI via `make check-all`):

```bash
npm run api:check
```

API modules such as `src/lib/api/documents.ts` and `src/lib/api/chat.ts` import and re-export types directly from the generated schema:

```ts
import type { components } from "@/lib/api/generated/schema";
type Schemas = components["schemas"];

export type DocumentListResponse = Schemas["DocumentListResponse"];
```

When you add or change a Pydantic model on the backend, run `npm run api:update-schema` and commit both `openapi.json` and the updated `schema.d.ts`.

## Testing

Shared test harness and fixtures:

- `src/test/render.tsx`
  - `createTestQueryClient()` and `renderWithProviders()` for reusable TanStack Query + auth session setup.
- `src/test/navigation.ts`
  - reusable Next.js App Router mocks (`useRouter`, `usePathname`, `useSearchParams`) for component tests.
- `src/test/msw/fixtures.ts`
  - stable API fixture payloads for documents, chat, evaluations, pipeline, health, and admin usage.
- `src/test/msw/handlers.ts`
  - reusable MSW handlers built from the shared fixtures.
- `src/test/msw/server.ts`
  - `createMockApiServer()` utility for test-local MSW server lifecycle.

Playwright smoke coverage:

- `playwright.config.ts` runs the app with test-safe auth defaults.
- `e2e/smoke.spec.ts` covers:
  - login + protected-route redirect flow
  - dashboard load
  - documents load
  - chat load
- e2e API calls are intercepted in-browser, so tests do not require a running backend.
- Defaults:
  - `PLAYWRIGHT_FRONTEND_PORT=3101`
  - uses system Chrome channel by default for local runs
  - automatically uses bundled Playwright Chromium in CI
  - set `PLAYWRIGHT_USE_BUNDLED_BROWSER=true` to use Playwright-managed browser binaries instead
  - set `PLAYWRIGHT_FRONTEND_PORT` to a free port if another local app is already bound

CI-ready commands:

```bash
npm run typecheck
npm run lint
npm run test
npm run test:e2e
```

## Responsive / Supported Viewports

Rudix targets the following viewport baseline:

| Tier | Width | Example device |
|------|-------|----------------|
| Mobile | 375 px and up | iPhone SE / 13 mini |
| Tablet | 768 px and up | iPad portrait |
| Desktop | 1024 px and up | Laptop |
| Wide desktop | 1280 px and up | Full AppShell with sidebar + chat history |

Key responsive behaviours:
- **Mobile (< 640 px)**: the global search bar collapses to a search icon; the desktop sidebar is replaced by a "Menu" drawer; the onboarding checklist is clamped to the screen width.
- **Tablet (< 1024 px)**: the desktop sidebar is hidden; the search bar is shown.
- **Chat page**: the session-history sidebar is only rendered at ≥ 1280 px (`xl:`); session controls (new chat, search) are always in the chat header.
- **Tables**: all data tables are wrapped in `overflow-x-auto` so they scroll horizontally rather than clipping on narrow screens.
- **Public pages**: marketing/landing pages are responsive from 375 px upward using standard `sm:` / `md:` / `lg:` Tailwind breakpoints.

Responsive Playwright tests are in `e2e/responsive.spec.ts` and cover mobile, tablet, and desktop viewports for the main shell, chat, and public landing page.

## Notes

- `@radix-ui/react-dialog` and `@radix-ui/react-slot` were removed because they are not used in the current code.
- Typed frontend API clients are in `src/lib/api/*`. Request/response types are derived from the generated schema at `src/lib/api/generated/schema.d.ts`.
- Shared request handling includes bearer token and organization header injection from local session (when available), normalized API errors, and safe retry behavior for transient query failures.
- Shared UI state primitives are in `src/components/states/*` (`LoadingState`, `EmptyState`, `ErrorState`, `ForbiddenState`, `RateLimitState`, `RetryAction`) with safe trace/request ID rendering.
- TanStack Query defaults and mutation invalidation helpers are in `src/lib/api/query.ts`.
- Pipeline fallback graph/data remain in `src/lib/pipeline.ts`.
