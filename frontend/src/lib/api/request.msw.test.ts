import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { ApiClientError } from "@/lib/api/errors";
import { apiRequest } from "@/lib/api/request";

const apiBaseUrl = "http://api.test";

const server = setupServer(
  http.get(`${apiBaseUrl}/case/401`, () => HttpResponse.json({ detail: "Missing bearer token" }, { status: 401 })),
  http.get(`${apiBaseUrl}/case/403`, () => HttpResponse.json({ detail: "Insufficient role" }, { status: 403 })),
  http.get(`${apiBaseUrl}/case/409`, () => HttpResponse.json({ detail: "Document is already processing" }, { status: 409 })),
  http.get(`${apiBaseUrl}/case/429`, () => HttpResponse.json({ detail: "Rate limit exceeded" }, { status: 429 })),
  http.get(`${apiBaseUrl}/case/503`, () => HttpResponse.json({ detail: "Service unavailable" }, { status: 503 })),
);

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
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
    async ({ path, expectedStatus, expectedCode, expectedUserMessage, expectedRetryable }) => {
      await expect(
        apiRequest(path, {
          apiBaseUrl,
          retry: false,
          attachAuth: false,
          attachOrganizationId: false,
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
