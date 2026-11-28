import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";

vi.mock("next-intl/middleware", () => ({
  default: () => () => NextResponse.next(),
}));

import { config, proxy } from "./proxy";

const CSP = "Content-Security-Policy";
const CSP_REPORT_ONLY = "Content-Security-Policy-Report-Only";

function request(path: string): NextRequest {
  return new NextRequest(new URL(path, "https://app.example.com"));
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("proxy /runtime-config.js (R08-11)", () => {
  it("is matched explicitly although it has an extension", () => {
    expect(config.matcher).toContain("/runtime-config.js");
  });

  it("answers 404 in build mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com/api/v1");
    const response = proxy(request("/runtime-config.js"));
    expect(response.status).toBe(404);
    expect(await response.text()).not.toContain("api.example.com");
  });

  it("serves the runtime values in request mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", "request");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api-b.example.com/api/v1");
    vi.stubEnv("APP_AUTH_SECRET", "never-served");
    const response = proxy(request("/runtime-config.js"));
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain(
      "application/javascript",
    );
    const body = await response.text();
    expect(body).toContain("https://api-b.example.com/api/v1");
    expect(body).not.toContain("never-served");
  });
});

describe("proxy CSP (R08-11)", () => {
  it("adds no CSP in build mode (next.config sets it at build)", () => {
    const response = proxy(request("/en"));
    expect(response.headers.get(CSP)).toBeNull();
    expect(response.headers.get(CSP_REPORT_ONLY)).toBeNull();
  });

  it("sets the report-only CSP from the runtime env in request mode", () => {
    vi.stubEnv("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", "request");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api-b.example.com/api/v1");
    const response = proxy(request("/en/pricing"));
    const policy = response.headers.get(CSP_REPORT_ONLY) ?? "";
    expect(policy).toContain(
      "connect-src 'self' https://api-b.example.com wss://api-b.example.com",
    );
    expect(response.headers.get(CSP)).toBeNull();
  });

  it("enforces the CSP when the runtime env says so", () => {
    vi.stubEnv("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", "request");
    vi.stubEnv("NEXT_PUBLIC_CSP_ENFORCE", "true");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api-c.example.com/api/v1");
    const response = proxy(request("/dashboard"));
    expect(response.headers.get(CSP)).toContain("https://api-c.example.com");
    expect(response.headers.get(CSP_REPORT_ONLY)).toBeNull();
  });

  it("sets the CSP on redirects too", () => {
    vi.stubEnv("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", "request");
    const response = proxy(request("/en/dashboard"));
    expect(response.status).toBeGreaterThanOrEqual(300);
    expect(response.headers.get(CSP_REPORT_ONLY)).toContain("default-src");
  });
});
