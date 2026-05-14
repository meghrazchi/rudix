import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSessionStorage, writeSessionToStorage } from "@/lib/auth-session";
import { apiRequest } from "@/lib/api/request";

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

    expect(headers.get("X-Organization-ID")).toBe("0b350f69-22f0-47d9-bf6d-b3e1f7221f65");
  });
});
