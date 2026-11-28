# v0.7.0 — Detailed Implementation Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Implemented on `develop` (all nine packages merged; see section 9)
- `Last Updated`: 2026-11-28
- `Related Docs`: [V0_7_0_FRONTEND_PERFORMANCE.md](./V0_7_0_FRONTEND_PERFORMANCE.md),
  [V0_6_0_IMPLEMENTATION_PLAN.md](./V0_6_0_IMPLEMENTATION_PLAN.md),
  [V0_5_0_IMPLEMENTATION_PLAN.md](./V0_5_0_IMPLEMENTATION_PLAN.md),
  [V0_4_0_IMPLEMENTATION_PLAN.md](./V0_4_0_IMPLEMENTATION_PLAN.md),
  [01_EXECUTION_PLAN.md](./01_EXECUTION_PLAN.md), [../07_API_DESIGN.md](../07_API_DESIGN.md),
  [../09_FRONTEND_UI_DESIGN.md](../09_FRONTEND_UI_DESIGN.md),
  [../11_SECURITY_AND_PRODUCTION_CHECKLIST.md](../11_SECURITY_AND_PRODUCTION_CHECKLIST.md)

## 1. Purpose

Turn the `0.7.0` spec into nine work packages with exact files, symbols, tests, and owners of
shared files. Every reference was read on `develop` at `b72e4a70` (`0.2.0` to `0.6.0` merged,
not tagged). Line numbers drift; search for the quoted symbol.

Evidence rule: bundle sizes below come from `npm run build` run in a clean worktree on this
machine (Next.js 16.4.6, Turbopack, staging environment values as in CI), with the chunks
listed in `.next/diagnostics/route-bundle-stats.json` compressed by Node `zlib` at level 9.
HTML sizes come from `next start` and `curl` on the same build. No Core Web Vitals, Lighthouse,
or field latency figure is written down anywhere in this release, because none can be measured
reliably here. CI budgets are derived from measured build output with headroom.

The public pages were redesigned just before this release (`e9d7991f` to `80af8378`, merged in
`38fef3fe`). Nothing in `0.7.0` changes their design, copy, metadata, canonical URLs, or
crawlability: `R07-01` changes how they are rendered, not what they show, and the shared rule
for every package is "no restyling".

## 2. Plan check: what the code confirmed or changed

| Item | Result |
|---|---|
| R07-01 | **Changed.** `app/layout.tsx` calls `getLocale()` and `getMessages()` (cookie fallback in `src/i18n/request.ts`), so the build lists every `/[locale]/*` route as dynamic and `.next/prerender-manifest.json` holds only `/_global-error`, `/icon.svg`, `/robots.txt`, `/sitemap.xml`; `/en` answers `Cache-Control: private, no-cache, no-store`. Locales are six (`en de es fr ar fa`), not four; the parity test checks all six. Next 16 can only prerender per locale when the locale is a root parameter, so `app/layout.tsx` is replaced by two root layouts, `app/[locale]/layout.tsx` and `app/(app)/layout.tsx`. Navigating between the groups becomes a full page load. `/status` (`force-dynamic`, live data), `/forbidden` and `/403` (`searchParams`) stay dynamic. |
| R07-02 | **Changed.** 53 namespaces, 6,102 leaf keys (spec: 5,961); `en.json` 346,716 bytes, `fa.json` 483,723. Two providers exist (root and `[locale]` layout), but they pass the same imported object, which React serialises once: `/en` is 327,323 bytes of HTML (89,731 gzip), `/de/product` 359,061, and the `public` namespace alone is 84 KB. The payload goal is met with `pick` per root layout; splitting the six files into 318 namespace files would rewrite 18 importers without changing what is shipped, so the files stay whole (section 6). |
| R07-03 | **Changed.** Next 16.4.6 prints no size column. First-load JS (gzip): marketing pages 195.0–200.2 KB (`/[locale]` 199.4, `/[locale]/pricing` 198.5), login, contact, accept-invite, onboarding 245.0–251.1 KB, app routes 265.1–395.2 KB (`/dashboard` 275.6, `/documents` 295.5, `/chat` 320.4, `/reports` 395.2). Shared framework chunks: React DOM 69.6 KB, Next runtime 44.0 KB. `zustand`, `motion`, `@tanstack/react-table`, `class-variance-authority` have no import in `src`; `eslint-config-next` is already `16.4.6`, equal to `next`; `public/next.svg`, `vercel.svg`, `file.svg`, `globe.svg`, `window.svg` are unreferenced. `recharts` is imported by seven files, `@xyflow/react` by `RagPipelinePage.tsx`; Next already optimises `lucide-react` and `recharts` imports by default (bundled docs, `optimizePackageImports`). The 150 KB marketing target is below what the framework chunks plus the current shell allow; CI budgets are the measured figures plus headroom, and the spec targets are recorded as goals. |
| R07-04 | **Changed.** The redesigned public pages draw about 150 distinct Material Symbols through `SiteIcon` (`components/public/site/primitives.tsx`); 281 references in 55 files. Replacing them with `lucide-react` would restyle the redesign, so the stylesheet is replaced by a self-hosted subset of the symbols in use (one-time download, section 4.2.8). `public/brand/rudix-mark.svg` (303,577 bytes) wraps a base64 PNG of 441×589 px; `app/icon.svg` and `app/favicon.svg` are byte-identical copies. CSP (`config/security-headers.mjs`) allows `fonts.googleapis.com` and `fonts.gstatic.com`. |
| R07-05 | **Changed.** 84 modules in `src/lib/api`; 4 import the generated schema (`documents`, `chat`, `evaluations`, `notification-center`). 39 of 522 operations in `openapi.json` have no typed 2xx JSON schema, mostly exports, downloads, SCIM, and bot webhooks; the frontend consumes four: `GET /agent/runs/{run_id}/trace`, `GET /agent/traces/shared/{token}`, `GET /admin/metadata/filter-documents`, `POST /security/sessions/revoke-all`. |
| R07-06 | **Changed.** Cursor pagination exists on sessions, messages, documents, notifications, audit logs, and webhook deliveries only. Collections, collection documents, team members, and verified answers have `limit` (max 200), `offset`, and `total`, which is enough for a count and "load more"; no backend change for them. About 17 call sites in 11 files ask for 200 rows; `useCitationPanel` loads 200 chunks to find one (an additive `chunk_id` filter fixes it); `DashboardPage` sums chunk counts over at most `NEXT_PUBLIC_DASHBOARD_MAX_DOCUMENT_ROWS` documents without saying so. |
| R07-07 | **Changed.** No per-user stream exists. `GET /agent/runs/{run_id}/stream` (0.6.0) is SSE with bearer authentication, a Redis buffer, and database polling fallback; the frontend still polls it. 23 interval sites in 16 files (`refetchInterval` or `setInterval(`), six with `refetchIntervalInBackground: true`. `EventSource` cannot send headers and the `R02-10` ticket is a WebSocket handshake ticket, so the stream is read with `fetch` and a bearer header (never a token in the URL). Without Redis the new endpoint answers `503 realtime_unavailable` and the client keeps polling. |
| R07-08 | Confirmed: no `global-error.tsx`, no segment `error.tsx` or `loading.tsx`; `app/error.tsx` is English only. `global-error.tsx` replaces the root layout, so it cannot use the message provider; its strings come from a small per-locale table. |
| R07-09 | **Changed.** The refresh cookie is `HttpOnly`, `SameSite=lax` (default), `Secure` in production, `Path=/api/v1/auth`, and host-only on the API host, so `src/proxy.ts` on the frontend host can never see it. An additive session-hint cookie (no token, `Path=/`) is set and cleared with it. `refreshAccessToken({ trigger: "startup" })` returns without calling the backend when no token is stored, so today nothing restores a session without `localStorage`. A reused refresh token revokes every session of the user, so tabs must keep refreshing one at a time. The Playwright suites seed `rudix.session.v1` with `addInitScript`; the legacy read keeps them working. `/knowledge` is missing from `AUTHENTICATED_APP_ROUTE_SEGMENTS`, so the proxy treats it as a public path. |
| R07-10 | **Changed.** 27 files over 1,000 lines and 74 over 500 (excluding tests and generated files); 87 `queryKey: [` literals. Not all can be split in this release without colliding with other items; section 3 assigns each large file to one package and section 6 lists the rest. |
| R07-11 | **Changed.** `POST /analytics/events` exists but needs a signed-in user and stores product events in Postgres with a fixed event-name enum. A separate first-party endpoint, off by default, records Web Vitals as Prometheus histograms only. Sending anything to a third party is not approved. The hand-rolled Sentry client posts to the legacy `/api/<project>/store/` endpoint; moving it to the envelope endpoint keeps the same, owner-configured destination. |
| R07-12 | **Changed.** 122 component files have no `useTranslations`/`getTranslations`, 62 of them with literal JSX text. Public and legal page components are excluded (redesigned copy; translating legal text is an owner decision). Automated accessibility checks need `@axe-core/playwright` (not approved). Only Chromium is installed for Playwright here. |
| Dependencies | `0.4.0` keyset pagination (`R04-04`), `0.5.0` SSE framing (`app/application/chat/transports/sse.py`), `0.6.0` agent run stream. `R05-12` (Markdown rendering) is not approved and not touched. No migration is needed; Alembic head stays `20261128_0003`. |

## 3. Sequence

| Chain | Order | Task | Items | Model | Review |
|---|---|---|---|---|---|
| S | 1 | S1 | R07-01 static public pages, R07-02 message picking | opus | frontend |
| A | 1 | A1 | R07-03 code splitting, dependency cleanup, bundle budgets | sonnet | frontend |
| A | 2 | A2 | R07-04 icons, fonts, images; R07-08 route boundaries; R07-11 field measurement (first-party part) | sonnet | api |
| B | 1 | B1 | R07-09 in-memory access token, session-hint cookie, server-side route gate | opus | api |
| C | 1 | C1 | R07-05 generated API types in every client module | sonnet | api |
| C | 2 | C2 | R07-10 part 1 (documents and collections pages), R07-06 real pagination | opus | api |
| C | 3 | C3 | R07-07 realtime event stream, `useRealtime()`, polling fallback, agent run SSE consumer | opus | api |
| D | 1 | D1 | R07-10 part 2 (connector setup, permissions, settings, admin pages) | sonnet | frontend |
| D | 2 | D2 | R07-12 translations (chat, trust panel, evaluations, states), lint rule, extra browsers | sonnet | frontend |

S1 runs first and alone; A, B, C, and D start after S1 is merged. No package adds a migration.
If one becomes unavoidable it goes into chain C as `20261129_0001` with
`down_revision = "20261128_0003"`; any other package stops and reports.

Model reasons: S1 rewrites the root of every route (two root layouts, Next 16 conventions that
differ from older versions, SEO parity, a missing namespace breaks a page). B1 is token storage,
cookies, CSRF, and the server-side gate. C2 changes query keys and invalidation of paged lists.
C3 is a push protocol with authentication, organisation scope, and cache invalidation. The
others are mechanical or fully specified, and every branch is reviewed by Opus.

## 4. Shared files and contracts

### 4.1 Owners and anchors

Every task re-reads a shared file before editing it, edits only its anchor with `Edit`, never
rewrites a shared file whole or reformats it, and re-reads after a failed `Edit`.

| File | Task: anchor |
|---|---|
| `src/app/layout.tsx` | S1 deletes it. |
| `src/app/[locale]/layout.tsx`, `src/app/(app)/layout.tsx` | S1 only. |
| `src/components/layout/RootDocument.tsx` (S1 creates: `<html>`, `<body>`, fonts, providers) | A2 only, at `{/* anchor: A2 head */}` (the Material Symbols link) and `{/* anchor: A2 body */}` (Web Vitals reporter; S1 places it inside `ConsentProvider`, next to `CookieConsentBanner`). |
| `src/app/global-error.tsx`, segment `error.tsx` and `loading.tsx` | S1 moves `app/error.tsx` to `[locale]/error.tsx` and `(app)/error.tsx` unchanged; A2 owns them afterwards. |
| `src/i18n/namespaces.ts` (S1 creates `PUBLIC_NAMESPACES`, `APP_NAMESPACES`) | A package that adds a top-level namespace adds it here in the same commit (D2 only, expected). |
| `src/i18n/messages/*.json` (all six, always together) | New keys only, never reordered: A2 last keys of `errors` (`routeBoundary`); B1 last keys of `auth`; C2 last keys of `common` (`pagination`); C3 last keys of `appShell` (`realtime`); D2 inside the namespaces of the files it translates and new top-level namespaces inserted directly after `languageSwitcher`. D1 adds none. |
| `src/lib/api/query.ts` (`queryKeys`) | S1 adds `// anchor: C` as the first line inside `queryKeys` and `// anchor: D` as its last line. C2 and C3 add groups after `// anchor: C`; D1 after `// anchor: D`. New factory entries return the same arrays as the literals they replace. |
| `src/lib/api/*.ts` | C1 owns all except `request.ts`, `session.ts`, `auth.ts` (B1) and the new `web-vitals.ts` (A2). After C1: C2 edits list functions in `documents.ts`, `collections.ts`, `team.ts`, `verified-answers.ts`; C3 adds `events.ts`. |
| `src/lib/api/request.ts`, `auth-session.ts`, `auth-refresh-coordinator.ts`, `use-auth-session.ts`, `src/proxy.ts`, `src/lib/app-route-paths.ts`, `ProtectedAppLayout.tsx`, `src/test/render.tsx` | B1 only. |
| `src/components/layout/AppShell.tsx` | C3 only (wraps its children in `RealtimeProvider`). Nobody splits it in `0.7.0`. |
| `components/chat/SourceScopeSelector.tsx`, `ScopeControls.tsx`, `ScopeConnectorSection.tsx`, `chat/hooks/useChatSourceQueries.ts`, `chat/hooks/useCitationPanel.ts` | C2 only; D2 leaves them out of its translation and lint scope. |
| A1's lazy modules (`DocumentPreviewModal`, `TrustPanelModal`, the seven chart files, `RagPipelinePage.tsx`, the settings tab container) | A1 only. |
| Files D1 splits | D1 only; their module paths and export names stay, because A1 lazy-loads the settings tabs by path. |
| `frontend/openapi.json`, `src/lib/api/generated/schema.d.ts` | Regenerated with `npm run api:update-schema` by A2, C1, C2, C3 after an API change. On conflict regenerate on the merged tree; never hand-merge or hand-edit. |
| `next.config.ts` | S1 (`experimental.globalNotFound` only if the build requires it); A1 adds `experimental.optimizePackageImports`; A2 adds top-level `images` after `distDir`. |
| `package.json`, `package-lock.json` | A1 removes dependencies (lockfile via `npm uninstall`); C1 adds the script `api:check-handwritten` after `api:check`; A2 adds `icons:check` after `format:write`. No other package changes dependencies. |
| `vitest.config.ts` | B1 adds `.next-e2e-gate/**` after `.next-e2e-ws/**` in `exclude`. Thresholds are never lowered; the release integrator raises them. |
| `eslint.config.mjs` | B1 adds `.next-e2e-gate/**` after `.next-e2e-main/**`; D2 appends one config object at the end of the array. |
| `playwright.config.ts` | A2 adds `NEXT_PUBLIC_E2E_ERROR_PROBE: "true"` to the `env` of `devServer()`; B1 appends project `chromium-route-gate` after `chromium-chat-ws` and a third `webServer` entry; D2 inserts its `firefox` and `webkit` projects at the start of `projects`. C3 does not edit it. |
| `config/security-headers.mjs` and test | A2 only. `config/build-env-validation.mjs`: A2 (refuse `NEXT_PUBLIC_E2E_ERROR_PROBE` in staging/production). |
| `.github/workflows/ci.yml` (frontend job) | S1 adds step "Check prerendered public routes" after "Build frontend"; A1 adds "Check bundle budgets" after it; C1 adds "Check hand-written API types" after "Verify generated API types". `playwright.yml`: D2 only. |
| `backend/app/api/router.py` | A2 after `api_router.include_router(public_status.router)`; C3 after `protected_router.include_router(org_memory.router)`. |
| Backend settings | B1 `app/core/settings/auth.py` (end of `AuthSettings`); A2 `app/core/settings/observability.py` (end); C3 new `app/core/settings/realtime.py` and the `Settings` bases in `app/core/config.py` (C3 only). Metrics in new modules (`app/core/metrics_frontend.py` A2, `app/core/metrics_realtime.py` C3); `app/core/metrics.py` is not edited. |
| `.env.example` (root) | S1 adds `# --- Frontend performance (0.7.0) ---` with markers `# anchor: A2`, `# anchor: B1`, `# anchor: C2`, `# anchor: C3`. |
| `docs/07_API_DESIGN.md` | B1: `#### Session hint cookie` after `#### SSO callback redirects`; C1: the agent trace, metadata, and security sections it types; C2: `chunk_id` under the document chunks section; C3: new `## Realtime events` before `## Agent runs`; A2: new `## Frontend telemetry` before `## Status codes`. |
| `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` | B1: `## Authentication`; A2: `## Security headers`; C3: new `## Realtime events` before `## File upload security`. |
| `docs/12_EVALUATION_AND_MONITORING.md` | One `###` subsection per task (A1, A2, C3), inserted before `## Continuous evaluation`. |
| `frontend/README.md` | One `### <topic> (R07-xx)` subsection per task, directly before `## Dashboard Design Sample`, in merge order; env variables in the setup list. |
| `backend/README.md` | B1, A2, C3 add bullets at the end of the section their settings belong to. |
| `docs/CHANGELOG.md` | One line per task under `[Unreleased]` `### Added`, directly after the line starting "- `docs/roadmap/V0_7_0_IMPLEMENTATION_PLAN.md`". |

### 4.2 Contracts between chains

1. **Worktrees and checks.** Branch `feat/v0.7.0-<task>` in worktree `../rudix-v070-<task>`
   cut from the current `develop`; `cd frontend && npm ci`. A branch that changes nothing under
   `backend/` skips the backend suites and the test database. A backend branch runs
   `cd backend && make install` and uses database `rudix_test_<chain>` on `127.0.0.1:55432`
   (snippet in the `0.4.0` plan section 4.2 item 1); if `rudix-test-pg` is not running, report
   it, do not start it. Restore `frontend/AGENTS.md` and `frontend/tsconfig.json` with
   `git checkout --` before each commit after any Next.js command.
2. **Root layouts (S1).** `RootDocument({ locale, messages, children })` renders `<html lang dir
   className="h-full antialiased">`, `<head>`, and `<body>` with `NextIntlClientProvider`,
   `ConfigErrorBanner` or `AppQueryProvider` + `ConsentProvider` + `CookieConsentBanner`,
   exactly as `app/layout.tsx` does today. `ROOT_METADATA` (`src/lib/root-metadata.ts`) is
   exported by both root layouts. Pages under `[locale]` call `setRequestLocale(locale)` before
   any server translation. Nothing under `[locale]` may read `cookies()` or `headers()` except
   `/status`, `/forbidden`, `/403`.
3. **Message picking (S1).** `pickMessages(messages, namespaces)` in `src/i18n/messages.ts`.
   Nested `NextIntlClientProvider`s do not merge messages: a nested provider passes the union.
   Server components can read every namespace. A missing namespace is caught by
   `src/i18n/public-namespaces.test.tsx` (renders every public page with only the picked
   namespaces and `onError` throwing) and by the console check in
   `e2e/public-static-parity.spec.ts`.
4. **Public parity (S1 records, everyone keeps).** `e2e/fixtures/public-parity-baseline.json`
   is recorded with the pre-S1 code (`PUBLIC_PARITY_UPDATE=1`): per public path and locale the
   `<title>`, meta description, robots, canonical, hreflang alternates, Open Graph and Twitter
   tags, JSON-LD, `<html lang dir>`, a hash of the visible text of `<main>`, and a hash of the
   tag and class sequence of `<main>`. It is never re-recorded in `0.7.0`; a package whose
   change alters it has changed the public pages and must be reworked.
5. **Session API (B1).** Signatures unchanged: `getSessionRequestContext()`,
   `refreshAccessToken()`, `useAuthSession()`, `getSessionSnapshot()`, `persistSession()`,
   `clearSession()`. C3 reads the token only through `getSessionRequestContext()` and retries a
   `401` once after `refreshAccessToken({ trigger: "request" })`.
6. **Event envelope (C3).** SSE frame `id: <n>`, `event: <type>`, `data:
   {"type","organization_id","occurred_at","payload"}`. Types and payloads: `document.status
   {document_id, status}`, `documents.changed {}`, `notification.created {notification_id}`,
   `connector.sync {connection_id, run_id, status}`, `agent.run {run_id, status}`, `incident
   {incident_id, status}`. Payloads carry ids and statuses only, never names, text, or errors.
7. **Lazy modules (A1).** A heavy component keeps its module path and export name; the module
   becomes a `next/dynamic` wrapper over `<Name>Content.tsx`. Other packages never import the
   `Content` module.
8. **Icon subset (A2).** `scripts/material-symbols-subset.mjs` collects symbol names from the
   source (`name=`, `icon=`, `icon:` and literal `material-symbols-outlined` children) into
   `config/material-symbols.json`; a one-time download of the Google Fonts subset for those
   names is committed as `public/fonts/material-symbols/material-symbols-outlined.woff2` with its
   Apache-2.0 notice. `npm run icons:check` (A2) fails when the source uses a name not in the
   list. A package that adds a symbol name re-runs the script; without network access, it uses
   a name already in the list.

## 5. Steps per item

### R07-01 and R07-02 — Static public pages and message picking (S1)

First commit: the parity baseline (4.2.4) and `e2e/public-static-parity.spec.ts`, recorded
against the current code. Then `RootDocument`, the two root layouts, `generateStaticParams`
(six locales) and `dynamicParams = false` in `[locale]/layout.tsx`, `setRequestLocale` in every
`[locale]` layout and page, `global-not-found` only if the build requires it, the moved error
pages, `pickMessages` with `PUBLIC_NAMESPACES` for `[locale]` and `APP_NAMESPACES` (everything
the app uses) for `(app)`, and `scripts/check-prerendered-routes.mjs` over
`config/static-public-routes.json` (every sitemap path except `/status`, kept equal to the
sitemap by a test). Docs: frontend README, docs/11 `## Security headers` (the nonce note no
longer says pages render dynamically), docs/09.

### R07-03 — Code splitting and budgets (A1)

`next/dynamic` at module boundaries (4.2.7) for the chart blocks of the seven `recharts` files,
the flow canvas of `RagPipelinePage.tsx`, `TrustPanelModal`, `DocumentPreviewModal`, and the
settings tabs at their container. `experimental.optimizePackageImports` only for a package
not in Next's default list and only if the build output shows a reduction. Remove the four unused dependencies and five unreferenced SVGs.
`scripts/check-bundle-budgets.mjs` reads `route-bundle-stats.json`, gzips each first-load
chunk, prints a per-route table, writes `bundle-report.json`, and fails when a route exceeds
`config/bundle-budgets.json` (measured after A1, plus 5 percent, rounded up to the next KB;
it fails loudly if the stats file is missing).

### R07-04, R07-08, R07-11 — Assets, boundaries, field measurement (A2)

Self-hosted Material Symbols subset (4.2.8) loaded with `@font-face` and `font-display: block`
from `globals.css`; CSP without Google Fonts; brand mark re-encoded at twice its largest
rendered size with the same path and `viewBox`; `app/icon.svg` and `app/favicon.svg`
re-encoded small under the same paths, so the `<head>` icon tags do not change; `images.formats` `["image/avif", "image/webp"]`. `global-error.tsx` with a
six-locale string table; translated `error.tsx` and `loading.tsx` (`SkeletonBlock`) for chat,
documents, collections, admin, settings, reports, plus `[locale]/error.tsx`. Web Vitals:
`useReportWebVitals` behind `NEXT_PUBLIC_WEB_VITALS_ENABLED` (default `false`) and analytics
consent, `POST /api/v1/telemetry/web-vitals` behind `WEB_VITALS_INGEST_ENABLED` (default
`false`), histogram `rudix_web_vitals_value{metric,route}`, Grafana dashboard. Sentry client to
the envelope endpoint.

### R07-09 — Token in memory, route gate (B1)

`src/lib/auth/session-store.ts` (memory, `useSyncExternalStore`), legacy `rudix.session.v1`
read once and removed after a successful refresh (`AUTH_LEGACY_SESSION_READ`, kept until
`0.8.0`), startup refresh without a stored token, serial cross-tab refresh under the existing
lease, dev-only `sessionStorage` for the local fallback. Backend `rudix_session_hint` cookie
with the refresh cookie (`APP_AUTH_SESSION_HINT_COOKIE_ENABLED`, default `false`). Proxy gate
`RUDIX_ROUTE_GATE=off|enforce` (default `off`). Playwright project `chromium-route-gate`.
CSRF: both cookies stay `HttpOnly` and `SameSite=Lax` by default; when
`APP_AUTH_COOKIE_SAME_SITE=none`, refresh and logout reject an `Origin` outside `CORS_ORIGINS`.

### R07-05 — Generated API types (C1)

One commit per domain, highest traffic first; exported names kept as aliases of
`components["schemas"][...]`; Pydantic models for the four untyped endpoints with a JSON
snapshot test proving the same keys; `scripts/check-api-handwritten-types.mjs`.

### R07-10 part 1 and R07-06 — Documents, collections, pagination (C2)

Split `DocumentDetailPage.tsx`, `DocumentsPage.tsx`, `CollectionsPage.tsx` into route shells,
hooks, tables, filters, and dialogs under 500 lines each with existing tests unchanged; then
`useInfiniteQuery` lists with a count and "Load more", server-side search for selectors,
virtualised rows above `NEXT_PUBLIC_TABLE_VIRTUALIZE_MIN_ROWS` (200), `chunk_id` on
`GET /documents/{document_id}/chunks`.

### R07-07 — Push instead of polling (C3)

`GET /api/v1/events/stream` (`REALTIME_EVENTS_ENABLED`, default `false`), Redis pub/sub per
organisation with a bounded replay buffer, audience filtering, publication after commit; the
frontend `RealtimeProvider` in `AppShell`, invalidation map, `useRealtimeAwareInterval()` in all
23 polling sites (no polling while connected, a longer fallback interval when disconnected, no
polling in hidden tabs), and the agent run stream consumer deferred from `0.6.0`.

### R07-10 part 2 — Remaining large components (D1)

Behaviour-preserving splits of `ConnectorSetupPage`, `AdminPermissionsPage`,
`OrganizationSettingsTab`, `SecuritySettingsTab`, `BillingSettingsTab`, `UserProfilePage`,
`AdminFeedbackReviewPage`, `AdminTeamPage`, `AdminMCPPage`, `AdminAuditLogsPage`,
`AdminServiceAccountsPage`, `AdminAIResponsePolicyPage`, with their ad-hoc query keys.

### R07-12 — Translations and checks (D2)

Translate the trust panel sections, chat modals and shared pages, evaluations components, and
`components/states`, plus the three dataset-builder lists (R07-06 for that file), leaving out
the chat scope files C2 owns and A1's lazy modules. A
`no-restricted-syntax` rule for literal JSX text and literal `aria-label`, `title`,
`placeholder`, `alt` values, as an error in the translated directories. Opt-in Firefox and
WebKit Playwright projects for the public, smoke, and responsive specs.

## 6. Deferred

- Splitting the message files physically by namespace; per-segment picking inside `(app)`.
- `@next/bundle-analyzer` (dev dependency, not approved); the build-output fallback is used.
- The spec budgets that the measured output does not meet (150 KB marketing, 300 KB app shell
  on the largest routes) stay goals; CI enforces measured figures plus headroom.
- Moving the `@xyflow/react` and `intro.js` stylesheets out of `globals.css` (cascade order;
  needs a visual check).
- The Material Symbols subset if no network access is available to the implementer; the
  stylesheet and its CSP allowance then stay.
- Official Sentry SDK and source-map upload (approval). Any third-party or outbound Web Vitals
  reporting (approval). Field data and the staging dashboard with real traffic.
- `@axe-core/playwright` accessibility checks (approval). Translating public and legal page
  copy (owner decision). Remaining untranslated components outside D2's directories.
- Files still over 500 lines after C2 and D1 (`AgentWorkspacePage`, `DashboardPage`,
  `EvaluationsPage`, `AppShell`, `ConnectorConnectionDetailPage`, `DocumentPreviewModal`,
  `AdminSecurityCenterPage`, `RagPipelinePage`, `AdminSourceHealthPage`, `request.ts`, and
  about 50 between 500 and 1,000 lines).
- Turning on by default: `REALTIME_EVENTS_ENABLED`, `NEXT_PUBLIC_REALTIME_ENABLED`,
  `APP_AUTH_SESSION_HINT_COOKIE_ENABLED`, `RUDIX_ROUTE_GATE=enforce`, Web Vitals; each after
  staging. Removing the legacy session read (`0.8.0`). A CSP nonce (static pages rule it out).
- `R05-12` rich answer rendering (renderer not approved).

## 7. Verification for the release

```bash
cd frontend && npm ci && npm run format && npm run lint && npm run typecheck
cd frontend && npm run test:coverage && npm run api:check && npm run api:check-handwritten
cd frontend && npm run build && node scripts/check-prerendered-routes.mjs \
  && node scripts/check-bundle-budgets.mjs && npm run icons:check
cd frontend && PLAYWRIGHT_USE_BUNDLED_BROWSER=true npx playwright test
cd backend && make lint && make test && make test-cov
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://rudix:rudix@127.0.0.1:55432/rudix_test make test-postgres
cd backend && .venv/bin/python scripts/export_openapi.py --check ../frontend/openapi.json
find frontend/src -name '*.ts*' ! -name '*.test.*' ! -path '*/generated/*' | xargs wc -l | sort -rn | head -40
```

Coverage stays at or above the ratchets (backend 82.2; frontend lines 66.0, statements 65.1,
functions 59.1, branches 58.5). `alembic heads` reports `20261128_0003`. The Playwright count is
at least 233 plus the new tests. The prerender check lists every path of
`config/static-public-routes.json` for all six locales, and the parity spec passes.

## 8. Manual steps (staging and production)

1. Set `APP_AUTH_SESSION_HINT_COOKIE_DOMAIN=.getrudix.com` (staging: the staging parent
   domain), enable the hint cookie, wait one refresh-token lifetime, then set
   `RUDIX_ROUTE_GATE=enforce` on the frontend; confirm a signed-out request to `/dashboard`
   redirects before any HTML of the shell, and a signed-in reload keeps the session.
2. Enable `REALTIME_EVENTS_ENABLED` with Redis; across two API replicas confirm document status
   changes appear within two seconds and the documents page sends no periodic requests;
   watch `rudix_realtime_connections` and reconnects.
3. Enable Web Vitals (backend and frontend) behind consent; check the Grafana panel per route.
4. Crawl the public site (Search Console URL inspection, `curl -A Googlebot`): status 200,
   cacheable static responses, unchanged canonical and hreflang, no `noindex`.
5. Run the Firefox and WebKit projects in CI once the workflow installs those browsers.

## 9. Status (2026-11-28)

All nine packages are merged into `develop`, in this order: S1 (static public pages, message
picking), A1 (code splitting, bundle budgets), D1 (remaining large components), C1 (generated
API types), B1 (token in memory, session hint, route gate), A2 (icons, route boundaries, Web
Vitals), D2 (translations, lint rule, extra browsers), C2 (documents and collections split,
pagination), C3 (realtime event stream). No migration was added; `alembic heads` reports
`20261128_0003`.

Checked on `develop` plus the integration changes (frontend build with the CI staging values,
no secrets):

- Backend: `make lint` passes (ruff; mypy on 942 files); `ruff format --check` passes;
  `make test` 6,213 passed, 395 skipped; `make test-cov` 82.59% with a local `.env` and 82.46%
  without one, as in CI (ratchet raised from 82.2 to 82.4); `make test-postgres` 355 passed,
  5 skipped (4 need `TEST_REDIS_URL`; `tests/test_rls_enforcement_pg.py`, which needs
  `TEST_MIGRATIONS_DATABASE_URL`, passed 21 of 21 when run with it). The OpenAPI contract check
  passes with and without `.env`.
- Frontend: format, typecheck and lint pass (0 errors, 2 older warnings); Vitest 2,805 passed
  in 273 files, twice, with coverage 68.66-68.67% statements, 60.88-60.9% branches, 62.19%
  functions, 69.57-69.58% lines (ratchets raised from 65.1, 58.5, 59.1, 66.0 to 68.6, 60.8,
  62.1, 69.5, the lower run rounded down); `api:check`, `api:check-handwritten` (72 modules)
  and `icons:check` (204 names used, 234 listed) pass; `npm run build` passes and
  `check-prerendered-routes.mjs` finds all 144 static public routes (24 paths, six locales);
  Playwright 410 passed (Chromium projects, including the 162 public parity tests on the
  default port 3101 and the route-gate project).
- Files over 500 lines (section 7 command, excluding tests and generated files): 58, of which
  11 are over 1,000 (74 and 27 at `b72e4a70`). Every file named in R07-10 part 1 and part 2 is
  under 500 lines.
- No setting, alias, or metric name is defined twice; every package has one
  `docs/CHANGELOG.md` entry (a stray blank line between two of them is removed); docs/README.md
  lists this plan once; the anchors of section 4.1 in docs/07, docs/11, docs/12, the frontend
  README and `.env.example` are all present.

Not met or not verified:

- Bundle budgets: `check-bundle-budgets.mjs` failed on `/documents`, 339.9 KB gzip against
  334. Measured at each merge point: 317.6 after A1, 318.2 after B1, 327.3 after A2 (A2 added
  about 8 to 10.6 KB to every route, marketing pages included: `/[locale]/product` 228.8 to
  239.3), 338.9 after C2 (+11.6), 339.9 after C3. C2 was branched before A2 was merged, so the
  two increases met only on `develop`. Fixed afterwards without changing a budget: the Web
  Vitals collector loads with `React.lazy` instead of `next/dynamic` (the root layout no
  longer ships the `next/dynamic` loader; 1.1 to 1.3 KB off every route that does not use it
  elsewhere), and the documents page loads its virtual rows, upload, delete and
  assign-collections dialogs on demand (the assign dialog was imported through the
  `CollectionsPage` module). `/documents` is now 315.2 KB against 334 and `/[locale]/product`
  238.4 against 240; every route is within its budget.
- Spec targets stay goals (section 6): marketing 238.4 KB against 150; ordinary app routes up
  to 318.1 KB (`/user/profile`) against 300; `/chat` 355.4 KB.
- R07-10 "no component over 500 lines" holds only for the files this release split; the other
  58 are listed in the frontend README.
- R07-06 is partly met: for non-admin roles `GET /documents` returns `total` equal to the
  length of the policy-filtered page, so offset-paged pickers never offer "Load more" to
  members (cursor mode, the default documents table, is unaffected); this needs a backend
  contract decision. `EvaluationsPage` still loads 200 questions per set without a count.
- `make audit` fails on the dev-only `virtualenv` 21.14.5 (13 advisories, allowlisted in the
  CI security gate until langfuse is upgraded); `virtualenv` is unchanged in this release.
- Firefox and WebKit projects were not run here (only Chromium is installed); CI is their
  first run. The 4 live-Redis tests did not run (no Redis test instance).
- `adminPermissions.outcomes.pass` is missing from the message catalogues, so the access
  debugger logs `MISSING_MESSAGE` during e2e (older than this release).

Still to verify on staging: the items of section 8, and the open items the package reviews
reported (not re-checked here), among them the login, accept-invite and SSO callback pages
whose prerendered HTML holds the loading fallback (S1), the route-gate login loop when the hint
cookie Domain misses the frontend host (B1), the synchronous Redis publish inside `commit()`
with a slow Redis and proxy buffering of the event stream (C3), a browser-to-API Web Vitals run
and the Grafana dashboard render (A2), and per-tab serial refresh against the refresh rate limit
with many tabs (B1).

## 10. Change Notes

- 2026-11-27: Initial version, written after checking the `0.7.0` spec against the code at
  `b72e4a70`.
- 2026-11-27: Anchor fixes: chat scope files and lazy modules owned by one package each,
  `icons:check` placement, icon metadata unchanged, no parity re-record, CSRF note for B1.
- 2026-11-28: Status after all nine packages merged; integration check results, ratchets
  raised, bundle budget overrun on `/documents` recorded.
