import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginFlowError, startLoginSession } from "@/lib/auth-login";

describe("startLoginSession", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    vi.unstubAllGlobals();
    process.env = { ...originalEnv };
    delete process.env.NEXT_PUBLIC_AUTH_LOGIN_URL;
    delete process.env.NEXT_PUBLIC_AUTH_LOCAL_PASSWORD;
    delete process.env.NEXT_PUBLIC_AUTH_DEFAULT_USER_ID;
    delete process.env.NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_ID;
    delete process.env.NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_NAME;
    delete process.env.NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    process.env = { ...originalEnv };
  });

  it("creates local fallback session when remote login is not configured", async () => {
    process.env.NEXT_PUBLIC_AUTH_LOCAL_FALLBACK = "true";
    process.env.NEXT_PUBLIC_AUTH_DEFAULT_USER_ID = "dev-user";
    process.env.NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_ID = "dev-org";
    process.env.NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_NAME = "Dev Org";

    const session = await startLoginSession({
      email: "user@example.com",
      password: "password123",
    });

    expect(session.userId).toBe("dev-user");
    expect(session.organizationId).toBe("dev-org");
    expect(session.organizationName).toBe("Dev Org");
    expect(session.email).toBe("user@example.com");
  });

  it("returns safe invalid-credentials error for local fallback password mismatch", async () => {
    process.env.NEXT_PUBLIC_AUTH_LOCAL_FALLBACK = "true";
    process.env.NEXT_PUBLIC_AUTH_LOCAL_PASSWORD = "correct-password";

    await expect(
      startLoginSession({
        email: "user@example.com",
        password: "wrong-password",
      }),
    ).rejects.toMatchObject({
      kind: "invalid_credentials",
      safeMessage: "Invalid email or password.",
    } satisfies Partial<LoginFlowError>);
  });

  it("maps remote 503 errors to safe network-failure message", async () => {
    process.env.NEXT_PUBLIC_AUTH_LOGIN_URL = "http://api.test/login";

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Service unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      startLoginSession({
        email: "user@example.com",
        password: "password123",
      }),
    ).rejects.toMatchObject({
      kind: "network_failure",
      safeMessage: "Unable to sign in right now. Check your connection and try again.",
    } satisfies Partial<LoginFlowError>);
  });
});
