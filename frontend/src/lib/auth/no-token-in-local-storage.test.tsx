import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as authLogin from "@/lib/auth-login";
import {
  clearSessionStorage,
  readSessionFromStorage,
} from "@/lib/auth-session";
import { clearCrossTabRefreshLease } from "@/lib/auth-refresh-coordinator";

// R07-09 acceptance: no flow writes a token-bearing value to localStorage.

const TOKEN = "header.secret-access-token-xyz.signature";

const nav = vi.hoisted(() => ({
  params: new Map<string, string>(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => ({
    get: (key: string) => nav.params.get(key) ?? null,
    has: (key: string) => nav.params.has(key),
    toString: () => "",
  }),
  usePathname: () => "/",
}));

vi.mock("@/lib/api/team-invitations", () => ({
  acceptInvitation: vi.fn(async () => ({
    email: "invitee@example.com",
    organization_name: "Org",
    role: "member",
  })),
}));

const session = {
  userId: "user-1",
  email: "user@example.com",
  role: "member" as const,
  organizationId: "org-1",
  organizationName: "Org One",
  accessToken: TOKEN,
};

type SetItemSpy = {
  mock: { contexts: unknown[]; calls: unknown[][] };
  mockRestore: () => void;
};

let setItemSpy: SetItemSpy;

function localStorageWrites(): string[] {
  return setItemSpy.mock.contexts
    .map((context: unknown, index: number) =>
      context === window.localStorage
        ? String(setItemSpy.mock.calls[index]?.[1] ?? "")
        : null,
    )
    .filter((value: string | null): value is string => value !== null);
}

function expectNoTokenInLocalStorage(): void {
  for (const value of localStorageWrites()) {
    expect(value).not.toContain(TOKEN);
  }
  for (const value of Object.values(window.localStorage)) {
    expect(String(value)).not.toContain(TOKEN);
  }
}

describe("no access token in localStorage (R07-09)", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    clearSessionStorage();
    clearCrossTabRefreshLease();
    nav.params.clear();
    nav.replace.mockReset();
    setItemSpy = vi.spyOn(
      Storage.prototype,
      "setItem",
    ) as unknown as SetItemSpy;
  });

  afterEach(() => {
    setItemSpy.mockRestore();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    clearSessionStorage();
    process.env = { ...originalEnv };
  });

  it("login keeps the token in memory only", async () => {
    vi.spyOn(authLogin, "startLoginSession").mockResolvedValueOnce(session);
    const { default: LoginPage } =
      await import("@/app/[locale]/(public)/login/page");

    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(readSessionFromStorage()?.accessToken).toBe(TOKEN);
    });
    expectNoTokenInLocalStorage();
  });

  it("refresh keeps the rotated token in memory only", async () => {
    process.env.NEXT_PUBLIC_AUTH_REFRESH_URL = "http://api.test/auth/refresh";
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ access_token: TOKEN, user_id: "user-1" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
    const { refreshAccessToken } = await import("@/lib/api/request");

    const restored = await refreshAccessToken({ trigger: "startup" });

    expect(restored?.accessToken).toBe(TOKEN);
    expectNoTokenInLocalStorage();
  });

  it("SSO callback moves the token from the URL into memory", async () => {
    nav.params.set("access_token", TOKEN);
    nav.params.set("user_id", "user-1");
    nav.params.set("email", "user@example.com");
    nav.params.set("role", "member");
    nav.params.set("organization_id", "org-1");
    nav.params.set("next", "/dashboard");
    window.history.replaceState(
      null,
      "",
      `/sso/callback?access_token=${TOKEN}`,
    );
    const { default: SSOCallbackPage } =
      await import("@/app/[locale]/(public)/sso/callback/page");

    render(<SSOCallbackPage />);

    await waitFor(() => {
      expect(nav.replace).toHaveBeenCalledWith("/dashboard");
    });
    expect(readSessionFromStorage()?.accessToken).toBe(TOKEN);
    expect(window.location.search).toBe("");
    expect(window.location.href).not.toContain(TOKEN);
    expectNoTokenInLocalStorage();
  });

  it("accept-invite auto sign-in keeps the token in memory only", async () => {
    nav.params.set("token", "invite-token");
    vi.spyOn(authLogin, "startLoginSession").mockResolvedValueOnce(session);
    const { default: AcceptInvitePage } =
      await import("@/app/[locale]/(public)/accept-invite/page");

    render(<AcceptInvitePage />);
    await userEvent.type(
      await screen.findByPlaceholderText("Min 8 characters"),
      "password123",
    );
    await userEvent.type(
      screen.getByPlaceholderText("Repeat password"),
      "password123",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /accept|join|create|set/i }),
    );

    await waitFor(() => {
      expect(nav.replace).toHaveBeenCalledWith("/dashboard");
    });
    expect(readSessionFromStorage()?.accessToken).toBe(TOKEN);
    expectNoTokenInLocalStorage();
  });
});
