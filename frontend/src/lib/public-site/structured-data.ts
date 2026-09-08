import { resolvePublicSiteBaseUrl } from "@/lib/public-site/links";
import { PUBLIC_SITE_METADATA_DEFAULTS } from "@/lib/public-site/seo";
import { getHtmlLang } from "@/lib/i18n-format";
import { SUPPORTED_LOCALES } from "@/i18n/routing";

export function buildPublicOrganizationJsonLd(): object {
  const baseUrl = resolvePublicSiteBaseUrl();
  const organizationId = new URL("/#organization", baseUrl).toString();

  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": organizationId,
        name: PUBLIC_SITE_METADATA_DEFAULTS.siteName,
        url: baseUrl,
        logo: new URL("/brand/rudix-mark.svg", baseUrl).toString(),
        description: PUBLIC_SITE_METADATA_DEFAULTS.defaultDescription,
      },
      {
        "@type": "WebSite",
        "@id": new URL("/#website", baseUrl).toString(),
        name: PUBLIC_SITE_METADATA_DEFAULTS.siteName,
        url: baseUrl,
        publisher: { "@id": organizationId },
        inLanguage: SUPPORTED_LOCALES.map(getHtmlLang),
      },
    ],
  };
}
