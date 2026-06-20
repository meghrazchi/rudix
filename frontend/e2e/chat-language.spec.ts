import { expect, test, type Page, type Route } from "@playwright/test";

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";

const memberSession = {
  userId: "e2e-user-lang",
  email: "member@example.com",
  role: "member" as const,
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-access-token-lang",
  refreshToken: "e2e-refresh-token-lang",
};

async function fulfillJson(
  route: Route,
  body: unknown,
  status = 200,
): Promise<void> {
  await route.fulfill({
    status,
    headers: {
      "content-type": "application/json",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "*",
      "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    },
    body: JSON.stringify(body),
  });
}

async function installApiMocks(page: Page): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");

    if (request.method() === "OPTIONS") {
      await route.fulfill({
        status: 200,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-headers": "*",
          "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        },
      });
      return;
    }

    if (path === "/documents" && request.method() === "GET") {
      await fulfillJson(route, { items: [], total: 0, limit: 20, offset: 0 });
      return;
    }

    if (path === "/collections" && request.method() === "GET") {
      await fulfillJson(route, { items: [], total: 0, limit: 20, offset: 0 });
      return;
    }

    if (path === "/chat/sessions" && request.method() === "GET") {
      await fulfillJson(route, { items: [], total: 0, limit: 10, offset: 0 });
      return;
    }

    if (path === "/chat/sessions" && request.method() === "POST") {
      await fulfillJson(route, {
        session_id: "session-lang-test",
        title: "Test",
        message_count: 0,
        created_at: "2026-06-04T00:00:00Z",
        updated_at: "2026-06-04T00:00:00Z",
      });
      return;
    }

    if (path === "/chat" && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}");
      const languageUsed = body.answer_language ?? null;
      await fulfillJson(route, {
        chat_session_id: "session-lang-test",
        message_id: "msg-lang-test",
        answer: `Answer (language: ${languageUsed ?? "auto"})`,
        confidence_score: 0.8,
        confidence_category: "high",
        confidence_explanation: {
          top_similarity: 0.8,
          average_similarity: 0.7,
          top_rerank_score: 0.0,
          citation_support_score: 0.5,
          citation_validation_score: 1.0,
          citation_coverage_score: 0.5,
          retrieval_agreement_score: 0.8,
          raw_score: 0.8,
          citation_validation_multiplier: 1.0,
          not_found_penalty_multiplier: 1.0,
          no_context: false,
          not_found_signal: false,
          weights: {},
          thresholds: {},
        },
        not_found: false,
        citations: [],
        citation_validation_failed: false,
        debug: {
          latencies_ms: { total: 200 },
          retrieval_count: 0,
          selected_count: 0,
          rerank_applied: false,
          detected_language: "en",
          answer_language_used: languageUsed,
        },
        created_at: "2026-06-04T00:00:00Z",
      });
      return;
    }

    await route.fallback();
  });
}

async function loginAs(
  page: Page,
  session: typeof memberSession,
): Promise<void> {
  await page.evaluate(
    ({ key, value }) => {
      window.localStorage.setItem(key, JSON.stringify(value));
    },
    { key: SESSION_STORAGE_KEY, value: session },
  );
}

test.describe("Chat language selector (F231)", () => {
  test.beforeEach(async ({ page }) => {
    await installApiMocks(page);
    await page.goto("/chat");
    await loginAs(page, memberSession);
    await page.goto("/chat");
  });

  test("answer language selector is visible in the composer toolbar", async ({
    page,
  }) => {
    await expect(page.getByLabel("Answer language")).toBeVisible();
  });

  test("answer language selector has Auto option selected by default", async ({
    page,
  }) => {
    const selector = page.getByLabel("Answer language");
    await expect(selector).toHaveValue("auto");
  });

  test("answer language options include all four languages", async ({
    page,
  }) => {
    const selector = page.getByLabel("Answer language");
    const options = await selector.locator("option").allTextContents();
    expect(options).toContain("English");
    expect(options).toContain("German");
    expect(options).toContain("Spanish");
    expect(options).toContain("French");
  });

  test("selecting German and submitting sends answer_language=de", async ({
    page,
  }) => {
    await page.getByLabel("Answer language").selectOption("de");

    const chatRequests: string[] = [];
    await page.route("**/api/v1/chat", async (route) => {
      const body = route.request().postData() ?? "{}";
      chatRequests.push(body);
      await route.fallback();
    });

    await page
      .getByPlaceholder(/Type a message/i)
      .fill("Wie viele Urlaubstage?");
    await page.getByRole("button", { name: /Send message/i }).click();

    await page.waitForTimeout(500);

    expect(chatRequests.length).toBeGreaterThan(0);
    const lastRequest = JSON.parse(chatRequests.at(-1) ?? "{}");
    expect(lastRequest.answer_language).toBe("de");
  });

  test("auto mode does not send answer_language in the request", async ({
    page,
  }) => {
    const chatRequests: string[] = [];
    await page.route("**/api/v1/chat", async (route) => {
      chatRequests.push(route.request().postData() ?? "{}");
      await route.fallback();
    });

    await page.getByPlaceholder(/Type a message/i).fill("What is leave?");
    await page.getByRole("button", { name: /Send message/i }).click();

    await page.waitForTimeout(500);

    if (chatRequests.length > 0) {
      const lastRequest = JSON.parse(chatRequests.at(-1) ?? "{}");
      expect(lastRequest.answer_language).toBeUndefined();
    }
  });
});
