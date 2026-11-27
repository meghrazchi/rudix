import { defineConfig, devices } from "@playwright/test";

// Critical-path suite against the real integration stack (R03-04): API, worker,
// Postgres, Qdrant, MinIO, RabbitMQ, Redis and the deterministic LLM stub from
// deploy/compose/docker-compose.integration-stub.yml. The suite is skipped
// unless RUDIX_E2E_INTEGRATION=1. Kept apart from playwright.config.ts
// (testDir ./e2e), which runs against mocked APIs.

const APP_URL = process.env.RUDIX_E2E_APP_URL ?? "http://127.0.0.1:3200";
const API_URL = process.env.RUDIX_E2E_API_URL ?? "http://localhost:8000/api/v1";
const startWebServer =
  process.env.RUDIX_E2E_INTEGRATION === "1" &&
  !process.env.RUDIX_E2E_SKIP_WEBSERVER;

export default defineConfig({
  testDir: "./e2e-integration",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // Upload, indexing (up to 120 s) and one grounded chat answer.
  timeout: 240_000,
  expect: {
    timeout: 15_000,
  },
  outputDir: "test-results/integration",
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-integration" }],
  ],
  use: {
    baseURL: APP_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "integration",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: startWebServer
    ? {
        command: "npm run build && npm run start -- -p 3200",
        url: `${APP_URL}/login`,
        reuseExistingServer: false,
        timeout: 600_000,
        env: {
          NEXT_PUBLIC_API_URL: API_URL,
          NEXT_PUBLIC_APP_URL: APP_URL,
          NEXT_PUBLIC_AUTH_PROVIDER: "app",
          NEXT_PUBLIC_AUTH_LOGIN_URL: "",
          NEXT_PUBLIC_PROXY_TARGET: "",
          // The suite logs in for real: every dev-only auth fallback is off.
          NEXT_PUBLIC_AUTH_LOCAL_FALLBACK: "false",
          NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK: "false",
          NEXT_PUBLIC_AUTH_LOCAL_PASSWORD: "",
          NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_PASSWORD: "",
          NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN: "",
          NEXT_PUBLIC_AUTH_DEFAULT_REFRESH_TOKEN: "",
        },
      }
    : undefined,
});
