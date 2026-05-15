import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearSessionStorage,
  readSessionFromStorage,
  writeSessionToStorage,
} from "@/lib/auth-session";
import { ApiClientError } from "@/lib/api/errors";
import { apiRequest, getJwtExpirationTimeMs } from "@/lib/api/request";

function createJwt(expSeconds: number): string {
  const header = { alg: "HS256", typ: "JWT" };
  const payload = { sub: "user-1", exp: expSeconds };
  const encode = (value: object) =>
    btoa(JSON.stringify(value))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/g, "");

  return `${encode(header)}.${encode(payload)}.signature`;
}

describe("apiRequest header attachment", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const originalEnv = { ...process.env };

  beforeEach(() => {
    fetchMock.mockReset();
    clearSessionStorage();
    vi.stubGlobal("fetch", fetchMock);
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    clearSessionStorage();
    process.env = { ...originalEnv };
  });

  it("attaches bearer token and organization id from session storage", async () => {
    process.env.NEXT_PUBLIC_AUTH_PROVIDER = "clerk";
    writeSessionToStorage({
      userId: "user-1",
      email: "user@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-from-session",
    });

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await apiRequest<{ ok: boolean }>("/health", {
      apiBaseUrl: "http://api.test",
      retry: false,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(init?.headers);

    expect(headers.get("Authorization")).toBe("Bearer token-from-session");
    expect(headers.get("X-Organization-ID")).toBe("org-1");
    expect(headers.get("X-Request-ID")).toBeTruthy();
  });

  it("allows explicit request auth context to override session values", async () => {
    process.env.NEXT_PUBLIC_AUTH_PROVIDER = "clerk";
    writeSessionToStorage({
      userId: "user-1",
      email: "user@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-from-session",
    });

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await apiRequest<{ ok: boolean }>("/health", {
      apiBaseUrl: "http://api.test",
      token: "token-explicit",
      organizationId: "org-explicit",
      retry: false,
    });

    const [, init] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(init?.headers);

    expect(headers.get("Authorization")).toBe("Bearer token-explicit");
    expect(headers.get("X-Organization-ID")).toBe("org-explicit");
  });

  it("does not attach invalid organization slug header for app auth", async () => {
    process.env.NEXT_PUBLIC_AUTH_PROVIDER = "app";
    writeSessionToStorage({
      userId: "seed-user-001",
      email: "user@example.com",
      role: "member",
      organizationId: "org-jupar",
      organizationName: "Jupar",
      accessToken: "token-from-session",
    });

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await apiRequest<{ ok: boolean }>("/health", {
      apiBaseUrl: "http://api.test",
      retry: false,
    });

    const [, init] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(init?.headers);

    expect(headers.get("Authorization")).toBe("Bearer token-from-session");
    expect(headers.get("X-Organization-ID")).toBeNull();
  });

  it("attaches organization header for app auth when organization id is UUID", async () => {
    process.env.NEXT_PUBLIC_AUTH_PROVIDER = "app";
    writeSessionToStorage({
      userId: "seed-user-001",
      email: "user@example.com",
      role: "member",
      organizationId: "0b350f69-22f0-47d9-bf6d-b3e1f7221f65",
      organizationName: "Jupar",
      accessToken: "token-from-session",
    });

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await apiRequest<{ ok: boolean }>("/health", {
      apiBaseUrl: "http://api.test",
      retry: false,
    });

    const [, init] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(init?.headers);

    expect(headers.get("X-Organization-ID")).toBe(
      "0b350f69-22f0-47d9-bf6d-b3e1f7221f65",
    );
  });

  it("extracts JWT expiration from access token payload", () => {
    const expSeconds = 1_893_456_000;
    const token = createJwt(expSeconds);
    expect(getJwtExpirationTimeMs(token)).toBe(expSeconds * 1_000);
  });
});

describe("apiRequest refresh handling", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const originalEnv = { ...process.env };

  beforeEach(() => {
    fetchMock.mockReset();
    clearSessionStorage();
    vi.stubGlobal("fetch", fetchMock);
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    clearSessionStorage();
    process.env = { ...originalEnv };
  });

  it("uses single-flight refresh for concurrent 401 responses and retries safe requests", async () => {
    process.env.NEXT_PUBLIC_AUTH_REFRESH_URL = "http://api.test/auth/refresh";

    writeSessionToStorage({
      userId: "user-1",
      email: "user@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "old-token",
      refreshToken: "refresh-token",
    });

    let refreshCalls = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        refreshCalls += 1;
        await new Promise((resolve) => setTimeout(resolve, 10));
        return new Response(
          JSON.stringify({
            access_token: "new-token",
            refresh_token: "refresh-token-2",
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        );
      }

      if (url.endsWith("/resource")) {
        const authHeader = new Headers(init?.headers).get("Authorization");
        if (authHeader === "Bearer new-token") {
          return new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        return new Response(JSON.stringify({ detail: "Expired token" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }

      return new Response("not found", { status: 404 });
    });

    const [first, second] = await Promise.all([
      apiRequest<{ ok: boolean }>("/resource", {
        apiBaseUrl: "http://api.test",
        retry: false,
      }),
      apiRequest<{ ok: boolean }>("/resource", {
        apiBaseUrl: "http://api.test",
        retry: false,
      }),
    ]);

    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    expect(refreshCalls).toBe(1);

    const session = readSessionFromStorage();
    expect(session?.accessToken).toBe("new-token");
    expect(session?.refreshToken).toBe("refresh-token-2");
  });

  it("refreshes but does not replay unsafe mutations by default", async () => {
    process.env.NEXT_PUBLIC_AUTH_REFRESH_URL = "http://api.test/auth/refresh";

    writeSessionToStorage({
      userId: "user-1",
      email: "user@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "old-token",
      refreshToken: "refresh-token",
    });

    let mutationCalls = 0;
    let refreshCalls = 0;

    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        refreshCalls += 1;
        return new Response(
          JSON.stringify({
            access_token: "new-token",
            refresh_token: "refresh-token-2",
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        );
      }

      if (url.endsWith("/mutation")) {
        mutationCalls += 1;
        return new Response(JSON.stringify({ detail: "Expired token" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }

      return new Response("not found", { status: 404 });
    });

    await expect(
      apiRequest("/mutation", {
        apiBaseUrl: "http://api.test",
        method: "POST",
        json: { operation: "run" },
        retry: false,
      }),
    ).rejects.toMatchObject({
      code: "session_refresh_required_retry",
      userMessage: "Your session was refreshed.",
    } satisfies Partial<ApiClientError>);

    expect(refreshCalls).toBe(1);
    expect(mutationCalls).toBe(1);
    expect(readSessionFromStorage()?.accessToken).toBe("new-token");
  });
});
