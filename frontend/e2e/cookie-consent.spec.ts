import { expect, test } from "@playwright/test";

import { CONSENT_STORAGE_KEY } from "./support/consent";

// The suite default (playwright.config.ts) is a returning visitor who has
// already answered the banner. These tests cover the first visit.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("cookie consent banner (first visit)", () => {
  test("shows on first visit, records the choice and stays dismissed", async ({
    page,
  }) => {
    await page.goto("/en/login");

    const banner = page.getByRole("dialog", { name: "Cookie consent" });
    await expect(banner).toBeVisible();

    await banner.getByRole("button", { name: "Reject non-essential" }).click();
    await expect(banner).toBeHidden();

    const stored = await page.evaluate(
      (key) => window.localStorage.getItem(key),
      CONSENT_STORAGE_KEY,
    );
    expect(JSON.parse(stored ?? "null")).toMatchObject({
      decisions: { functional: false, analytics: false },
    });

    await page.reload();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(
      page.getByRole("dialog", { name: "Cookie consent" }),
    ).toHaveCount(0);
  });
});
