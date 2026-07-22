import { isValidLocale, type SupportedLocale } from "@/i18n/routing";

const AUTHENTICATED_APP_ROUTE_RE =
  /^\/(dashboard|chat|admin|documents|collections|connectors|evaluations|graph|rag-pipeline|reports|settings|user|workspace|api)\b/;

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
