# v0.7.0 — Frontend Performance

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../09_FRONTEND_UI_DESIGN.md](../09_FRONTEND_UI_DESIGN.md)

## 1. Purpose

Make public pages static and fast, cut the JavaScript and message payload shipped to every
page, replace hand-written API types and polling, and bring the remaining large components
under the size guideline.

Chat-specific frontend work is in [V0_5_0](./V0_5_0_CHAT_PIPELINE_AND_STREAMING.md).
Check the Next.js documentation bundled in `frontend/node_modules/next/dist/docs` before
using an API; `frontend/AGENTS.md` warns that this version differs from older conventions.

## 2. Proposed budgets

Targets to confirm against the first bundle report (`R07-03`):

| Metric | Target |
|---|---|
| Marketing pages LCP, p75 mobile | 2.5 s or less |
| Marketing pages first-load JavaScript | 150 KB gzip or less |
| App shell first-load JavaScript | 300 KB gzip or less |
| Messages sent per page | Only the namespaces the route uses |
| INP on chat and documents, p75 | 200 ms or less |

## 3. Work items

### R07-01 — Static marketing pages (M)

- **Problem:** The root layout reads the locale from cookies, so no public page is
  prerendered.
- **Change:** Resolve the locale from the `[locale]` path segment for public routes. Call
  `setRequestLocale` in each public layout and page and add `generateStaticParams` for the
  six locales. Keep cookie-based locale for the authenticated `(app)` group only.
- **Done when:** The prerender manifest lists every public route for every locale, and
  canonical and hreflang output is unchanged.

### R07-02 — Split the message catalogue (M)

- **Problem:** Each page receives a 340 to 470 KB catalogue (5,961 keys), passed to the
  client provider twice.
- **Change:** Split message files by namespace. Each layout passes only the namespaces its
  subtree needs (`pick`). Remove the duplicate provider. Keep the key-parity test working
  across split files.
- **Done when:** A public page ships only public namespaces, and the parity test passes.

### R07-03 — Code splitting and bundle budgets (M)

- **Change:**
  - Load with `next/dynamic`: `recharts` charts, `@xyflow/react`, the trust panel, modals,
    the document preview, and admin-only panels.
  - Enable `optimizePackageImports` for icon and utility packages.
  - Add a bundle report to CI and fail when a route exceeds its budget (the analyzer is a
    dev dependency and needs approval; fallback is parsing the Next.js build output).
  - Remove unused dependencies: `zustand`, `motion`, `@tanstack/react-table`,
    `class-variance-authority`. Align `eslint-config-next` with the `next` version. Delete
    `public/next.svg` and `public/vercel.svg`.
- **Done when:** Budgets in section 2 are enforced in CI.

### R07-04 — Icons, fonts, and images (S)

- **Change:** Remove the render-blocking Google Fonts Material Symbols stylesheet. Use one
  icon source: either `lucide-react` everywhere or a self-hosted subset of the symbols
  actually used. Optimise `public/brand/rudix-mark.svg` (303 KB) and provide a small favicon.
  Configure `images` formats in `next.config.ts`.
- **Done when:** No third-party font request remains, and the CSP from `R02-09` drops the
  Google Fonts allowance.

### R07-05 — Generated API client everywhere (L)

- **Problem:** 72 of 76 client modules use about 697 hand-written types.
- **Change:** With the full OpenAPI export from `R03-10`, migrate client modules to the
  generated types, one domain per merge request, highest traffic first. Delete the
  hand-written type when its module is migrated. Backend response models that return untyped
  dictionaries get Pydantic schemas first.
- **Done when:** No client module declares a response type by hand, and a backend contract
  change fails the frontend type check.

### R07-06 — Real pagination in lists (M)

- **Problem:** About 15 lists hard-code `limit: 200` and silently drop the rest.
- **Change:** Use `useInfiniteQuery` with the cursor contract from `R04-04`. Virtualise
  tables that can exceed a few hundred rows. Selectors that need "all" items use
  server-side search instead of loading everything.
- **Done when:** No list silently truncates; each shows a count or a "load more" affordance.

### R07-07 — Push instead of polling (L)

- **Problem:** 28 polling intervals across 15 files. The documents page polls a list plus
  five status requests every 4 seconds, including in background tabs.
- **Change:**
  - Backend: one authenticated event stream per user (SSE, or the existing WebSocket),
    backed by Redis pub/sub, carrying `document.status`, `notification.created`,
    `connector.sync`, `agent.run`, and `incident` events. Organisation-scoped; events carry
    IDs, not document content.
  - Frontend: a single `useRealtime()` subscription in the app shell that invalidates the
    matching TanStack Query keys.
  - Keep polling as a fallback at a longer interval, and stop it when the tab is hidden.
- **Done when:** The documents page makes no periodic requests while the stream is
  connected, and status changes appear within two seconds.

### R07-08 — Route-level boundaries (S)

- **Change:** Add `global-error.tsx`, and `error.tsx` and `loading.tsx` for the main route
  segments (chat, documents, collections, admin, settings, reports). Translate the error
  page. Use `SkeletonBlock` (F178) for loading states.
- **Done when:** A thrown error in an admin page leaves the shell and navigation usable.

### R07-09 — Token storage and server-side route gate (M)

- **Problem:** The access token is persisted in `localStorage`. Route protection is entirely
  client-side, so every protected page first paints a "loading session" gate.
- **Change:** Keep the access token in memory only and restore it on load through the
  existing refresh-cookie flow. In `src/proxy.ts`, redirect requests for `(app)` routes that
  carry no refresh cookie to the login page. The backend stays the authority for
  authorization.
- **Done when:** No token is written to `localStorage`, and a signed-out request for an app
  route redirects without rendering the shell.

### R07-10 — Shrink the remaining large components (L, incremental)

- **Change:** Split the 28 files over 1,000 lines, starting with `DocumentDetailPage.tsx`,
  `DocumentsPage.tsx`, `CollectionsPage.tsx`, `ConnectorSetupPage.tsx`, and
  `AdminPermissionsPage.tsx`. Extract data hooks, table, filters, and dialogs. Replace the
  87 ad-hoc query keys with the `queryKeys` factory while touching each file.
- **Done when:** No component file exceeds 500 lines, with existing tests passing unchanged.

### R07-11 — Field measurement (M, partly needs approval)

- **Change:** Report Core Web Vitals with `useReportWebVitals` to the consent-gated analytics
  endpoint. Replace the hand-rolled Sentry client, which uses a legacy endpoint, with the
  official SDK and source-map upload (needs approval; fallback is to move the existing client
  to the current envelope endpoint).
- **Done when:** LCP, INP, and CLS are visible per route in a dashboard.

### R07-12 — Translation and accessibility coverage (M)

- **Change:** Translate the 100 component files that do not use `useTranslations`, starting
  with the trust panel, share and feedback modals, shared answer page, and evaluations.
  Add an ESLint rule against literal UI strings. Add automated accessibility checks to the
  Playwright suite (dev dependency, needs approval) and run it on Firefox and WebKit too.
- **Done when:** No hard-coded user-facing strings remain in components, and the
  accessibility check passes on the main routes.

## 4. Exit criteria

- Budgets in section 2 hold in CI and in field data from staging.
- Public routes are prerendered for all six locales.
- The documents and notifications views do not poll while connected.

## 5. Failure Modes and Recovery

| Failure | Recovery |
|---|---|
| Event stream disconnects | Fallback polling resumes; reconnect with backoff |
| A missing namespace breaks a page | The parity test and a per-route render test catch it in CI |
| Static generation serves a stale locale page | Revalidate on deploy; pages contain no user data |

## 6. Security Considerations

`R07-09` reduces token exposure to cross-site scripting. The event stream in `R07-07` must
authenticate with the ticket mechanism from `R02-10`, enforce organisation scope on the
server, and never carry document text. Public pages must remain crawlable; confirm no
unintended `noindex` after `R07-01`.

## 7. Observability and Operations

Web Vitals per route, bundle size per route over time, event-stream connection count and
reconnect rate.

## 8. Change Notes

- 2026-11-26: Initial version.
