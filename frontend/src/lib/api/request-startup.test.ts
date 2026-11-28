import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AUTH_BOUNDARY_EVENT_NAME,
  clearSessionStorage,
  LEGACY_SESSION_STORAGE_KEY,
  readSessionFromStorage,
  writeSessionToStorage,
} from "@/lib/auth-session";
import { clearCrossTabRefreshLease } from "@/lib/auth-refresh-coordinator";
import {
  apiRequest,
  getSessionRequestContext,
  refreshAccessToken,
} from "@/lib/api/request";

// R07-09: a new tab has no session in memory and restores it from the
// HttpOnly refresh cookie.

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("startup session restore (R07-09)", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const originalEnv = { ...process.env };
  const boundaryListener = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    boundaryListener.mockReset();
    window.localStorage.clear();
    clearSessionStorage();
    clearCrossTabRefreshLease();
    vi.stubGlobal("fetch", fetchMock);
    process.env = { ...originalEnv };
    process.env.NEXT_PUBLIC_AUTH_REFRESH_URL = "http://api.test/auth/refresh";
    window.addEventListener(AUTH_BOUNDARY_EVENT_NAME, boundaryListener);
  });

  afterEach(() => {
    window.removeEventListener(AUTH_BOUNDARY_EVENT_NAME, boundaryListener);
    vi.unstubAllGlobals();
    clearSessionStorage();
    clearCrossTabRefreshLease();
    process.env = { ...originalEnv };
  });

  it("calls the refresh endpoint with credentials when memory is empty", async () => {
    fetchMock.mockResolvedValueOnce(
      json({
        access_token: "restored-token",
        user_id: "user-1",
        role: "admin",
        organization_id: "org-1",
      }),
    );

    const restored = await refreshAccessToken({ trigger: "startup" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toBe("http://api.test/auth/refresh");
    expect(init?.credentials).toBe("include");
    expect(init?.method).toBe("POST");
    expect(restored).toMatchObject({
      accessToken: "restored-token",
      userId: "user-1",
      role: "admin",
    });
    expect(getSessionRequestContext()).toEqual({
      token: "restored-token",
      organizationId: "org-1",
      userId: "user-1",
    });
  });

  it.each([401, 403])(
    "resolves unauthenticated on %s without an auth-boundary event",
    async (status) => {
      fetchMock.mockResolvedValueOnce(json({ detail: "Missing" }, status));

      await expect(refreshAccessToken({ trigger: "startup" })).resolves.toBe(
        null,
      );
      expect(boundaryListener).not.toHaveBeenCalled();
      expect(readSessionFromStorage()).toBeNull();
    },
  );

  it("propagates other failures to the caller", async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: "down" }, 503));
    await expect(
      refreshAccessToken({ trigger: "startup" }),
    ).rejects.toMatchObject({ status: 503 });
  });

  it("shares one request between concurrent startup callers", async () => {
    fetchMock.mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
      return json({ access_token: "t", user_id: "u" });
    });

    const [a, b] = await Promise.all([
      refreshAccessToken({ trigger: "startup" }),
      refreshAccessToken({ trigger: "startup" }),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(a?.accessToken).toBe("t");
    expect(b?.accessToken).toBe("t");
  });

  it("does not call the backend when refresh is not configured", async () => {
    delete process.env.NEXT_PUBLIC_AUTH_REFRESH_URL;
    await expect(refreshAccessToken({ trigger: "startup" })).resolves.toBe(
      null,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("removes the legacy localStorage session after the first refresh", async () => {
    window.localStorage.setItem(
      LEGACY_SESSION_STORAGE_KEY,
      JSON.stringify({
        userId: "user-1",
        email: null,
        role: "member",
        organizationId: "org-1",
        organizationName: null,
        accessToken: "legacy.jwt.token",
      }),
    );
    fetchMock.mockResolvedValueOnce(
      json({ access_token: "new", user_id: "u" }),
    );

    // Non-JWT legacy token: startup keeps it (no refresh), like 0.6.x.
    await expect(
      refreshAccessToken({ trigger: "startup" }),
    ).resolves.toMatchObject({ accessToken: "legacy.jwt.token" });
    expect(window.localStorage.getItem(LEGACY_SESSION_STORAGE_KEY)).not.toBe(
      null,
    );

    await refreshAccessToken({ trigger: "401" });
    expect(window.localStorage.getItem(LEGACY_SESSION_STORAGE_KEY)).toBeNull();
    expect(readSessionFromStorage()?.accessToken).toBe("new");
  });

  it("removes the legacy localStorage session after an authenticated response", async () => {
    window.localStorage.setItem(
      LEGACY_SESSION_STORAGE_KEY,
      JSON.stringify({
        userId: "user-1",
        email: null,
        role: "member",
        organizationId: null,
        organizationName: null,
        accessToken: "legacy-token",
      }),
    );
    fetchMock.mockResolvedValueOnce(json({ ok: true }));

    await apiRequest("/resource", { apiBaseUrl: "http://api.test" });

    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer legacy-token");
    expect(window.localStorage.getItem(LEGACY_SESSION_STORAGE_KEY)).toBeNull();
    expect(readSessionFromStorage()?.accessToken).toBe("legacy-token");
  });

  it("keeps the legacy session when the request is not authenticated", async () => {
    window.localStorage.setItem(LEGACY_SESSION_STORAGE_KEY, "{}");
    writeSessionToStorage({
      userId: "user-1",
      email: null,
      role: "member",
      organizationId: null,
      organizationName: null,
      accessToken: null,
    });
    fetchMock.mockResolvedValueOnce(json({ ok: true }));

    await apiRequest("/public", {
      apiBaseUrl: "http://api.test",
      attachAuth: false,
    });

    expect(window.localStorage.getItem(LEGACY_SESSION_STORAGE_KEY)).toBe("{}");
  });
});
