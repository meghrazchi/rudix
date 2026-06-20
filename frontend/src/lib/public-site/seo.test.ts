import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  buildLocalizedPublicMetadata,
  buildPublicMetadata,
} from "@/lib/public-site/seo";
import {
  buildPublicSitemapEntries,
  PUBLIC_SITEMAP_PATHS,
} from "@/lib/public-site/sitemap";
import { SUPPORTED_LOCALES } from "@/i18n/routing";

const originalEnv = { ...process.env };

beforeEach(() => {
  process.env = { ...originalEnv };
  process.env.NEXT_PUBLIC_PUBLIC_SITE_URL = "https://public.example.com";
});

afterEach(() => {
  process.env = { ...originalEnv };
});

describe("public site metadata", () => {
  it("builds locale-aware metadata with canonical, alternates, and social fields", () => {
    const metadata = buildPublicMetadata({
      locale: "de",
      title: "Product | Rudix",
      description: "Product overview",
      path: "/product",
    });

    expect(metadata.title).toBe("Product | Rudix");
    expect(metadata.description).toBe("Product overview");
    expect(metadata.alternates?.canonical).toBe(
      "https://public.example.com/de/product",
    );
    expect(metadata.alternates?.languages).toMatchObject({
      "en-US": "https://public.example.com/en/product",
      "de-DE": "https://public.example.com/de/product",
      "es-ES": "https://public.example.com/es/product",
      "fr-FR": "https://public.example.com/fr/product",
      "x-default": "https://public.example.com/en/product",
    });
    const openGraph = metadata.openGraph as
      | {
          type?: string;
          url?: string;
          locale?: string;
          alternateLocale?: string[];
        }
      | undefined;
    const twitter = metadata.twitter as { card?: string } | undefined;

    expect(openGraph?.type).toBe("website");
    expect(openGraph?.locale).toBe("de_DE");
    expect(openGraph?.alternateLocale).toEqual(
      expect.arrayContaining(["en_US", "es_ES", "fr_FR"]),
    );
    expect(openGraph?.url).toBe("https://public.example.com/de/product");
    expect(twitter?.card).toBe("summary_large_image");
  });

  it("supports no-index pages", () => {
    const metadata = buildPublicMetadata({
      locale: "en",
      title: "Status | Rudix",
      description: "Status page",
      path: "/status",
      noIndex: true,
    });

    const robots = metadata.robots as
      | { index?: boolean; follow?: boolean }
      | undefined;

    expect(robots?.index).toBe(false);
    expect(robots?.follow).toBe(false);
  });

  it("builds localized SEO metadata from message catalogs", () => {
    const metadata = buildLocalizedPublicMetadata({
      locale: "fr",
      seoKey: "securityDisclosure",
      path: "/legal/security-disclosure",
    });

    expect(metadata.title).toBe("Politique de divulgation de sécurité | Rudix");
    expect(metadata.alternates?.canonical).toBe(
      "https://public.example.com/fr/legal/security-disclosure",
    );
  });

  it("builds sitemap entries for every locale and public route", () => {
    const sitemap = buildPublicSitemapEntries("https://public.example.com");

    expect(sitemap).toHaveLength(
      SUPPORTED_LOCALES.length * PUBLIC_SITEMAP_PATHS.length,
    );
    expect(sitemap[0]?.url).toBe("https://public.example.com/en");
    expect(
      sitemap.some(
        (entry) => entry.url === "https://public.example.com/de/pricing",
      ),
    ).toBe(true);
    expect(
      sitemap.some(
        (entry) => entry.url === "https://public.example.com/fr/legal/privacy",
      ),
    ).toBe(true);
  });
});
