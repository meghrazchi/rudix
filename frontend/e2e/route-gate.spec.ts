import { expect, test, type Page, type Route } from "@playwright/test";

import { mockCorsHeaders } from "./support/mock-cors";

// R07-09: runs against the third dev server, started with
// RUDIX_ROUTE_GATE=enforce, a configured refresh URL and no dev session
// fallback, so a reload can only restore the session through the
// (mocked) refresh endpoint.

const HINT_COOKIE = "rudix_session_hint";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";
const ACCESS_TOKEN = "e2e-gate-access-token-7f3a";

type Role = "admin" | "member";

function sessionPayload(role: Role): Record<string, string> {
  return {
    access_token: ACCESS_TOKEN,
    token_type: "bearer",
    user_id: `e2e-${role}-1`,
    email: `${role}@example.com`,
    role,
    organization_id: ORG_ID,
    organization_name: "Rudix E2E Org",
  };
}

async function fulfillJson(
  route: Route,
  body: unknown,
  status = 200,
): Promise<void> {
  await route.fulfill({
    status,
    headers: {
      "content-type": "application/json",
      ...mockCorsHeaders(route.request()),
    },
    body: JSON.stringify(body),
  });
}

type ApiMockState = { refreshCalls: number; signedIn: boolean };

async function installApiMocks(
  page: Page,
  options: { role: Role; signedIn: boolean },
): Promise<ApiMockState> {
  const state: ApiMockState = { refreshCalls: 0, signedIn: options.signedIn };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");

    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: mockCorsHeaders(request) });
      return;
    }
    if (path === "/auth/token/refresh" && request.method() === "POST") {
      state.refreshCalls += 1;
      if (!state.signedIn) {
        await fulfillJson(
          route,
          { detail: { code: "session_invalid", message: "Sign in again." } },
          401,
        );
        return;
      }
      await fulfillJson(route, sessionPayload(options.role));
      return;
    }
    if (path === "/auth/login" && request.method() === "POST") {
      state.signedIn = true;
      await fulfillJson(route, sessionPayload(options.role));
      return;
    }
    if (path === "/auth/effective-permissions") {
      await fulfillJson(route, {
        permissions: ["documents:view", "chat:use"],
        role: options.role,
        custom_role_id: null,
      });
      return;
    }
    if (path === "/notifications/unread-count") {
      await fulfillJson(route, { unread_count: 0 });
      return;
    }
    await fulfillJson(route, { detail: "No e2e mock" }, 404);
  });
  return state;
}

async function addHintCookie(page: Page, baseURL: string): Promise<void> {
  await page
    .context()
    .addCookies([
      { name: HINT_COOKIE, value: "1", url: baseURL, httpOnly: true },
    ]);
}

async function expectNoTokenInLocalStorage(page: Page): Promise<void> {
  const values = await page.evaluate(() => Object.values(window.localStorage));
  for (const value of values) {
    expect(value).not.toContain(ACCESS_TOKEN);
  }
}

test.describe("server-side route gate (RUDIX_ROUTE_GATE=enforce)", () => {
  test("redirects a signed-out app request before rendering the shell", async ({
    request,
  }) => {
    const response = await request.get("/dashboard", { maxRedirects: 0 });

    expect(response.status()).toBe(307);
    const location = response.headers()["location"] ?? "";
    expect(new URL(location, "http://gate.test").pathname).toBe("/en/login");
    expect(location).toMatch(/\/en\/login\?next=%2Fdashboard$/);
    const body = await response.text();
    expect(body).not.toContain("Primary navigation");
    expect(body).not.toContain("Loading session");
  });

  test("keeps the requested path and query in next", async ({ request }) => {
    const response = await request.get("/documents?tab=recent", {
      maxRedirects: 0,
    });
    expect(response.status()).toBe(307);
    expect(response.headers()["location"]).toMatch(
      /\/en\/login\?next=%2Fdocuments%3Ftab%3Drecent$/,
    );
  });

  test("renders the shell with the hint cookie and a refreshed session", async ({
    page,
    baseURL,
  }) => {
    const api = await installApiMocks(page, { role: "admin", signedIn: true });
    await addHintCookie(page, baseURL!);

    await page.goto("/dashboard");

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(
      page
        .getByRole("navigation", { name: "Primary navigation" })
        .getByRole("link", { name: "Dashboard" }),
    ).toBeVisible({ timeout: 30_000 });
    expect(api.refreshCalls).toBeGreaterThanOrEqual(1);
    await expectNoTokenInLocalStorage(page);
  });

  test("still sends a member on an admin-only route to /forbidden", async ({
    page,
    baseURL,
  }) => {
    await installApiMocks(page, { role: "member", signedIn: true });
    await addHintCookie(page, baseURL!);

    await page.goto("/admin");

    await expect(page).toHaveURL(/\/forbidden$/, { timeout: 30_000 });
  });

  test("normalises a locale-prefixed app path, then gates it", async ({
    request,
  }) => {
    const prefixed = await request.get("/de/dashboard", { maxRedirects: 0 });
    expect(prefixed.status()).toBe(307);
    expect(
      new URL(prefixed.headers()["location"] ?? "", "http://gate.test")
        .pathname,
    ).toBe("/dashboard");

    const gated = await request.get("/dashboard", {
      maxRedirects: 0,
      headers: { cookie: "NEXT_LOCALE=de" },
    });
    expect(gated.status()).toBe(307);
    expect(gated.headers()["location"]).toMatch(
      /\/de\/login\?next=%2Fdashboard$/,
    );
  });

  test("leaves public pages alone", async ({ request }) => {
    for (const path of ["/en", "/en/pricing", "/en/login"]) {
      const response = await request.get(path, { maxRedirects: 0 });
      expect(response.status(), path).toBe(200);
    }
  });

  test("login keeps the token out of localStorage and a reload restores it", async ({
    page,
    baseURL,
  }) => {
    const api = await installApiMocks(page, { role: "admin", signedIn: false });

    await page.goto("/en/login?next=%2Fdashboard");
    await page.getByLabel("Email").fill("admin@example.com");
    await page.getByLabel("Password").fill("password123");
    // The real API sets the HttpOnly hint cookie on sign-in; the mock
    // cannot set a cookie for the frontend host, so the test adds it.
    await addHintCookie(page, baseURL!);
    await page.getByRole("button", { name: "Sign in" }).click();

    const nav = page.getByRole("navigation", { name: "Primary navigation" });
    await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible({
      timeout: 30_000,
    });
    await expectNoTokenInLocalStorage(page);

    const refreshesBeforeReload = api.refreshCalls;
    await page.reload();

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible({
      timeout: 30_000,
    });
    expect(api.refreshCalls).toBeGreaterThan(refreshesBeforeReload);
    await expectNoTokenInLocalStorage(page);
  });
});
