import { describe, expect, it } from "vitest";

import {
  buildRuntimeConfigScript,
  runtimeConfigResponse,
  toScriptSafeJson,
} from "./runtime-config-script";

function evaluate(script: string): Record<string, string> {
  const target: { __RUDIX_RUNTIME_CONFIG__?: Record<string, string> } = {};
  new Function("window", script)(target);
  return target.__RUDIX_RUNTIME_CONFIG__ ?? {};
}

describe("runtime-config script", () => {
  it("serves allowlisted names only", () => {
    const values = evaluate(
      buildRuntimeConfigScript({
        NEXT_PUBLIC_API_URL: "https://api.example.com/api/v1",
        NEXT_PUBLIC_SUPPORT_URL: "",
        NEXT_PUBLIC_AUTH_LOCAL_PASSWORD: "dev-password",
        NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN: "dev-token",
        NEXT_PUBLIC_PUBLIC_SITE_URL: "https://www.example.com",
        APP_AUTH_SECRET: "server-secret",
        DATABASE_URL: "postgresql://user:pass@db/rudix",
      }),
    );
    expect(values).toEqual({
      NEXT_PUBLIC_API_URL: "https://api.example.com/api/v1",
      NEXT_PUBLIC_SUPPORT_URL: "",
    });
  });

  it("freezes the served object", () => {
    const values = evaluate(
      buildRuntimeConfigScript({ NEXT_PUBLIC_GA_ID: "G-1" }),
    );
    expect(Object.isFrozen(values)).toBe(true);
  });

  it("escapes characters that could end the script or break parsing", () => {
    const hostile = "</script><script>alert(1)</script>&\u2028\u2029";
    const script = buildRuntimeConfigScript({
      NEXT_PUBLIC_SUPPORT_URL: hostile,
    });
    expect(script).not.toMatch(/[<>&\u2028\u2029]/);
    expect(script).toContain("\\u003c/script\\u003e");
    expect(script).toContain("\\u0026\\u2028\\u2029");
    expect(evaluate(script).NEXT_PUBLIC_SUPPORT_URL).toBe(hostile);
    expect(toScriptSafeJson({ a: "<>" })).toBe('{"a":"\\u003c\\u003e"}');
  });
});

describe("runtimeConfigResponse", () => {
  it("answers 404 in build mode without any value", async () => {
    const response = runtimeConfigResponse("build", {
      NEXT_PUBLIC_API_URL: "https://api.example.com",
    });
    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.text()).not.toContain("api.example.com");
  });

  it("serves JavaScript with no-store and nosniff in request mode", async () => {
    const response = runtimeConfigResponse("request", {
      NEXT_PUBLIC_API_URL: "https://api.example.com/api/v1",
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe(
      "application/javascript; charset=utf-8",
    );
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    const body = await response.text();
    expect(
      body.startsWith("window.__RUDIX_RUNTIME_CONFIG__=Object.freeze("),
    ).toBe(true);
    expect(evaluate(body).NEXT_PUBLIC_API_URL).toBe(
      "https://api.example.com/api/v1",
    );
  });
});
