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
    // Icons and fonts are self-hosted (R07-04): no Google Fonts allowance.
    expect(policy).not.toContain("fonts.googleapis.com");
    expect(policy).not.toContain("fonts.gstatic.com");
    expect(policy).toContain("font-src 'self' data:");
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
  it("adds the contact submit origin to connect-src, not the external URL", () => {
    const policy = csp({
      NEXT_PUBLIC_CONTACT_SUBMIT_API_URL: "https://forms.example.com/submit",
      NEXT_PUBLIC_CONTACT_SUBMIT_EXTERNAL_URL: "https://ext.example.com/x",
      NEXT_PUBLIC_CONTACT_SCHEDULER_URL: "https://cal.example.com/demo",
    });
    expect(directive(policy, "connect-src")).toContain(
      "https://forms.example.com",
    );
    expect(policy).not.toContain("ext.example.com");
    expect(policy).not.toContain("cal.example.com");
    expect(policy).toContain("form-action 'self'");
  });

  it("defaults frame-src to none", () => {
    expect(directive(csp({}), "frame-src")).toBe("frame-src 'none'");
  });

  it("adds known captcha provider hosts case-insensitively", () => {
    const ts = csp({ NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER: " Turnstile " });
    for (const name of ["script-src", "frame-src", "connect-src"]) {
      expect(directive(ts, name)).toContain(
        "https://challenges.cloudflare.com",
      );
    }
    expect(directive(ts, "frame-src")).toContain("'self'");
    expect(directive(ts, "style-src")).not.toContain("cloudflare");

    const hc = csp({ NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER: "hcaptcha" });
    for (const name of [
      "script-src",
      "frame-src",
      "connect-src",
      "style-src",
    ]) {
      expect(directive(hc, name)).toContain("https://hcaptcha.com");
      expect(directive(hc, name)).toContain("https://*.hcaptcha.com");
    }

    const rc = csp({ NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER: "RECAPTCHA" });
    for (const name of ["script-src", "frame-src"]) {
      expect(directive(rc, name)).toContain("https://www.google.com");
      expect(directive(rc, name)).toContain("https://www.gstatic.com");
    }
    expect(directive(rc, "connect-src")).toContain("https://www.google.com");
    expect(directive(rc, "connect-src")).not.toContain("gstatic");
  });

  it("adds nothing for unknown captcha providers", () => {
    const base = csp({});
    for (const provider of ["acme", "", "constructor", "__proto__"]) {
      expect(csp({ NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER: provider })).toBe(
        base,
      );
    }
  });

  it("uses report-only by default and enforces with NEXT_PUBLIC_CSP_ENFORCE", () => {
    const def = headerMap({});
    expect(def["Content-Security-Policy-Report-Only"]).toBeDefined();
    expect(def["Content-Security-Policy"]).toBeUndefined();
    for (const value of ["false", "", "1"]) {
      expect(
        headerMap({ NEXT_PUBLIC_CSP_ENFORCE: value })[
          "Content-Security-Policy"
        ],
      ).toBeUndefined();
    }
    const env = { NEXT_PUBLIC_CSP_ENFORCE: " TRUE " };
    const enforced = headerMap(env);
    expect(enforced["Content-Security-Policy-Report-Only"]).toBeUndefined();
    expect(enforced["Content-Security-Policy"]).toBe(
      def["Content-Security-Policy-Report-Only"],
    );
  });
});
