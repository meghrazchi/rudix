import { expect, test, type Page, type Route } from "@playwright/test";

// Route error boundaries (R07-08). /admin/error-probe throws during render
// when the dev server runs with NEXT_PUBLIC_E2E_ERROR_PROBE=true
// (playwright.config.ts). The segment boundary must keep the app shell and
// navigation usable.

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";

const adminSession = {
  userId: "e2e-admin-1",
  email: "admin@example.com",
  role: "admin" as const,
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-admin-token",
  refreshToken: "e2e-admin-refresh",
};

async function fulfillJson(route: Route, body: unknown): Promise<void> {
  await route.fulfill({
    status: 200,
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
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");

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
    if (path === "/notifications/unread-count") {
      await fulfillJson(route, { unread_count: 0 });
      return;
    }
    if (path === "/auth/effective-permissions") {
      await fulfillJson(route, {
        permissions: ["documents:view", "chat:use", "admin:access"],
      });
      return;
    }
    await route.fallback();
  });

  await page.addInitScript(
    `window.localStorage.setItem(
      "${SESSION_STORAGE_KEY}",
      JSON.stringify(${JSON.stringify(adminSession)})
    );`,
  );
}

test("a render error in an admin page keeps the shell usable", async ({
  page,
}) => {
  await installApiMocks(page);
  await page.goto("/admin/error-probe");

  await expect(
    page.getByRole("heading", { name: "Unable to render this page" }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByRole("alert").filter({ hasText: "Unable to render this page" }),
  ).toBeVisible();

  const primaryNav = page.getByRole("navigation", {
    name: "Primary navigation",
  });
  await expect(primaryNav).toBeVisible();

  await primaryNav.getByRole("link", { name: "Dashboard" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(
    page.getByRole("heading", { name: "Unable to render this page" }),
  ).toHaveCount(0);
});

test("the segment fallback is translated with the locale cookie", async ({
  page,
  context,
  baseURL,
}) => {
  await context.addCookies([
    {
      name: "NEXT_LOCALE",
      value: "de",
      url: baseURL ?? "http://127.0.0.1:3000",
    },
  ]);
  await installApiMocks(page);
  await page.goto("/admin/error-probe");

  await expect(
    page.getByRole("heading", { name: "Seite kann nicht angezeigt werden" }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByRole("button", { name: "Erneut versuchen" }),
  ).toBeVisible();
});
