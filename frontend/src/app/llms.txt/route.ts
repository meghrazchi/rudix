import { resolvePublicSiteBaseUrl } from "@/lib/public-site/links";
import { PUBLIC_SITEMAP_PATHS } from "@/lib/public-site/sitemap";
import {
  buildLocalizedPublicPath,
  PUBLIC_SITE_METADATA_DEFAULTS,
} from "@/lib/public-site/seo";
import { DEFAULT_LOCALE } from "@/i18n/routing";

export function GET(): Response {
  const baseUrl = resolvePublicSiteBaseUrl();
  const sitemapUrl = new URL("/sitemap.xml", baseUrl).toString();

  const pageLines = PUBLIC_SITEMAP_PATHS.map((path) => {
    const url = new URL(
      buildLocalizedPublicPath(DEFAULT_LOCALE, path),
      baseUrl,
    ).toString();
    return `- [${url}](${url})`;
  }).join("\n");

  const body = `# ${PUBLIC_SITE_METADATA_DEFAULTS.siteName}

> ${PUBLIC_SITE_METADATA_DEFAULTS.defaultDescription}

This site is available in English, German, Spanish, French, Persian, and
Arabic. Localized versions of every page below are reachable by replacing the
locale segment (e.g. \`/en/...\` -> \`/de/...\`) or via ${sitemapUrl}, which
lists every localized URL with hreflang alternates.

## Pages

${pageLines}
`;

  return new Response(body, {
    headers: {
      "content-type": "text/markdown; charset=utf-8",
      "cache-control": "public, max-age=3600, s-maxage=86400",
    },
  });
}
