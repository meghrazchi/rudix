import { expect, test, type Page, type Route } from "@playwright/test";

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";

const baseSession = {
  userId: "e2e-user-states",
  email: "admin@example.com",
  role: "admin" as const,
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

async function seedAuthenticatedSession(page: Page): Promise<void> {
  await page.addInitScript(
    ({ storageKey, payload }) => {
      window.localStorage.setItem(storageKey, JSON.stringify(payload));
    },
    { storageKey: SESSION_STORAGE_KEY, payload: baseSession },
  );
}

async function waitForSessionBootstrap(page: Page): Promise<void> {
  const loadingHeading = page.getByRole("heading", { name: "Loading session" });
  if (await loadingHeading.isVisible().catch(() => false)) {
    await expect(loadingHeading).toBeHidden({ timeout: 30_000 });
  }
}

async function installCommonMocks(page: Page): Promise<void> {
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

    if (path === "/notifications/unread-count" && request.method() === "GET") {
      await fulfillJson(route, { unread_count: 0 });
      return;
    }

    if (path === "/notifications" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
        unread_count: 0,
      });
      return;
    }

    if (path === "/auth/effective-permissions" && request.method() === "GET") {
      await fulfillJson(route, { permissions: [] });
      return;
    }

    await fulfillJson(
      route,
      { detail: `No e2e mock for ${request.method()} ${path}` },
      404,
    );
  });
}

test.describe("Empty and error state polish (F178)", () => {
  test("documents page shows empty state with upload CTA when no documents exist", async ({
    page,
  }) => {
    await installCommonMocks(page);
    await seedAuthenticatedSession(page);

    // Override documents endpoint to return empty list
    await page.route("**/api/v1/documents**", async (route) => {
      const request = route.request();
      if (request.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods":
              "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
        sort_by: "created_at",
        sort_order: "desc",
      });
    });

    await page.route("**/api/v1/collections**", async (route) => {
      await fulfillJson(route, { items: [], total: 0 });
    });

    await page.goto("/documents");
    await waitForSessionBootstrap(page);

    // Empty state should be visible with a title
    await expect(
      page.getByText(/No documents found/i),
    ).toBeVisible({ timeout: 15_000 });

    // CTA button should be present for upload
    const uploadButton = page.getByRole("button", { name: /Upload Document/i });
    await expect(uploadButton).toBeVisible();
  });

  test("dashboard shows empty state when workspace has no documents and no chat", async ({
    page,
  }) => {
    await installCommonMocks(page);
    await seedAuthenticatedSession(page);

    await page.route("**/api/v1/documents**", async (route) => {
      const request = route.request();
      if (request.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods":
              "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 200,
        offset: 0,
        sort_by: "updated_at",
        sort_order: "desc",
      });
    });

    await page.route("**/api/v1/chat/**", async (route) => {
      const request = route.request();
      if (request.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods":
              "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }
      const url = new URL(request.url());
      const path = url.pathname.replace(/^\/api\/v1/, "");
      if (path === "/chat/stats") {
        await fulfillJson(route, {
          total_sessions: 0,
          questions_asked: 0,
        });
        return;
      }
      if (path === "/chat/sessions") {
        await fulfillJson(route, {
          items: [],
          total: 0,
          limit: 50,
          offset: 0,
        });
        return;
      }
      await fulfillJson(route, { detail: "not found" }, 404);
    });

    await page.route("**/api/v1/admin/**", async (route) => {
      await fulfillJson(route, { detail: "not found" }, 404);
    });

    await page.goto("/dashboard");
    await waitForSessionBootstrap(page);

    // Dashboard should render without crashing
    await expect(
      page.getByRole("heading", { name: /Command Center/i }),
    ).toBeVisible({ timeout: 15_000 });

    // Empty workspace state should appear when both counts are 0
    await expect(
      page.getByText(/Get started/i).or(page.getByText(/Upload/i)).first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("documents page shows error state with retry on API failure", async ({
    page,
  }) => {
    await installCommonMocks(page);
    await seedAuthenticatedSession(page);

    await page.route("**/api/v1/documents**", async (route) => {
      const request = route.request();
      if (request.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods":
              "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }
      await fulfillJson(
        route,
        { detail: "Internal server error", request_id: "req-e2e-500" },
        500,
      );
    });

    await page.goto("/documents");
    await waitForSessionBootstrap(page);

    // ErrorState should appear — look for the role=alert region
    const alert = page.getByRole("alert");
    await expect(alert.first()).toBeVisible({ timeout: 15_000 });

    // Retry button should be present
    await expect(page.getByRole("button", { name: /retry/i }).first()).toBeVisible();
  });

  test("error state for 403 on documents shows forbidden state", async ({
    page,
  }) => {
    await installCommonMocks(page);
    await seedAuthenticatedSession(page);

    await page.route("**/api/v1/documents**", async (route) => {
      const request = route.request();
      if (request.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods":
              "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }
      await fulfillJson(route, { detail: "Forbidden" }, 403);
    });

    await page.goto("/documents");
    await waitForSessionBootstrap(page);

    // ForbiddenState or ErrorState should render for 403
    await expect(
      page
        .getByText(/Access denied/i)
        .or(page.getByText(/permission/i))
        .first(),
    ).toBeVisible({ timeout: 15_000 });
  });
});
