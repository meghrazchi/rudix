import { expect, test } from "@playwright/test";

import { SUPPORTED_LOCALES } from "../src/i18n/routing";
import { PUBLIC_SITEMAP_PATHS } from "../src/lib/public-site/sitemap";
import { buildLocalizedPublicPath } from "../src/lib/public-site/seo";
import { isExternalHref } from "../src/lib/public-site/links";

test.describe("public sitemap URLs resolve for every locale", () => {
  for (const locale of SUPPORTED_LOCALES) {
    for (const path of PUBLIC_SITEMAP_PATHS) {
      const localizedPath = buildLocalizedPublicPath(locale, path);

      test(`${locale} ${path} returns 200`, async ({ request }) => {
        const response = await request.get(localizedPath);
        expect(response.status(), localizedPath).toBe(200);
      });
    }
  }
});

test.describe("primary nav and footer links resolve", () => {
  for (const locale of SUPPORTED_LOCALES) {
    test(`${locale} home page nav/footer has no broken internal links`, async ({
      page,
      request,
    }) => {
      const response = await page.goto(`/${locale}`);
      expect(response?.status()).toBe(200);

      const header = page.getByRole("navigation");
      const footer = page.getByRole("contentinfo");
      const hrefs = new Set<string>();

      for (const locator of [header, footer]) {
        const links = await locator.getByRole("link").all();
        for (const link of links) {
          const href = await link.getAttribute("href");
          if (href && !isExternalHref(href)) {
            hrefs.add(href);
          }
        }
      }

      expect(hrefs.size).toBeGreaterThan(0);

      for (const href of hrefs) {
        const linkResponse = await request.get(href);
        expect(linkResponse.status(), href).toBeLessThan(400);
      }
    });
  }
});
