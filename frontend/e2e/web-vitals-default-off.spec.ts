import { expect, test } from "@playwright/test";

// R07-11: field measurement is off unless NEXT_PUBLIC_WEB_VITALS_ENABLED is
// "true" at build time, and then still needs analytics consent.

test("sends no Web Vitals request by default", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/telemetry/web-vitals")) {
      requests.push(request.url());
    }
  });

  await page.goto("/en");
  await page.waitForLoadState("networkidle");
  // Hiding the page is what would flush a batch.
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(500);

  expect(requests).toEqual([]);
});
