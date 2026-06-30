import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseFrontendRuntimeConfig } from "@/lib/runtime-config";

function buildEnv(
  overrides: Record<string, string | undefined> = {},
): NodeJS.ProcessEnv {
  return {
    ...process.env,
    NEXT_PUBLIC_API_URL: "http://localhost:8000/api/v1",
    NEXT_PUBLIC_APP_URL: "http://localhost:3000",
    ...overrides,
  };
}

function collectSourceFiles(root: string): string[] {
  const entries = fs.readdirSync(root, { withFileTypes: true });
  const files: string[] = [];

  for (const entry of entries) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(fullPath));
      continue;
    }
    if (!entry.isFile()) {
      continue;
    }
    if (entry.name.endsWith(".ts") || entry.name.endsWith(".tsx")) {
      files.push(fullPath);
    }
  }

  return files;
}

describe("runtime config parsing", () => {
  it("parses required URLs and typed feature flags", () => {
    const { config, errors } = parseFrontendRuntimeConfig(
      buildEnv({
        NEXT_PUBLIC_API_URL: "https://api.example.com/v1/",
        NEXT_PUBLIC_APP_URL: "https://app.example.com/",
        NEXT_PUBLIC_AUTH_PROVIDER: "clerk",
        NEXT_PUBLIC_FEATURE_DEVELOPER_MODE: "true",
        NEXT_PUBLIC_CHAT_FEEDBACK_ENABLED: "true",
        NEXT_PUBLIC_FEATURE_EXPORTS_ENABLED: "false",
        NEXT_PUBLIC_FEATURE_UNAVAILABLE_BACKEND_ENDPOINTS: "false",
      }),
    );

    expect(errors).toEqual([]);
    expect(config.apiUrl).toBe("https://api.example.com/v1");
    expect(config.appUrl).toBe("https://app.example.com");
    expect(config.deploymentEnvironment).toBe("other");
    expect(config.authProvider).toBe("clerk");
    expect(config.features).toEqual({
      collectionsEnabled: true,
      developerMode: true,
      feedback: true,
      analyticsEnabled: true,
      exports: false,
      unavailableBackendEndpoints: false,
    });
    expect(config.analytics).toEqual({
      matomoUrl: null,
      matomoSiteId: null,
    });
  });

  it("returns a validation error when NEXT_PUBLIC_API_URL is missing", () => {
    const env = buildEnv();
    delete env.NEXT_PUBLIC_API_URL;

    const { errors } = parseFrontendRuntimeConfig(env);
    expect(errors).toContain(
      "NEXT_PUBLIC_API_URL is required and must be an absolute http(s) URL.",
    );
  });

  it("rejects localhost URLs for staging builds", () => {
    const { errors } = parseFrontendRuntimeConfig(
      buildEnv({
        NEXT_PUBLIC_DEPLOYMENT_ENV: "staging",
        NEXT_PUBLIC_API_URL: "http://localhost:8000/api/v1",
        NEXT_PUBLIC_APP_URL: "https://staging.getrudix.com",
      }),
    );

    expect(errors).toContain(
      "NEXT_PUBLIC_API_URL must use https:// when NEXT_PUBLIC_DEPLOYMENT_ENV is staging or production.",
    );
    expect(errors).toContain(
      "NEXT_PUBLIC_API_URL must not point to localhost when NEXT_PUBLIC_DEPLOYMENT_ENV is staging or production.",
    );
  });

  it("accepts the staging frontend and API URLs", () => {
    const { config, errors } = parseFrontendRuntimeConfig(
      buildEnv({
        NEXT_PUBLIC_DEPLOYMENT_ENV: "staging",
        NEXT_PUBLIC_API_URL: "https://api-staging.getrudix.com/api/v1",
        NEXT_PUBLIC_APP_URL: "https://staging.getrudix.com",
      }),
    );

    expect(errors).toEqual([]);
    expect(config.deploymentEnvironment).toBe("staging");
    expect(config.apiUrl).toBe("https://api-staging.getrudix.com/api/v1");
    expect(config.appUrl).toBe("https://staging.getrudix.com");
  });

  it("accepts the production frontend and API URLs", () => {
    const { config, errors } = parseFrontendRuntimeConfig(
      buildEnv({
        NEXT_PUBLIC_DEPLOYMENT_ENV: "production",
        NEXT_PUBLIC_API_URL: "https://api.getrudix.com/api/v1",
        NEXT_PUBLIC_APP_URL: "https://getrudix.com",
      }),
    );

    expect(errors).toEqual([]);
    expect(config.deploymentEnvironment).toBe("production");
    expect(config.apiUrl).toBe("https://api.getrudix.com/api/v1");
    expect(config.appUrl).toBe("https://getrudix.com");
  });
});

describe("frontend env usage", () => {
  it("only references NEXT_PUBLIC_* or NODE_ENV variables", () => {
    const repoRoot = path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      "..",
      "..",
    );
    const sourceRoot = path.join(repoRoot, "src");
    const files = [
      ...collectSourceFiles(sourceRoot),
      path.join(repoRoot, "next.config.ts"),
    ];

    const invalidReferences: string[] = [];
    const matcher = /process\.env\.([A-Z0-9_]+)/g;

    for (const filePath of files) {
      const content = fs.readFileSync(filePath, "utf8");
      const matches = content.matchAll(matcher);
      for (const match of matches) {
        const key = match[1];
        if (!key) {
          continue;
        }
        if (
          key === "NODE_ENV" ||
          key === "NEXT_PHASE" ||
          key.startsWith("NEXT_PUBLIC_")
        ) {
          continue;
        }
        invalidReferences.push(`${path.relative(repoRoot, filePath)}:${key}`);
      }
    }

    expect(invalidReferences).toEqual([]);
  });
});
