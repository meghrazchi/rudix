#!/usr/bin/env node
// Playwright web server for the chromium-runtime-config project (R08-11).
//
// Builds the app once in request mode with API URL A into its own dist dir,
// then starts the standalone server with API URL B. The spec asserts that the
// browser and the CSP use B: the values are read at request time, not baked.
//
//   node e2e/support/runtime-config-server.mjs <port>
//
// Set RUNTIME_CONFIG_E2E_SKIP_BUILD=true to reuse an existing build.
import { spawnSync, spawn } from "node:child_process";
import { cpSync, existsSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const supportDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(supportDir, "..", "..");
// Shared with e2e/runtime-config.spec.ts.
const settings = JSON.parse(
  readFileSync(path.join(supportDir, "runtime-config-e2e.json"), "utf8"),
);
const RUNTIME_E2E_DIST_DIR = settings.distDir;
const BUILD_API_URL = settings.buildApiUrl;
const RUNTIME_API_URL = settings.runtimeApiUrl;

function sharedEnv(port) {
  const env = { ...process.env };
  delete env.NODE_ENV;
  return {
    ...env,
    NEXT_DIST_DIR: RUNTIME_E2E_DIST_DIR,
    NEXT_TELEMETRY_DISABLED: "1",
    NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE: "request",
    NEXT_PUBLIC_DEPLOYMENT_ENV: "development",
    NEXT_PUBLIC_APP_URL: `http://127.0.0.1:${port}`,
    NEXT_PUBLIC_AUTH_PROVIDER: "app",
    NEXT_PUBLIC_AUTH_LOGIN_URL: "",
    NEXT_PUBLIC_AUTH_REFRESH_URL: "",
    NEXT_PUBLIC_AUTH_LOCAL_FALLBACK: "false",
    NEXT_PUBLIC_AUTH_LOCAL_PASSWORD: "",
    NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN: "",
    NEXT_PUBLIC_AUTH_DEFAULT_REFRESH_TOKEN: "",
    NEXT_PUBLIC_CSP_ENFORCE: "",
    NEXT_PUBLIC_ASSET_PREFIX: "",
  };
}

function build(port) {
  const result = spawnSync("npx", ["next", "build"], {
    cwd: frontendRoot,
    stdio: "inherit",
    env: { ...sharedEnv(port), NEXT_PUBLIC_API_URL: BUILD_API_URL },
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
  // The standalone server serves static files and public/ from its own dir.
  const distDir = path.join(frontendRoot, RUNTIME_E2E_DIST_DIR);
  const standalone = path.join(distDir, "standalone");
  const staticTarget = path.join(standalone, RUNTIME_E2E_DIST_DIR, "static");
  rmSync(staticTarget, { recursive: true, force: true });
  cpSync(path.join(distDir, "static"), staticTarget, { recursive: true });
  cpSync(path.join(frontendRoot, "public"), path.join(standalone, "public"), {
    recursive: true,
  });
}

function start(port) {
  const server = path.join(
    frontendRoot,
    RUNTIME_E2E_DIST_DIR,
    "standalone",
    "server.js",
  );
  if (!existsSync(server)) {
    console.error(`runtime-config e2e: ${server} is missing; build first`);
    process.exit(1);
  }
  const child = spawn(process.execPath, [server], {
    cwd: path.dirname(server),
    stdio: "inherit",
    env: {
      ...sharedEnv(port),
      NODE_ENV: "production",
      PORT: String(port),
      HOSTNAME: "127.0.0.1",
      NEXT_PUBLIC_API_URL: RUNTIME_API_URL,
    },
  });
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => child.kill(signal));
  }
  child.on("exit", (code) => process.exit(code ?? 0));
}

const port = Number.parseInt(process.argv[2] ?? "3104", 10);
if (process.env.RUNTIME_CONFIG_E2E_SKIP_BUILD !== "true") {
  build(port);
}
start(port);
