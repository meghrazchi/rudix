import { expect, test, type Page, type Route } from "@playwright/test";

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";

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

async function installChatApiMocks(page: Page): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {});
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

    if (path === "/connectors/available" && request.method() === "GET") {
      await fulfillJson(route, { items: [], total: 0, limit: 20, offset: 0 });
      return;
    }

    if (path === "/chat/sessions" && request.method() === "GET") {
      await fulfillJson(route, { items: [], total: 0, limit: 10, offset: 0 });
      return;
    }

    await fulfillJson(route, { detail: `No scroll mock for ${path}` });
  });
}

async function seedAuthenticatedSession(page: Page): Promise<void> {
  await page.addInitScript(
    ({ storageKey, payload }) => {
      window.localStorage.setItem(storageKey, JSON.stringify(payload));
    },
    {
      storageKey: SESSION_STORAGE_KEY,
      payload: {
        userId: "scroll-test-user",
        email: "member@example.com",
        role: "member",
        organizationId: ORG_ID,
        organizationName: "Rudix E2E Org",
        accessToken: "e2e-access-token",
        refreshToken: "e2e-refresh-token",
      },
    },
  );
}

test("public landing page scrolls on the document", async ({ page }) => {
  await page.goto("/en");

  await expect(
    page.getByRole("heading", { name: /Ask your documents/i }),
  ).toBeVisible();

  const canScroll = await page.evaluate(
    () => document.documentElement.scrollHeight > window.innerHeight,
  );
  expect(canScroll).toBe(true);

  await page.evaluate(() =>
    window.scrollTo(0, document.documentElement.scrollHeight),
  );

  await expect
    .poll(() => page.evaluate(() => window.scrollY), {
      message: "public page should allow window scrolling",
    })
    .toBeGreaterThan(0);
});

test.describe("localized public layout smoke checks", () => {
  for (const [path, label] of [
    ["/de", "German landing page"],
    ["/fr/contact", "French contact page"],
  ] as const) {
    test(`does not introduce horizontal overflow on the ${label}`, async ({
      page,
    }) => {
      await page.goto(path);

      await expect(page.locator("h1").first()).toBeVisible();

      const hasHorizontalOverflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth >
          document.documentElement.clientWidth + 1,
      );

      expect(hasHorizontalOverflow).toBe(false);
    });
  }
});

test("chat route does not scroll the document or app main container", async ({
  page,
}) => {
  await installChatApiMocks(page);
  await seedAuthenticatedSession(page);

  await page.goto("/chat");

  await expect(
    page.getByRole("heading", { name: "Chat Session" }),
  ).toBeVisible();

  const main = page.getByRole("main");
  await expect(main).toHaveCSS("overflow-y", "hidden");

  await page.evaluate(() =>
    window.scrollTo(0, document.documentElement.scrollHeight),
  );

  await expect
    .poll(() => page.evaluate(() => window.scrollY), {
      message: "chat route should not allow document scrolling",
    })
    .toBe(0);
});
