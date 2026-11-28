import { afterEach, describe, expect, it, vi } from "vitest";

type HeaderRule = {
  source: string;
  headers: { key: string; value: string }[];
};

type NextConfigModule = {
  default: {
    assetPrefix?: string;
    headers?: () => Promise<HeaderRule[]>;
  };
  buildHeaderRules: () => HeaderRule[];
};

async function loadConfig(env: Record<string, string>) {
  vi.resetModules();
  for (const [key, value] of Object.entries(env)) {
    vi.stubEnv(key, value);
  }
  return (await import("../next.config")) as unknown as NextConfigModule;
}

function headerKeys(rule: HeaderRule | undefined): string[] {
  return (rule?.headers ?? []).map((header) => header.key);
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("next.config headers (R08-11, R08-12)", () => {
  it("keeps the CSP in the build-time headers in build mode", async () => {
    const config = await loadConfig({
      NEXT_PUBLIC_API_URL: "https://api-a.example.com/api/v1",
    });
    const rules = (await config.default.headers?.()) ?? [];
    expect(rules).toHaveLength(1);
    expect(rules[0]?.source).toBe("/:path*");
    expect(headerKeys(rules[0])).toContain(
      "Content-Security-Policy-Report-Only",
    );
    const policy = rules[0]?.headers.find((header) =>
      header.key.startsWith("Content-Security-Policy"),
    );
    expect(policy?.value).toContain("https://api-a.example.com");
    expect(config.default.assetPrefix).toBeUndefined();
  });

  it("leaves the CSP to the proxy in request mode", async () => {
    const config = await loadConfig({
      NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE: "request",
      NEXT_PUBLIC_CSP_ENFORCE: "true",
    });
    const keys = headerKeys(config.buildHeaderRules()[0]);
    expect(keys).not.toContain("Content-Security-Policy");
    expect(keys).not.toContain("Content-Security-Policy-Report-Only");
    expect(keys).toContain("X-Frame-Options");
    expect(keys).toContain("X-Content-Type-Options");
  });

  it("sets assetPrefix and adds the CDN origin to the CSP", async () => {
    const config = await loadConfig({
      NEXT_PUBLIC_ASSET_PREFIX: "https://cdn.example.com/rudix/",
    });
    expect(config.default.assetPrefix).toBe("https://cdn.example.com/rudix");
    const policy = config
      .buildHeaderRules()[0]
      ?.headers.find((header) => header.key.startsWith("Content-Security"));
    expect(policy?.value).toContain("script-src 'self' 'unsafe-inline'");
    expect(policy?.value).toContain("https://cdn.example.com");
  });

  it("adds Cache-Control for public asset folders only when configured", async () => {
    const unset = await loadConfig({});
    expect(unset.buildHeaderRules().map((rule) => rule.source)).toEqual([
      "/:path*",
    ]);

    const config = await loadConfig({
      PUBLIC_ASSET_CACHE_CONTROL: "public, max-age=3600",
    });
    const rules = config.buildHeaderRules();
    expect(rules.map((rule) => rule.source)).toEqual([
      "/:path*",
      "/brand/:path*",
      "/fonts/:path*",
      "/images/:path*",
    ]);
    for (const rule of rules.slice(1)) {
      expect(rule.headers).toEqual([
        { key: "Cache-Control", value: "public, max-age=3600" },
      ]);
    }
  });
});
