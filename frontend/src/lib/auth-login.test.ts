import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginFlowError, startLoginSession } from "@/lib/auth-login";

describe("startLoginSession", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    vi.unstubAllGlobals();
    process.env = { ...originalEnv };
    process.env.NEXT_PUBLIC_AUTH_PROVIDER = "app";
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
    process.env.NEXT_PUBLIC_AUTH_PROVIDER = "clerk";
    process.env.NEXT_PUBLIC_AUTH_LOCAL_FALLBACK = "true";
    process.env.NEXT_PUBLIC_AUTH_DEFAULT_USER_ID = "dev-user";
    process.env.NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_ID = "dev-org";
    process.env.NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_NAME = "Dev Org";
    process.env.NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN = "dev-token";

    const session = await startLoginSession({
      email: "user@example.com",
      password: "password123",
    });

    expect(session.userId).toBe("dev-user");
    expect(session.organizationId).toBe("dev-org");
    expect(session.organizationName).toBe("Dev Org");
    expect(session.email).toBe("user@example.com");
    expect(session.accessToken).toBe("dev-token");
  });

  it("returns not-configured error when app login response has no access token", async () => {
    process.env.NEXT_PUBLIC_AUTH_LOGIN_URL = "http://api.test/login";
    process.env.NEXT_PUBLIC_AUTH_LOCAL_FALLBACK = "false";

    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ user_id: "dev-user" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    vi.stubGlobal(
      "fetch",
      fetchMock,
    );

    await expect(
      startLoginSession({
        email: "user@example.com",
        password: "password123",
      }),
    ).rejects.toMatchObject({
      kind: "not_configured",
      safeMessage:
        "Sign-in is configured but no API access token is available. Set NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN or configure NEXT_PUBLIC_AUTH_LOGIN_URL to return access_token.",
    } satisfies Partial<LoginFlowError>);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.credentials).toBe("include");
  });

  it("returns safe invalid-credentials error for local fallback password mismatch", async () => {
    process.env.NEXT_PUBLIC_AUTH_PROVIDER = "clerk";
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
      safeMessage:
        "Unable to sign in right now. Check your connection and try again.",
    } satisfies Partial<LoginFlowError>);
  });
});
