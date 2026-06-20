import type { MetadataRoute } from "next";

import { PUBLIC_ROUTE_PATHS } from "@/lib/public-site/links";
import { SUPPORTED_LOCALES, type SupportedLocale } from "@/i18n/routing";
import { SOLUTION_AUDIENCES } from "@/lib/public-site/solutions";
import { buildLocalizedPublicPath } from "@/lib/public-site/seo";

export const PUBLIC_SITEMAP_PATHS = [
  PUBLIC_ROUTE_PATHS.home,
  PUBLIC_ROUTE_PATHS.product,
  PUBLIC_ROUTE_PATHS.solutions,
  PUBLIC_ROUTE_PATHS.security,
  PUBLIC_ROUTE_PATHS.pricing,
  PUBLIC_ROUTE_PATHS.contact,
  PUBLIC_ROUTE_PATHS.changelog,
  PUBLIC_ROUTE_PATHS.status,
  PUBLIC_ROUTE_PATHS.privacy,
  PUBLIC_ROUTE_PATHS.terms,
  PUBLIC_ROUTE_PATHS.cookies,
  PUBLIC_ROUTE_PATHS.dpa,
  PUBLIC_ROUTE_PATHS.subprocessors,
  PUBLIC_ROUTE_PATHS.acceptableUse,
  PUBLIC_ROUTE_PATHS.securityDisclosure,
  ...SOLUTION_AUDIENCES.map((solution) => solution.routePath),
] as const;

function getPriority(path: string): number {
  if (path === PUBLIC_ROUTE_PATHS.home) return 1;
  if (
    path === PUBLIC_ROUTE_PATHS.product ||
    path === PUBLIC_ROUTE_PATHS.solutions ||
    path === PUBLIC_ROUTE_PATHS.security ||
    path === PUBLIC_ROUTE_PATHS.pricing ||
    path === PUBLIC_ROUTE_PATHS.contact
  ) {
    return 0.9;
  }
  if (
    path === PUBLIC_ROUTE_PATHS.status ||
    path === PUBLIC_ROUTE_PATHS.changelog
  ) {
    return 0.7;
  }
  if (path.startsWith("/solutions/")) {
    return 0.8;
  }
  return 0.6;
}

function getChangeFrequency(
  path: string,
): MetadataRoute.Sitemap[number]["changeFrequency"] {
  if (path === PUBLIC_ROUTE_PATHS.status) {
    return "daily";
  }
  if (path === PUBLIC_ROUTE_PATHS.changelog) {
    return "weekly";
  }
  if (path.startsWith("/legal/")) {
    return "monthly";
  }
  return "weekly";
}

function buildLocalizedPublicUrl(
  baseUrl: string,
  locale: SupportedLocale,
  path: string,
): string {
  return new URL(buildLocalizedPublicPath(locale, path), baseUrl).toString();
}

export function buildPublicSitemapEntries(
  baseUrl: string,
  lastModified: Date = new Date(),
): MetadataRoute.Sitemap {
  return SUPPORTED_LOCALES.flatMap((locale) =>
    PUBLIC_SITEMAP_PATHS.map((path) => ({
      url: buildLocalizedPublicUrl(baseUrl, locale, path),
      lastModified,
      changeFrequency: getChangeFrequency(path),
      priority: getPriority(path),
    })),
  );
}
