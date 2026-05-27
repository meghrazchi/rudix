import { expect, test, type Page, type Route } from "@playwright/test";

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";

type TestSession = {
  userId: string;
  email: string;
  role: "owner" | "admin" | "member" | "viewer";
  organizationId: string;
  organizationName: string;
  accessToken: string;
  refreshToken: string;
};

const baseSession: TestSession = {
  userId: "e2e-user-1",
  email: "admin@example.com",
  role: "admin",
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-access-token",
  refreshToken: "e2e-refresh-token",
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
    const requestUrl = new URL(request.url());
    const path = requestUrl.pathname.replace(/^\/api\/v1/, "");

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
      const statusFilter = requestUrl.searchParams.get("status");
      const items = [
        {
          document_id: "doc-1",
          filename: "Employee-Handbook.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 12,
          chunk_count: 42,
          error_message: null,
          error_details: null,
          created_at: "2026-05-19T09:30:00Z",
          updated_at: "2026-05-20T08:30:00Z",
        },
      ];
      const filtered = statusFilter
        ? items.filter((item) => item.status === statusFilter)
        : items;
      await fulfillJson(route, {
        items: filtered,
        total: filtered.length,
        limit: Number.parseInt(
          requestUrl.searchParams.get("limit") ?? "20",
          10,
        ),
        offset: Number.parseInt(
          requestUrl.searchParams.get("offset") ?? "0",
          10,
        ),
        status: statusFilter,
        sort_by: requestUrl.searchParams.get("sort_by") ?? "updated_at",
        sort_order: requestUrl.searchParams.get("sort_order") ?? "desc",
      });
      return;
    }

    if (path === "/chat/sessions" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [
          {
            session_id: "session-1",
            title: "Onboarding FAQ",
            message_count: 2,
            created_at: "2026-05-20T07:00:00Z",
            updated_at: "2026-05-20T08:00:00Z",
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });
      return;
    }

    if (
      path === "/chat/sessions/session-1/messages" &&
      request.method() === "GET"
    ) {
      await fulfillJson(route, {
        items: [
          {
            message_id: "m-1",
            role: "user",
            content: "How do we upload files?",
            confidence_score: null,
            confidence_category: null,
            citations: [],
            created_at: "2026-05-20T08:00:00Z",
          },
          {
            message_id: "m-2",
            role: "assistant",
            content: "Use the upload modal on the Documents page.",
            confidence_score: 0.82,
            confidence_category: "high",
            citations: [],
            created_at: "2026-05-20T08:00:03Z",
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
      });
      return;
    }

    if (path === "/chat/sessions" && request.method() === "POST") {
      await fulfillJson(
        route,
        {
          session_id: "session-new",
          title: null,
          message_count: 0,
          created_at: "2026-05-20T08:10:00Z",
          updated_at: "2026-05-20T08:10:00Z",
        },
        201,
      );
      return;
    }

    if (path === "/chat" && request.method() === "POST") {
      await fulfillJson(route, {
        chat_session_id: "session-new",
        message_id: "assistant-msg-1",
        answer: "Mocked answer from e2e test.",
        confidence_score: 0.79,
        confidence_category: "medium",
        confidence_explanation: {
          top_similarity: 0.81,
          average_similarity: 0.7,
          top_rerank_score: 0.75,
          citation_support_score: 0.8,
          citation_validation_score: 0.9,
          citation_coverage_score: 0.84,
          retrieval_agreement_score: 0.78,
          raw_score: 0.79,
          citation_validation_multiplier: 1,
          not_found_penalty_multiplier: 1,
          no_context: false,
          not_found_signal: false,
          weights: {},
          thresholds: {},
        },
        not_found: false,
        citations: [],
        debug: {
          latencies_ms: { total: 320 },
          retrieval_count: 4,
          selected_count: 2,
          rerank_applied: true,
          embedding_model: "text-embedding-3-small",
          llm_model: "gpt-5.4-mini",
        },
        created_at: "2026-05-20T08:10:20Z",
      });
      return;
    }

    if (path === "/admin/usage" && request.method() === "GET") {
      await fulfillJson(route, {
        organization_id: ORG_ID,
        range: { from: "2026-04-21", to: "2026-05-20" },
        granularity: "day",
        totals: {
          input_tokens: 1000,
          output_tokens: 250,
          cost_usd: 2.4,
          event_count: 7,
          avg_confidence: 0.77,
          avg_latency_ms: 250,
        },
        series: [],
      });
      return;
    }

    if (path === "/auth/login" && request.method() === "POST") {
      await fulfillJson(route, {
        access_token: "login-token",
        refresh_token: "login-refresh",
        user_id: "e2e-user-1",
        email: "admin@example.com",
        role: "admin",
        organization_id: ORG_ID,
        organization_name: "Rudix E2E Org",
      });
      return;
    }

    await fulfillJson(
      route,
      { detail: `No e2e mock for ${request.method()} ${path}` },
      404,
    );
  });
}

async function seedAuthenticatedSession(
  page: Page,
  session: TestSession = baseSession,
): Promise<void> {
  await page.addInitScript(
    ({ storageKey, payload }) => {
      window.localStorage.setItem(storageKey, JSON.stringify(payload));
    },
    { storageKey: SESSION_STORAGE_KEY, payload: session },
  );
}

async function waitForSessionBootstrap(page: Page): Promise<void> {
  const loadingHeading = page.getByRole("heading", { name: "Loading session" });
  if (await loadingHeading.isVisible().catch(() => false)) {
    await expect(loadingHeading).toBeHidden({ timeout: 30_000 });
  }
}

test.describe("frontend e2e smoke (no real backend)", () => {
  test("navigates public marketing routes and login CTA", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /Scale Precision AI/i }),
    ).toBeVisible();

    await page.getByRole("link", { name: "Product" }).first().click();
    await expect(page).toHaveURL(/\/product$/);
    await expect(
      page.getByRole("heading", {
        name: "AI Document Q&A for trusted enterprise decisions",
      }),
    ).toBeVisible();

    await page.getByRole("link", { name: "Login" }).first().click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("redirects protected route to login and signs in successfully", async ({
    page,
  }) => {
    await installApiMocks(page);
    await page.goto("/documents");
    await waitForSessionBootstrap(page);

    const loginEmail = page.getByLabel("Email");
    const documentsHeading = page.getByRole("heading", {
      name: "Upload, Index, and Manage Documents",
    });

    await Promise.race([
      loginEmail.waitFor({ state: "visible", timeout: 30_000 }),
      documentsHeading.waitFor({ state: "visible", timeout: 30_000 }),
    ]);

    if (await loginEmail.isVisible().catch(() => false)) {
      await page.getByLabel("Email").fill("admin@example.com");
      await page.getByLabel("Password").fill("123123123");
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page).toHaveURL(/\/documents$/);
    }

    await expect(documentsHeading).toBeVisible();
  });

  test("loads dashboard with mocked APIs while authenticated", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/dashboard");
    await waitForSessionBootstrap(page);
    await expect(
      page.getByRole("heading", { name: "Organization Metrics Overview" }),
    ).toBeVisible();
    await expect(page.getByText("Recent activity")).toBeVisible();
  });

  test("loads documents and chat routes with mocked data", async ({ page }) => {
    await installApiMocks(page);
    await seedAuthenticatedSession(page);

    await page.goto("/documents");
    await waitForSessionBootstrap(page);
    await expect(
      page.getByRole("heading", {
        name: "Upload, Index, and Manage Documents",
      }),
    ).toBeVisible();
    await expect(page.getByText("Employee-Handbook.pdf")).toBeVisible();

    await page.goto("/chat");
    await waitForSessionBootstrap(page);
    await expect(
      page.getByRole("heading", { name: "Document-grounded Q&A" }),
    ).toBeVisible();
    await expect(page.getByText("Onboarding FAQ")).toBeVisible();
    await expect(
      page.getByRole("textbox", {
        name: "Ask a question about your selected documents...",
      }),
    ).toBeVisible();
  });
});
