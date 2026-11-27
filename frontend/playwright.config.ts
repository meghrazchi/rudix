import { defineConfig, devices } from "@playwright/test";

import { consentedStorageState } from "./e2e/support/consent";

const FRONTEND_PORT = Number.parseInt(
  process.env.PLAYWRIGHT_FRONTEND_PORT ?? "3101",
  10,
);
const FRONTEND_BASE_URL = `http://127.0.0.1:${FRONTEND_PORT}`;
// NEXT_PUBLIC values are inlined when the app is compiled, so WebSocket chat
// (NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED=true) needs its own dev server, on its
// own port and build directory. Only chat-ws-*.spec.ts runs against it.
const WS_FRONTEND_PORT = Number.parseInt(
  process.env.PLAYWRIGHT_WS_FRONTEND_PORT ?? "3102",
  10,
);
const WS_FRONTEND_BASE_URL = `http://127.0.0.1:${WS_FRONTEND_PORT}`;
const WS_SPECS = /chat-ws-.*\.spec\.ts$/;
// The server-side route gate (R07-09) reads RUDIX_ROUTE_GATE at request time
// and restores sessions only through the refresh cookie, so it gets a third
// dev server: gate enforced, refresh URL configured, no dev session fallback.
const GATE_FRONTEND_PORT = Number.parseInt(
  process.env.PLAYWRIGHT_GATE_FRONTEND_PORT ?? "3103",
  10,
);
const GATE_FRONTEND_BASE_URL = `http://127.0.0.1:${GATE_FRONTEND_PORT}`;
const GATE_SPECS = /route-gate\.spec\.ts$/;
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
    // Start as a visitor who already answered the cookie banner; the
    // first-visit banner is covered by e2e/cookie-consent.spec.ts.
    storageState: consentedStorageState(FRONTEND_BASE_URL),
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      testIgnore: [WS_SPECS, GATE_SPECS],
      use: {
        ...devices["Desktop Chrome"],
        ...(useBundledBrowser ? {} : { channel: "chrome" }),
      },
    },
    {
      name: "chromium-chat-ws",
      testMatch: WS_SPECS,
      use: {
        ...devices["Desktop Chrome"],
        ...(useBundledBrowser ? {} : { channel: "chrome" }),
        baseURL: WS_FRONTEND_BASE_URL,
        storageState: consentedStorageState(WS_FRONTEND_BASE_URL),
      },
    },
    {
      name: "chromium-route-gate",
      testMatch: GATE_SPECS,
      use: {
        ...devices["Desktop Chrome"],
        ...(useBundledBrowser ? {} : { channel: "chrome" }),
        baseURL: GATE_FRONTEND_BASE_URL,
        storageState: consentedStorageState(GATE_FRONTEND_BASE_URL),
      },
    },
  ],
  webServer: [
    devServer(FRONTEND_PORT, FRONTEND_BASE_URL, {}),
    devServer(WS_FRONTEND_PORT, WS_FRONTEND_BASE_URL, {
      NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED: "true",
      NEXT_DIST_DIR: ".next-e2e-ws",
    }),
    devServer(GATE_FRONTEND_PORT, GATE_FRONTEND_BASE_URL, {
      RUDIX_ROUTE_GATE: "enforce",
      NEXT_DIST_DIR: ".next-e2e-gate",
      NEXT_PUBLIC_AUTH_REFRESH_URL:
        "http://localhost:8000/api/v1/auth/token/refresh",
      NEXT_PUBLIC_AUTH_LOCAL_FALLBACK: "false",
      NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN: "",
      NEXT_PUBLIC_AUTH_DEFAULT_REFRESH_TOKEN: "",
    }),
  ],
});

function devServer(
  port: number,
  baseUrl: string,
  extraEnv: Record<string, string>,
) {
  return {
    command: `npm run dev -- --hostname 127.0.0.1 --port ${port}`,
    // Use a route-level readiness URL to reduce accidental reuse of unrelated apps.
    url: `${baseUrl}/login`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      // Hermetic env: with NODE_ENV=test, Next.js does not load the
      // developer's untracked `.env.local`, so local runs match CI.
      // See node_modules/next/dist/docs/01-app/02-guides/environment-variables.md
      // ("Test Environment Variables").
      NODE_ENV: "test",
      NEXT_PUBLIC_APP_URL: baseUrl,
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
      ...extraEnv,
    },
  };
}
