import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { mockCorsHeaders } from "./support/mock-cors";
import settings from "./support/runtime-config-e2e.json";

// R08-11: runs against a production build made in request mode with API URL
// A (BUILD_API_URL) and started with API URL B (RUNTIME_API_URL), see
// e2e/support/runtime-config-server.mjs. Everything must use B.

const BUILD_API_URL = settings.buildApiUrl;
const RUNTIME_API_URL = settings.runtimeApiUrl;
const RUNTIME_E2E_DIST_DIR = settings.distDir;

const buildOrigin = new URL(BUILD_API_URL).origin;
const runtimeOrigin = new URL(RUNTIME_API_URL).origin;

test("serves the runtime values from /runtime-config.js", async ({
  request,
}) => {
  const response = await request.get("/runtime-config.js");
  expect(response.status()).toBe(200);
  const headers = response.headers();
  expect(headers["content-type"]).toContain("application/javascript");
  expect(headers["cache-control"]).toBe("no-store");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  const body = await response.text();
  expect(body).toContain(RUNTIME_API_URL);
  expect(body).not.toContain(BUILD_API_URL);
  expect(body).not.toContain("NEXT_PUBLIC_AUTH_LOCAL_PASSWORD");
});

for (const pagePath of ["/en", "/en/pricing", "/login"]) {
  test(`CSP on ${pagePath} names the runtime API origin`, async ({
    request,
  }) => {
    const response = await request.get(pagePath);
    expect(response.status()).toBeLessThan(400);
    const csp = response.headers()["content-security-policy-report-only"];
    expect(csp).toContain(`connect-src 'self' ${runtimeOrigin}`);
    expect(csp).not.toContain(buildOrigin);
    expect(response.headers()["x-frame-options"]).toBe("DENY");
  });
}

test("public pages stay prerendered and load the runtime config", async ({
  request,
}) => {
  const response = await request.get("/en/pricing");
  const html = await response.text();
  expect(html).toContain("/runtime-config.js");

  const frontendRoot = path.resolve(__dirname, "..");
  const check = spawnSync(
    process.execPath,
    [
      "scripts/check-prerendered-routes.mjs",
      "--dist-dir",
      RUNTIME_E2E_DIST_DIR,
    ],
    { cwd: frontendRoot, encoding: "utf8" },
  );
  expect(check.stderr).toBe("");
  expect(check.status).toBe(0);
});

test("the login page calls the runtime API URL", async ({ page }) => {
  const apiCalls: string[] = [];
  await page.route(
    (url) => url.origin === buildOrigin || url.origin === runtimeOrigin,
    async (route) => {
      const request = route.request();
      apiCalls.push(request.url());
      if (request.method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: mockCorsHeaders(request) });
        return;
      }
      await route.fulfill({
        status: 401,
        headers: {
          "content-type": "application/json",
          ...mockCorsHeaders(request),
        },
        body: JSON.stringify({ detail: "Invalid email or password." }),
      });
    },
  );

  await page.goto("/en/login");
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as unknown as {
              __RUDIX_RUNTIME_CONFIG__?: Record<string, string>;
            }
          ).__RUDIX_RUNTIME_CONFIG__?.NEXT_PUBLIC_API_URL,
      ),
    )
    .toBe(RUNTIME_API_URL);

  await page.getByLabel("Email").fill("member@example.com");
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect
    .poll(() => apiCalls.some((url) => url.startsWith(RUNTIME_API_URL)))
    .toBe(true);
  expect(apiCalls.filter((url) => url.startsWith(buildOrigin))).toEqual([]);
  expect(apiCalls.some((url) => url === `${RUNTIME_API_URL}/auth/login`)).toBe(
    true,
  );
});
