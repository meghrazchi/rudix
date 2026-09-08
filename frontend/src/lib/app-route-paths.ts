import { isValidLocale, type SupportedLocale } from "@/i18n/routing";

export const AUTHENTICATED_APP_ROUTE_SEGMENTS = [
  "dashboard",
  "chat",
  "admin",
  "documents",
  "collections",
  "connectors",
  "evaluations",
  "graph",
  "rag-pipeline",
  "reports",
  "settings",
  "user",
  "workspace",
  "api",
] as const;

const AUTHENTICATED_APP_ROUTE_RE = new RegExp(
  `^/(${AUTHENTICATED_APP_ROUTE_SEGMENTS.join("|")})\\b`,
);

export function isAuthenticatedAppPath(pathname: string): boolean {
  return AUTHENTICATED_APP_ROUTE_RE.test(pathname);
}

export function parseLocalePrefixedAppPath(pathname: string): {
  locale: SupportedLocale;
  pathname: string;
} | null {
  const [, localePrefix, ...pathSegments] = pathname.split("/");
  const unprefixedPath = `/${pathSegments.join("/")}`;

  if (!isValidLocale(localePrefix) || !isAuthenticatedAppPath(unprefixedPath)) {
    return null;
  }

  return { locale: localePrefix, pathname: unprefixedPath };
}
