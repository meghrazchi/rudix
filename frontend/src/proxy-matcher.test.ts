import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("next-intl/middleware", () => ({ default: () => () => null }));

import { config, proxy } from "./proxy";

// The matcher is a path-to-regexp pattern; for these literal paths it behaves
// like an anchored regular expression.
const matcher = new RegExp(`^${config.matcher[0]}$`);

describe("proxy matcher", () => {
  it.each([
    "/robots.txt",
    "/sitemap.xml",
    "/llms.txt",
    "/icon.svg",
    "/fonts/pelak/Pelak-Regular.ttf",
    "/images/chat-sample-2.png",
    "/brand/rudix-mark.svg",
    "/api/health",
    "/_next/static/chunk.js",
  ])("skips locale handling for %s", (path) => {
    expect(matcher.test(path)).toBe(false);
  });

  it.each([
    "/",
    "/en",
    "/fa/pricing",
    "/de/solutions/legal",
    "/dashboard",
    "/chat/shared/abc_DEF-123",
  ])("runs locale handling for %s", (path) => {
    expect(matcher.test(path)).toBe(true);
  });
});

describe("proxy route gate (R07-09)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  function restoreEnv(name: string, value: string | undefined): void {
    vi.stubEnv(name, value);
  }

  function request(path: string, cookies: Record<string, string> = {}) {
    const cookieHeader = Object.entries(cookies)
      .map(([name, value]) => `${name}=${value}`)
      .join("; ");
    return new NextRequest(new URL(path, "https://app.example.com"), {
      headers: cookieHeader ? { cookie: cookieHeader } : {},
    });
  }

  it.each([undefined, "off", "anything"])(
    "lets signed-out app requests through when the gate is %s",
    (gate) => {
      restoreEnv("RUDIX_ROUTE_GATE", gate);
      const response = proxy(request("/dashboard"));
      expect(response.headers.get("location")).toBeNull();
      expect(response.status).toBe(200);
    },
  );

  it("redirects a signed-out app request to the localized login page", () => {
    vi.stubEnv("RUDIX_ROUTE_GATE", "enforce");
    const response = proxy(
      request("/documents/abc?tab=versions", { NEXT_LOCALE: "de" }),
    );
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "https://app.example.com/de/login?next=%2Fdocuments%2Fabc%3Ftab%3Dversions",
    );
  });

  it("uses the default locale when no locale cookie is set", () => {
    vi.stubEnv("RUDIX_ROUTE_GATE", " Enforce ");
    const response = proxy(request("/dashboard"));
    expect(response.headers.get("location")).toBe(
      "https://app.example.com/en/login?next=%2Fdashboard",
    );
  });

  it("lets the request through when the session-hint cookie is present", () => {
    vi.stubEnv("RUDIX_ROUTE_GATE", "enforce");
    const response = proxy(request("/knowledge", { rudix_session_hint: "1" }));
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });

  it("honours a custom session-hint cookie name", () => {
    vi.stubEnv("RUDIX_ROUTE_GATE", "enforce");
    vi.stubEnv("RUDIX_SESSION_HINT_COOKIE_NAME", "custom_hint");
    expect(proxy(request("/chat", { rudix_session_hint: "1" })).status).toBe(
      307,
    );
    expect(proxy(request("/chat", { custom_hint: "1" })).status).toBe(200);
  });

  it("normalises a locale-prefixed app path before gating it", () => {
    vi.stubEnv("RUDIX_ROUTE_GATE", "enforce");
    const normalised = proxy(request("/fr/dashboard"));
    expect(normalised.headers.get("location")).toBe(
      "https://app.example.com/dashboard",
    );
    const gated = proxy(request("/dashboard", { NEXT_LOCALE: "fr" }));
    expect(gated.headers.get("location")).toBe(
      "https://app.example.com/fr/login?next=%2Fdashboard",
    );
  });

  it("leaves public paths to the locale middleware", () => {
    vi.stubEnv("RUDIX_ROUTE_GATE", "enforce");
    // next-intl is mocked to return null for public paths.
    expect(proxy(request("/en/pricing"))).toBeNull();
    expect(proxy(request("/en/login"))).toBeNull();
  });

  it("never runs for API routes", () => {
    expect(matcher.test("/api/v1/auth/token/refresh")).toBe(false);
  });
});
