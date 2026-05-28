import { defineConfig, devices } from "@playwright/test";

const FRONTEND_PORT = Number.parseInt(
  process.env.PLAYWRIGHT_FRONTEND_PORT ?? "3101",
  10,
);
const FRONTEND_BASE_URL = `http://localhost:${FRONTEND_PORT}`;
const useBundledBrowser =
  process.env.PLAYWRIGHT_USE_BUNDLED_BROWSER === "true" ||
  process.env.CI === "true";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  workers: process.env.CI ? 2 : 1,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "dot" : "list",
  use: {
    baseURL: FRONTEND_BASE_URL,
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(useBundledBrowser ? {} : { channel: "chrome" }),
      },
    },
  ],
  webServer: {
    command: `npm run dev -- --hostname localhost --port ${FRONTEND_PORT}`,
    // Use a route-level readiness URL to reduce accidental reuse of unrelated apps.
    url: `${FRONTEND_BASE_URL}/login`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_APP_URL: FRONTEND_BASE_URL,
      NEXT_PUBLIC_API_URL: "http://localhost:8000/api/v1",
      NEXT_PUBLIC_DASHBOARD_ENABLE_ADMIN_USAGE: "false",
      NEXT_PUBLIC_AUTH_PROVIDER: "app",
      NEXT_PUBLIC_AUTH_LOGIN_URL: "",
      NEXT_PUBLIC_AUTH_LOCAL_FALLBACK: "true",
      NEXT_PUBLIC_AUTH_LOCAL_PASSWORD: "123123123",
      NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN: "e2e-access-token",
      NEXT_PUBLIC_AUTH_DEFAULT_REFRESH_TOKEN: "e2e-refresh-token",
      NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_ID:
        "c8ae2f17-c58e-499e-88bf-e6b0a8648c21",
      NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_NAME: "Rudix E2E Org",
      NEXT_PUBLIC_AUTH_DEFAULT_ROLE: "admin",
      NEXT_PUBLIC_CHAT_AGENTIC_ENABLED: "true",
      NEXT_PUBLIC_CHAT_AGENTIC_DEFAULT: "false",
      NEXT_PUBLIC_PUBLIC_PRODUCT_URL: "/product",
      NEXT_PUBLIC_PUBLIC_SOLUTIONS_URL: "/solutions",
      NEXT_PUBLIC_PUBLIC_SECURITY_URL: "/security",
      NEXT_PUBLIC_PUBLIC_PRICING_URL: "/pricing",
      NEXT_PUBLIC_PUBLIC_TRIAL_URL: "/signup",
      NEXT_PUBLIC_PUBLIC_DEMO_URL: "/contact",
      NEXT_PUBLIC_PUBLIC_LOGIN_URL: "/login",
    },
  },
});
