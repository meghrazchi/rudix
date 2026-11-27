import { expect, type Page } from "@playwright/test";

/**
 * Dismiss the floating "Getting started" checklist (F327) the way a user
 * does. The expanded checklist is fixed to the bottom-right corner and
 * covers controls there at desktop size (for example the chat composer's
 * Advanced settings button), so specs that are not about onboarding dismiss
 * it before interacting with those controls.
 */
export async function dismissOnboardingChecklist(page: Page): Promise<void> {
  await page
    .getByRole("button", { name: /Dismiss getting started checklist/ })
    .click();
  await expect(
    page.getByRole("region", { name: "Getting started checklist" }),
  ).toHaveCount(0);
}
