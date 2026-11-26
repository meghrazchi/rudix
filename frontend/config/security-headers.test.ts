import { describe, expect, it } from "vitest";

import {
  isProductionLikeEnvironment,
  resolveDeploymentEnvironment,
} from "./deployment-env.mjs";
import { buildSecurityHeaders } from "./security-headers.mjs";

type Env = Record<string, string | undefined>;

function headerMap(env: Env, isDev = false): Record<string, string> {
  return Object.fromEntries(
    buildSecurityHeaders(env, { isDev }).map((h) => [h.key, h.value]),
  );
}

function csp(env: Env, isDev = false): string {
  return headerMap(env, isDev)["Content-Security-Policy-Report-Only"];
}

function directive(policy: string, name: string): string {
  return policy.split("; ").find((d) => d.startsWith(`${name} `)) ?? "";
}

describe("deployment-env", () => {
  it("returns the first non-empty trimmed lower-cased value", () => {
    expect(
      resolveDeploymentEnvironment({
        NEXT_PUBLIC_DEPLOYMENT_ENV: "  ",
        NEXT_PUBLIC_ENVIRONMENT: " Staging ",
        NEXT_PUBLIC_SENTRY_ENVIRONMENT: "production",
      }),
    ).toBe("staging");
    expect(resolveDeploymentEnvironment({})).toBeNull();
  });

  it("detects production-like environments", () => {
    expect(
      isProductionLikeEnvironment({ NEXT_PUBLIC_DEPLOYMENT_ENV: "production" }),
    ).toBe(true);
    expect(
      isProductionLikeEnvironment({ NEXT_PUBLIC_DEPLOYMENT_ENV: "staging" }),
    ).toBe(true);
    expect(
      isProductionLikeEnvironment({
        NEXT_PUBLIC_DEPLOYMENT_ENV: "development",
      }),
    ).toBe(false);
    expect(isProductionLikeEnvironment({})).toBe(false);
  });
});

describe("buildSecurityHeaders", () => {
  it("always sets the static headers and frame-ancestors none", () => {
    const headers = headerMap({});
    expect(headers["X-Content-Type-Options"]).toBe("nosniff");
    expect(headers["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(headers["Permissions-Policy"]).toBe(
      "camera=(), microphone=(), geolocation=()",
    );
    expect(headers["X-Frame-Options"]).toBe("DENY");
    const policy = csp({});
    expect(policy).toContain("frame-ancestors 'none'");
    expect(policy).toContain("default-src 'self'");
    expect(policy).toContain("object-src 'none'");
    expect(policy).toContain("base-uri 'self'");
    expect(policy).toContain("form-action 'self'");
    expect(policy).toContain("fonts.googleapis.com");
    expect(policy).toContain("fonts.gstatic.com");
  });

  it("adds HSTS only when production-like", () => {
    expect(
      headerMap({ NEXT_PUBLIC_DEPLOYMENT_ENV: "production" })[
        "Strict-Transport-Security"
      ],
    ).toBe("max-age=31536000");
    expect(
      headerMap({ NEXT_PUBLIC_DEPLOYMENT_ENV: "staging" })[
        "Strict-Transport-Security"
      ],
    ).toBe("max-age=31536000");
    expect(
      headerMap({ NEXT_PUBLIC_DEPLOYMENT_ENV: "development" })[
        "Strict-Transport-Security"
      ],
    ).toBeUndefined();
  });

  it("adds unsafe-eval and ws: only in development", () => {
    const dev = csp({}, true);
    expect(directive(dev, "script-src")).toContain("'unsafe-eval'");
    expect(directive(dev, "connect-src")).toContain("ws:");
    const prod = csp({}, false);
    expect(directive(prod, "script-src")).not.toContain("'unsafe-eval'");
    expect(directive(prod, "connect-src")).not.toContain(" ws:");
    expect(directive(prod, "script-src")).toContain("'unsafe-inline'");
  });

  it("adds API, ws, Sentry, GA and Matomo origins only when configured", () => {
    const bare = csp({});
    expect(bare).not.toContain("googletagmanager");
    expect(bare).not.toContain("sentry");
    expect(directive(bare, "connect-src")).toBe("connect-src 'self'");

    const policy = csp({
      NEXT_PUBLIC_API_URL: "https://api.example.com/v1",
      NEXT_PUBLIC_SENTRY_DSN: "https://key@o1.ingest.sentry.io/42",
      NEXT_PUBLIC_GA_ID: "G-TEST",
      NEXT_PUBLIC_MATOMO_URL: "https://matomo.example.com/path",
    });
    const connect = directive(policy, "connect-src");
    expect(connect).toContain("https://api.example.com");
    expect(connect).not.toContain("/v1");
    expect(connect).toContain("wss://api.example.com");
    expect(connect).toContain("https://o1.ingest.sentry.io");
    expect(connect).toContain("https://*.analytics.google.com");
    expect(connect).toContain("https://matomo.example.com");
    expect(directive(policy, "script-src")).toContain(
      "https://www.googletagmanager.com",
    );
    expect(directive(policy, "script-src")).toContain(
      "https://matomo.example.com",
    );
    const img = directive(policy, "img-src");
    expect(img).toContain("https://api.example.com");
    expect(img).toContain("https://*.google-analytics.com");
    expect(img).toContain("https://matomo.example.com");
  });

  it("keeps the protocol of a self-hosted http Sentry DSN", () => {
    const connect = directive(
      csp({ NEXT_PUBLIC_SENTRY_DSN: "http://key@sentry.internal:9000/7" }),
      "connect-src",
    );
    expect(connect).toContain("http://sentry.internal:9000");
    expect(connect).not.toContain("https://sentry.internal");
  });

  it("uses ws:// for an http API origin and deduplicates sources", () => {
    const connect = directive(
      csp({
        NEXT_PUBLIC_API_URL: "http://localhost:8000",
        NEXT_PUBLIC_MATOMO_URL: "http://localhost:8000",
      }),
      "connect-src",
    );
    expect(connect).toContain("ws://localhost:8000");
    expect(connect.split("http://localhost:8000").length - 1).toBe(1);
  });

  it("adds report-uri only when set and valid", () => {
    expect(csp({})).not.toContain("report-uri");
    expect(csp({ NEXT_PUBLIC_CSP_REPORT_URI: "   " })).not.toContain(
      "report-uri",
    );
    expect(
      csp({ NEXT_PUBLIC_CSP_REPORT_URI: "https://csp.example.com/r?k=1" }),
    ).toContain("report-uri https://csp.example.com/r?k=1");
    expect(
      csp({ NEXT_PUBLIC_CSP_REPORT_URI: "https://x.com/a; script-src *" }),
    ).not.toContain("report-uri");
  });

  it("ignores invalid URLs without throwing", () => {
    const policy = csp({
      NEXT_PUBLIC_API_URL: "not a url",
      NEXT_PUBLIC_MATOMO_URL: "ftp://matomo.example.com",
      NEXT_PUBLIC_SENTRY_DSN: "::::",
      NEXT_PUBLIC_CSP_REPORT_URI: "nope",
    });
    expect(directive(policy, "connect-src")).toBe("connect-src 'self'");
    expect(policy).not.toContain("report-uri");
    expect(policy).not.toContain("matomo");
  });
});
