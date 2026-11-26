import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Critical path against the real integration stack with the LLM stub (R03-04):
// log in -> upload -> indexed -> ask in chat -> grounded answer with citation.
// Needs RUDIX_E2E_INTEGRATION=1, RUDIX_E2E_EMAIL and RUDIX_E2E_PASSWORD.

const FIXTURE_FILENAME = "rudix-e2e.txt";
const FIXTURE_PATH = path.join(__dirname, "fixtures", FIXTURE_FILENAME);
const FACT_CODE = "AURORA-7319";
const QUESTION = "What is the Rudix integration verification code?";
const INGEST_TIMEOUT_MS = 120_000;
const TERMINAL_FAILURE = /\b(failed|quarantined|blocked)\b/i;

type RequestIdRecord = { status: number; path: string; requestId: string };

function trackFailedApiRequestIds(page: Page): RequestIdRecord[] {
  const records: RequestIdRecord[] = [];
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (!url.pathname.includes("/api/v1/") || response.status() < 400) {
      return;
    }
    const requestId = response.headers()["x-request-id"];
    if (requestId) {
      // Path and request ID only: never bodies, tokens or query strings.
      records.push({
        status: response.status(),
        path: url.pathname,
        requestId,
      });
    }
  });
  return records;
}

async function waitForIndexed(page: Page): Promise<void> {
  const row = page
    .getByRole("row")
    .filter({ hasText: FIXTURE_FILENAME })
    .first();
  const deadline = Date.now() + INGEST_TIMEOUT_MS;
  let lastText = "";
  while (Date.now() < deadline) {
    if (await row.isVisible().catch(() => false)) {
      lastText = ((await row.textContent()) ?? "").replace(/\s+/g, " ");
      if (TERMINAL_FAILURE.test(lastText)) {
        throw new Error(
          `Document reached a terminal failure status: ${lastText}`,
        );
      }
      if (/\bindexed\b/i.test(lastText)) {
        return;
      }
    }
    await page.waitForTimeout(3_000);
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Upload Documents" }),
    ).toBeVisible();
  }
  throw new Error(
    `Document was not indexed within ${INGEST_TIMEOUT_MS} ms (last row: ${lastText || "not shown"})`,
  );
}

test.describe("integration critical path", () => {
  test.skip(
    process.env.RUDIX_E2E_INTEGRATION !== "1",
    "Set RUDIX_E2E_INTEGRATION=1 to run against the integration stack.",
  );

  let requestIds: RequestIdRecord[] = [];

  test.beforeEach(({ page }) => {
    requestIds = trackFailedApiRequestIds(page);
  });

  test.afterEach(async ({ page }, testInfo) => {
    if (testInfo.status === testInfo.expectedStatus) {
      return;
    }
    const shownIds = await page
      .getByText(/Request ID/i)
      .allTextContents()
      .catch(() => [] as string[]);
    await testInfo.attach("request-ids.json", {
      contentType: "application/json",
      body: JSON.stringify({ api: requestIds, shown: shownIds }, null, 2),
    });
  });

  test("upload, index, and get a cited answer", async ({ page }) => {
    const email = process.env.RUDIX_E2E_EMAIL ?? "";
    const password = process.env.RUDIX_E2E_PASSWORD ?? "";
    expect(email, "RUDIX_E2E_EMAIL must be set").not.toBe("");
    expect(password, "RUDIX_E2E_PASSWORD must be set").not.toBe("");

    await test.step("log in", async () => {
      await page.goto("/login");
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(password);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
      await expect(page).not.toHaveURL(/\/login/, { timeout: 30_000 });
    });

    await test.step("upload the fixture", async () => {
      await page.goto("/documents");
      await expect(
        page.getByRole("heading", { name: "Upload Documents" }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: /Upload document(s)?/i })
        .first()
        .click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();

      // A per-run line keeps the checksum unique, so reruns on a reused stack
      // are not rejected as duplicates.
      const content = `${readFileSync(FIXTURE_PATH, "utf8")}\nRun reference: ${Date.now().toString(36)}\n`;
      const uploadResponse = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname.endsWith("/documents/upload"),
      );
      await dialog.locator('input[type="file"]').setInputFiles({
        name: FIXTURE_FILENAME,
        mimeType: "text/plain",
        buffer: Buffer.from(content, "utf8"),
      });
      expect((await uploadResponse).status()).toBeLessThan(300);
      await dialog.getByRole("button", { name: "Close upload center" }).click();
    });

    await test.step("wait until indexed", async () => {
      await waitForIndexed(page);
    });

    await test.step("ask in chat", async () => {
      await page.goto("/chat");
      const composer = page.getByPlaceholder(
        "Type a message or use '/' for commands...",
      );
      await expect(composer).toBeEnabled({ timeout: 30_000 });
      await composer.fill(QUESTION);
      await composer.press("ControlOrMeta+Enter");

      const answer = page.locator("p", { hasText: FACT_CODE }).first();
      await expect(answer).toBeVisible({ timeout: 60_000 });
      const citation = answer
        .locator("xpath=following-sibling::div[1]")
        .getByRole("button", { name: /rudix-e2e\.txt/i })
        .first();
      await expect(citation).toBeVisible();
    });
  });
});
