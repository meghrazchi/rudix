import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AUTH_BOUNDARY_STORAGE_KEY,
  clearSessionStorage,
  readSessionFromStorage,
  writeSessionToStorage,
} from "@/lib/auth-session";
import { clearCrossTabRefreshLease } from "@/lib/auth-refresh-coordinator";
import { useAuthSession } from "@/lib/use-auth-session";

const session = {
  userId: "user-1",
  email: "user@example.com",
  role: "member" as const,
  organizationId: "org-1",
  organizationName: "Org One",
  accessToken: "token-1",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useAuthSession over the in-memory store (R07-09)", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const originalEnv = { ...process.env };

  beforeEach(() => {
    fetchMock.mockReset();
    window.localStorage.clear();
    clearSessionStorage();
    clearCrossTabRefreshLease();
    vi.stubGlobal("fetch", fetchMock);
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    clearSessionStorage();
    process.env = { ...originalEnv };
  });

  it("starts loading and restores the session through the refresh cookie", async () => {
    process.env.NEXT_PUBLIC_AUTH_REFRESH_URL = "http://api.test/auth/refresh";
    fetchMock.mockResolvedValueOnce(
      json({ access_token: "restored", user_id: "user-1", role: "admin" }),
    );

    const { result } = renderHook(() => useAuthSession());
    expect(result.current.state.status).toBe("loading");

    await waitFor(() => {
      expect(result.current.state.status).toBe("authenticated");
    });
    expect(result.current.state.session?.accessToken).toBe("restored");
    expect(result.current.state.session?.role).toBe("admin");
  });

  it("becomes unauthenticated when the refresh cookie is missing", async () => {
    process.env.NEXT_PUBLIC_AUTH_REFRESH_URL = "http://api.test/auth/refresh";
    fetchMock.mockResolvedValueOnce(json({ detail: "Missing" }, 401));

    const { result } = renderHook(() => useAuthSession());

    await waitFor(() => {
      expect(result.current.state.status).toBe("unauthenticated");
    });
    expect(result.current.boundaryEvent).toBeNull();
  });

  it("becomes unauthenticated when the startup refresh errors", async () => {
    process.env.NEXT_PUBLIC_AUTH_REFRESH_URL = "http://api.test/auth/refresh";
    fetchMock.mockRejectedValueOnce(new TypeError("network"));

    const { result } = renderHook(() => useAuthSession());

    await waitFor(() => {
      expect(result.current.state.status).toBe("unauthenticated");
    });
  });

  it("is authenticated at once when memory already holds a session", () => {
    writeSessionToStorage(session);
    const { result } = renderHook(() => useAuthSession());
    expect(result.current.state).toEqual({
      status: "authenticated",
      session,
    });
  });

  it("sets and signs out a session, updating every hook instance", async () => {
    const first = renderHook(() => useAuthSession());
    const second = renderHook(() => useAuthSession());
    await waitFor(() => {
      expect(first.result.current.state.status).toBe("unauthenticated");
    });

    act(() => {
      first.result.current.setAuthenticatedSession(session);
    });
    expect(second.result.current.state.session).toEqual(session);
    expect(window.localStorage.length).toBe(0);

    await act(async () => {
      await first.result.current.signOut();
    });
    expect(second.result.current.state.status).toBe("unauthenticated");
    expect(readSessionFromStorage()).toBeNull();
  });

  it("drops the in-memory session when another tab signs out", async () => {
    writeSessionToStorage(session);
    const { result } = renderHook(() => useAuthSession());

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: AUTH_BOUNDARY_STORAGE_KEY,
          newValue: JSON.stringify({
            reason: "signed_out",
            preserveNextPath: false,
            redirectTo: "/login?reason=signed_out",
            occurredAt: Date.now(),
          }),
        }),
      );
    });

    await waitFor(() => {
      expect(result.current.state.status).toBe("unauthenticated");
    });
    expect(result.current.boundaryMessageKey).toBe("signedOut");
    act(() => {
      result.current.clearBoundaryEvent();
    });
    expect(result.current.boundaryEvent).toBeNull();
  });
});
