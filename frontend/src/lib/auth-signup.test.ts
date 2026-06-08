import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SignupFlowError, startSignupSession } from "@/lib/auth-signup";

describe("startSignupSession", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    vi.unstubAllGlobals();
    process.env = { ...originalEnv };
    delete process.env.NEXT_PUBLIC_AUTH_SIGNUP_URL;
    delete process.env.NEXT_PUBLIC_AUTH_INVITE_ONLY;
    delete process.env.NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_PASSWORD;
    process.env.NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK = "true";
    process.env.NEXT_PUBLIC_AUTH_LOCAL_FALLBACK = "true";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    process.env = { ...originalEnv };
  });

  it("creates a local signup session and routes create-workspace flow to onboarding", async () => {
    const result = await startSignupSession({
      fullName: "Jane Doe",
      email: "new@example.com",
      password: "password123",
      workspaceMode: "create",
      workspaceName: "Acme Workspace",
      inviteCode: "",
      acceptTerms: true,
    });

    expect(result.session.email).toBe("new@example.com");
    expect(result.nextStep).toBe("onboarding");
  });

  it("returns duplicate-email safe error", async () => {
    await expect(
      startSignupSession({
        fullName: "Jane Doe",
        email: "existing@example.com",
        password: "password123",
        workspaceMode: "create",
        workspaceName: "Acme Workspace",
        inviteCode: "",
        acceptTerms: true,
      }),
    ).rejects.toMatchObject({
      kind: "duplicate_email",
      safeMessage: "An account with this email already exists.",
    } satisfies Partial<SignupFlowError>);
  });

  it("maps remote 409 errors to duplicate-email safe message", async () => {
    process.env.NEXT_PUBLIC_AUTH_SIGNUP_URL = "http://api.test/signup";

    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Email exists" }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );

    vi.stubGlobal("fetch", fetchMock);

    await expect(
      startSignupSession({
        fullName: "Jane Doe",
        email: "new@example.com",
        password: "password123",
        workspaceMode: "join",
        workspaceName: "",
        inviteCode: "INVITE123",
        acceptTerms: true,
      }),
    ).rejects.toMatchObject({
      kind: "duplicate_email",
      safeMessage: "An account with this email already exists.",
    } satisfies Partial<SignupFlowError>);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.credentials).toBe("include");
  });
});
