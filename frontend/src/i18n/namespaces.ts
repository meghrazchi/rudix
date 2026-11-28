import enMessages from "./messages/en.json";

/** A top-level key of the message catalogue (`src/i18n/messages/en.json`). */
export type MessageNamespace = keyof typeof enMessages;

/** Every top-level namespace, in catalogue order. */
export const ALL_NAMESPACES = Object.keys(enMessages) as MessageNamespace[];

/**
 * Namespaces shipped to the browser by `app/[locale]/layout.tsx` (R07-02):
 * every namespace read with `useTranslations`/`getTranslations` by a file
 * reachable from a page under `app/[locale]` or from `RootDocument`
 * (public site, consent banner, language switcher, login, NotFoundPage).
 *
 * A package that adds a top-level namespace adds it to this list, to
 * APP_NAMESPACES, or to both, in the same commit; `namespaces.test.ts` fails
 * otherwise. A missing entry here shows up as MISSING_MESSAGE in
 * `public-namespaces.test.tsx` and `e2e/public-static-parity.spec.ts`.
 */
export const PUBLIC_NAMESPACES = [
  "auth",
  "cookieConsent",
  "errors",
  "languageSwitcher",
  "public",
  "states",
] as const satisfies readonly MessageNamespace[];

/**
 * Namespaces of the signed-out account pages (0.9.0): email verification,
 * password reset (`authAccount`, A1), and the MFA challenge step (`authMfa`,
 * A2). They are shipped by A1's account layout next to PUBLIC_NAMESPACES,
 * never by the marketing pages, so the public payload does not grow. The
 * signed-in app ships them too (APP_NAMESPACES), for MFA enrolment in
 * settings.
 */
export const ACCOUNT_NAMESPACES = [
  "authAccount",
  "authMfa",
] as const satisfies readonly MessageNamespace[];

/**
 * Namespaces shipped by `app/(app)/layout.tsx`: the whole catalogue. The
 * signed-in app reads every namespace, and `app/(app)/not-found.tsx`
 * renders NotFoundPage inside the public layout, so `public` stays as well.
 */
export const APP_NAMESPACES = [
  "notificationCenter",
  "common",
  "navigation",
  "auth",
  "authAccount",
  "authMfa",
  "validation",
  "public",
  "dashboard",
  "documents",
  "chat",
  "evaluations",
  "collections",
  "connectors",
  "pipeline",
  "settings",
  "onboardingChecklist",
  "workspaceSwitcher",
  "appShell",
  "errors",
  "toasts",
  "languageSwitcher",
  "states",
  "adminTeam",
  "help",
  "cookieConsent",
  "adminLanding",
  "adminUsage",
  "adminObservability",
  "adminAuditLogs",
  "adminSecurityCenter",
  "adminGovernance",
  "adminModelProvider",
  "adminModelDiagnostics",
  "adminSafetyEvals",
  "adminApiKeys",
  "agentWorkspace",
  "graphExplorer",
  "adminRoles",
  "adminPermissions",
  "adminAccessDebugger",
  "adminSso",
  "adminScim",
  "adminSystemHealth",
  "adminFeedbackReview",
  "adminDocumentDeletion",
  "adminFeatureFlags",
  "adminFailedJobs",
  "adminSourceHealth",
  "adminPermissionsAccess",
  "adminUsageAdoption",
  "adminStatus",
  "adminQuotas",
  "adminPortability",
  "reports",
  "adminVectorIndex",
  "adminBots",
  "adminEmail",
] as const satisfies readonly MessageNamespace[];
