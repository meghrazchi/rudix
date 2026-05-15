import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
} from "vitest";

import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import {
  clearSessionStorage,
  readSessionFromStorage,
  writeSessionToStorage,
} from "@/lib/auth-session";
import { ApiClientError } from "@/lib/api/errors";
import { apiRequest } from "@/lib/api/request";

const apiBaseUrl = "http://api.test";
const originalEnv = { ...process.env };

let refreshCallCount = 0;
let protectedCallCount = 0;
let refreshMode: "success" | "failure" | "malformed" = "success";

const server = setupServer(
  http.get(`${apiBaseUrl}/case/401`, () =>
    HttpResponse.json({ detail: "Missing bearer token" }, { status: 401 }),
  ),
  http.get(`${apiBaseUrl}/case/403`, () =>
    HttpResponse.json({ detail: "Insufficient role" }, { status: 403 }),
  ),
  http.get(`${apiBaseUrl}/case/409`, () =>
    HttpResponse.json(
      { detail: "Document is already processing" },
      { status: 409 },
    ),
  ),
  http.get(`${apiBaseUrl}/case/429`, () =>
    HttpResponse.json({ detail: "Rate limit exceeded" }, { status: 429 }),
  ),
  http.get(`${apiBaseUrl}/case/503`, () =>
    HttpResponse.json({ detail: "Service unavailable" }, { status: 503 }),
  ),
  http.get(`${apiBaseUrl}/case/protected`, ({ request }) => {
    protectedCallCount += 1;
    const authHeader = request.headers.get("authorization");
    if (authHeader === "Bearer refreshed-access-token") {
      return HttpResponse.json({ ok: true }, { status: 200 });
    }
    return HttpResponse.json({ detail: "Expired token" }, { status: 401 });
  }),
  http.post(`${apiBaseUrl}/auth/token/refresh`, async () => {
    refreshCallCount += 1;
    if (refreshMode === "failure") {
      return HttpResponse.json({ detail: "Refresh revoked" }, { status: 401 });
    }
    if (refreshMode === "malformed") {
      return HttpResponse.json({ token_type: "bearer" }, { status: 200 });
    }
    return HttpResponse.json(
      {
        access_token: "refreshed-access-token",
        refresh_token: "refreshed-refresh-token",
      },
      { status: 200 },
    );
  }),
);

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

beforeEach(() => {
  clearSessionStorage();
  refreshCallCount = 0;
  protectedCallCount = 0;
  refreshMode = "success";
  process.env = {
    ...originalEnv,
    NEXT_PUBLIC_AUTH_REFRESH_URL: `${apiBaseUrl}/auth/token/refresh`,
  };
});

afterEach(() => {
  server.resetHandlers();
  clearSessionStorage();
  process.env = { ...originalEnv };
});

afterAll(() => {
  server.close();
});

describe("apiRequest status normalization", () => {
  it.each([
    {
      path: "/case/401",
      expectedStatus: 401,
      expectedCode: "unauthorized",
      expectedUserMessage: "Your session is not valid.",
      expectedRetryable: false,
    },
    {
      path: "/case/403",
      expectedStatus: 403,
      expectedCode: "forbidden",
      expectedUserMessage: "You do not have permission for this action.",
      expectedRetryable: false,
    },
    {
      path: "/case/409",
      expectedStatus: 409,
      expectedCode: "conflict",
      expectedUserMessage: "The request conflicts with current state.",
      expectedRetryable: false,
    },
    {
      path: "/case/429",
      expectedStatus: 429,
      expectedCode: "rate_limited",
      expectedUserMessage: "Too many requests were sent.",
      expectedRetryable: true,
    },
    {
      path: "/case/503",
      expectedStatus: 503,
      expectedCode: "service_unavailable",
      expectedUserMessage: "The service is temporarily unavailable.",
      expectedRetryable: true,
    },
  ])(
    "maps $path",
    async ({
      path,
      expectedStatus,
      expectedCode,
      expectedUserMessage,
      expectedRetryable,
    }) => {
      await expect(
        apiRequest(path, {
          apiBaseUrl,
          retry: false,
          attachAuth: false,
          attachOrganizationId: false,
          skipAuthRefresh: true,
        }),
      ).rejects.toMatchObject({
        status: expectedStatus,
        code: expectedCode,
        userMessage: expectedUserMessage,
        retryable: expectedRetryable,
      } satisfies Partial<ApiClientError>);
    },
  );
});

describe("apiRequest refresh integration", () => {
  it("refreshes and retries protected safe requests", async () => {
    writeSessionToStorage({
      userId: "user-1",
      email: "user@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "expired-access-token",
      refreshToken: "refresh-token-1",
    });

    const result = await apiRequest<{ ok: boolean }>("/case/protected", {
      apiBaseUrl,
      method: "GET",
      retry: false,
    });

    expect(result.ok).toBe(true);
    expect(refreshCallCount).toBe(1);
    expect(protectedCallCount).toBe(2);

    const session = readSessionFromStorage();
    expect(session?.accessToken).toBe("refreshed-access-token");
    expect(session?.refreshToken).toBe("refreshed-refresh-token");
  });

  it("clears session when refresh fails", async () => {
    refreshMode = "failure";
    writeSessionToStorage({
      userId: "user-1",
      email: "user@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "expired-access-token",
      refreshToken: "refresh-token-1",
    });

    await expect(
      apiRequest("/case/protected", {
        apiBaseUrl,
        method: "GET",
        retry: false,
      }),
    ).rejects.toMatchObject({
      status: 401,
      code: "unauthorized",
    } satisfies Partial<ApiClientError>);

    expect(readSessionFromStorage()).toBeNull();
  });

  it("treats malformed refresh response as invalid session", async () => {
    refreshMode = "malformed";
    writeSessionToStorage({
      userId: "user-1",
      email: "user@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "expired-access-token",
      refreshToken: "refresh-token-1",
    });

    await expect(
      apiRequest("/case/protected", {
        apiBaseUrl,
        method: "GET",
        retry: false,
      }),
    ).rejects.toMatchObject({
      status: 401,
      code: "session_invalid",
    } satisfies Partial<ApiClientError>);

    expect(readSessionFromStorage()).toBeNull();
  });
});
