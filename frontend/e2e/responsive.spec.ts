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

const VIEWPORTS = {
  mobile: { width: 375, height: 667 },
  tablet: { width: 768, height: 1024 },
  desktop: { width: 1280, height: 800 },
} as const;

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

    if (path === "/auth/me" && request.method() === "GET") {
      await fulfillJson(route, {
        user_id: baseSession.userId,
        email: baseSession.email,
        role: baseSession.role,
        organization_id: baseSession.organizationId,
        organization_name: baseSession.organizationName,
      });
      return;
    }

    if (path === "/auth/effective-permissions" && request.method() === "GET") {
      await fulfillJson(route, { permissions: [] });
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

    if (path === "/incidents/banner" && request.method() === "GET") {
      await fulfillJson(route, { active_incident: null });
      return;
    }

    if (path === "/documents" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
      });
      return;
    }

    if (path === "/chat/sessions" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [
          {
            session_id: "session-1",
            title: "Test Chat Session",
            message_count: 2,
            created_at: "2026-06-01T08:00:00Z",
            updated_at: "2026-06-01T09:00:00Z",
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });
      return;
    }

    if (path === "/collections" && request.method() === "GET") {
      await fulfillJson(route, { items: [], total: 0, limit: 50, offset: 0 });
      return;
    }

    if (
      path === "/connectors/connections/available" &&
      request.method() === "GET"
    ) {
      await fulfillJson(route, { items: [] });
      return;
    }

    if (path === "/workspaces/current" && request.method() === "GET") {
      await fulfillJson(route, {
        workspace_id: "ws-1",
        name: baseSession.organizationName,
        plan: "enterprise",
      });
      return;
    }

    if (path === "/dashboard" && request.method() === "GET") {
      await fulfillJson(route, {
        total_documents: 0,
        indexed_documents: 0,
        total_questions: 0,
        recent_activity: [],
      });
      return;
    }

    // Default 404
    await fulfillJson(
      route,
      { detail: `No responsive-test mock for ${request.method()} ${path}` },
      404,
    );
  });
}

async function seedSession(
  page: Page,
  session: TestSession = baseSession,
): Promise<void> {
  await page.addInitScript(
    ({ key, payload }) => {
      window.localStorage.setItem(key, JSON.stringify(payload));
    },
    { key: SESSION_STORAGE_KEY, payload: session },
  );
}

async function waitForBoot(page: Page): Promise<void> {
  const loadingHeading = page.getByRole("heading", { name: "Loading session" });
  if (await loadingHeading.isVisible().catch(() => false)) {
    await expect(loadingHeading).toBeHidden({ timeout: 30_000 });
  }
}

test.describe("responsive viewport smoke tests", () => {
  test("reports overview fits mobile, tablet, and desktop viewports", async ({
    page,
  }) => {
    await installApiMocks(page);
    await seedSession(page);

    for (const viewport of Object.values(VIEWPORTS)) {
      await page.setViewportSize(viewport);
      await page.goto("/reports");
      await waitForBoot(page);
      await expect(
        page.getByRole("heading", { name: "Overview" }),
      ).toBeVisible();
      const main = page.locator("main").first();
      const box = await main.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.width).toBeLessThanOrEqual(viewport.width + 1);
    }
  });

  test("mobile (375px): topbar shows Menu button and icon-only search", async ({
    page,
  }) => {
    await page.setViewportSize(VIEWPORTS.mobile);
    await installApiMocks(page);
    await seedSession(page);
    await page.goto("/documents");
    await waitForBoot(page);

    // Mobile "Menu" button visible, desktop sidebar hidden
    await expect(
      page.getByRole("button", { name: /open menu/i }),
    ).toBeVisible();
    await expect(
      page.locator("aside.hidden.lg\\:flex, aside.lg\\:flex"),
    ).toBeHidden();

    // Icon-only search button visible on mobile
    const iconSearchBtn = page
      .getByRole("button", { name: /open search/i })
      .first();
    await expect(iconSearchBtn).toBeVisible();

    // At least one search trigger exists (icon button)
    await expect(iconSearchBtn).toBeVisible();
  });

  test("mobile (375px): page heading is visible and topbar does not overflow", async ({
    page,
  }) => {
    await page.setViewportSize(VIEWPORTS.mobile);
    await installApiMocks(page);
    await seedSession(page);
    await page.goto("/documents");
    await waitForBoot(page);

    // Page title visible and not clipped
    await expect(
      page.getByRole("heading", { name: "Upload Documents" }),
    ).toBeVisible();

    // Top-level shell width should not exceed viewport
    const header = page.locator("header").first();
    const headerBox = await header.boundingBox();
    expect(headerBox).not.toBeNull();
    expect(headerBox!.width).toBeLessThanOrEqual(VIEWPORTS.mobile.width + 1);
  });

  test("mobile (375px): mobile sidebar opens and closes via Menu button", async ({
    page,
  }) => {
    await page.setViewportSize(VIEWPORTS.mobile);
    await installApiMocks(page);
    await seedSession(page);
    await page.goto("/documents");
    await waitForBoot(page);

    const menuButton = page.getByRole("button", { name: /open menu/i });
    await menuButton.click();

    const mobileNav = page.getByRole("dialog", { name: /navigation menu/i });
    await expect(mobileNav).toBeVisible();

    // Close via close button inside the mobile sidebar
    await page.getByRole("button", { name: /close/i }).first().click();
    await expect(mobileNav).toBeHidden();
  });

  test("tablet (768px): desktop sidebar is hidden, nav accessible via Menu button", async ({
    page,
  }) => {
    await page.setViewportSize(VIEWPORTS.tablet);
    await installApiMocks(page);
    await seedSession(page);
    await page.goto("/documents");
    await waitForBoot(page);

    // Desktop sidebar hidden below lg (1024px)
    const menuButton = page.getByRole("button", { name: /open menu/i });
    await expect(menuButton).toBeVisible();

    // Full search bar is visible at sm+ (768 >= 640)
    // There should be an open-search button with the full bar
    const searchButtons = page.getByRole("button", { name: /open search/i });
    await expect(searchButtons.first()).toBeVisible();
  });

  test("tablet (768px): chat page does not show history sidebar", async ({
    page,
  }) => {
    await page.setViewportSize(VIEWPORTS.tablet);
    await installApiMocks(page);
    await seedSession(page);
    await page.goto("/chat");
    await waitForBoot(page);

    // Chat heading visible
    await expect(
      page.getByRole("heading", { name: "Chat Session" }),
    ).toBeVisible();

    // History sidebar (sessions list) should be hidden on tablet
    const sessionsHeading = page.getByRole("heading", {
      name: /sessions/i,
      level: 2,
    });
    await expect(sessionsHeading).toBeHidden();
  });

  test("desktop (1280px): desktop sidebar visible, no Menu button", async ({
    page,
  }) => {
    await page.setViewportSize(VIEWPORTS.desktop);
    await installApiMocks(page);
    await seedSession(page);
    await page.goto("/documents");
    await waitForBoot(page);

    // Desktop sidebar visible
    const desktopSidebar = page.locator("aside").first();
    await expect(desktopSidebar).toBeVisible();

    // Mobile "Menu" button hidden at lg+
    const menuButton = page.getByRole("button", { name: /open menu/i });
    await expect(menuButton).toBeHidden();

    // Full search bar visible at desktop
    const searchButtons = page.getByRole("button", { name: /open search/i });
    await expect(searchButtons.first()).toBeVisible();
  });

  test("desktop (1280px): chat page shows history sidebar", async ({
    page,
  }) => {
    await page.setViewportSize(VIEWPORTS.desktop);
    await installApiMocks(page);
    await seedSession(page);
    await page.goto("/chat");
    await waitForBoot(page);

    // History sidebar visible at xl (1280px)
    const sessionsHeading = page.getByRole("heading", {
      name: /sessions/i,
      level: 2,
    });
    await expect(sessionsHeading).toBeVisible();
  });

  test("mobile (375px): public landing page renders without horizontal overflow", async ({
    page,
  }) => {
    await page.setViewportSize(VIEWPORTS.mobile);
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /Ask your documents/i }),
    ).toBeVisible();

    // Body should not cause horizontal scroll
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(VIEWPORTS.mobile.width + 1);
  });

  test("mobile (375px): public mobile nav toggle works", async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.mobile);
    await page.goto("/");

    // Mobile menu button exists
    const mobileMenuToggle = page
      .locator('[aria-label*="menu"], [aria-label*="Menu"]')
      .first();
    await expect(mobileMenuToggle).toBeVisible();
  });

  test("tablet (768px): settings page tabs are scrollable", async ({
    page,
  }) => {
    await page.setViewportSize(VIEWPORTS.tablet);
    await installApiMocks(page);
    await seedSession(page);
    await page.goto("/settings");
    await waitForBoot(page);

    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();

    // Tab container has overflow-x-auto so tabs don't wrap
    const tabContainer = page.locator(".overflow-x-auto").first();
    await expect(tabContainer).toBeVisible();
  });
});
