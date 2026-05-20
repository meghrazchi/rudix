import { describe, expect, it } from "vitest";

import {
  extractRequestIdFromError,
  getSupportAction,
  isForbiddenError,
  sanitizeRequestId,
} from "@/lib/forbidden";
import { ApiClientError } from "@/lib/api/errors";

describe("forbidden utilities", () => {
  it("sanitizes request IDs", () => {
    expect(sanitizeRequestId("req-123_ABC")).toBe("req-123_ABC");
    expect(sanitizeRequestId("  req:abc.123  ")).toBe("req:abc.123");
    expect(sanitizeRequestId("")).toBeNull();
    expect(sanitizeRequestId("invalid request id")).toBeNull();
  });

  it("detects forbidden API errors", () => {
    const forbiddenError = new ApiClientError({
      status: 403,
      code: "forbidden",
      message: "Forbidden",
      details: null,
      requestId: "req-403",
      userMessage: "You do not have permission for this action.",
      actionMessage: "Switch organization or contact an administrator.",
      retryable: false,
    });

    const conflictError = new ApiClientError({
      status: 409,
      code: "conflict",
      message: "Conflict",
      details: null,
      requestId: "req-409",
      userMessage: "Conflict.",
      actionMessage: "Refresh.",
      retryable: false,
    });

    expect(isForbiddenError(forbiddenError)).toBe(true);
    expect(isForbiddenError(conflictError)).toBe(false);
    expect(isForbiddenError({ status: 403 })).toBe(true);
    expect(isForbiddenError({ status: 500 })).toBe(false);
  });

  it("extracts safe request ID from known error shapes", () => {
    const forbiddenError = new ApiClientError({
      status: 403,
      code: "forbidden",
      message: "Forbidden",
      details: null,
      requestId: "req-403",
      userMessage: "You do not have permission for this action.",
      actionMessage: "Switch organization or contact an administrator.",
      retryable: false,
    });

    expect(extractRequestIdFromError(forbiddenError)).toBe("req-403");
    expect(
      extractRequestIdFromError({ status: 403, requestId: "trace-1" }),
    ).toBe("trace-1");
    expect(
      extractRequestIdFromError({ status: 403, request_id: "trace-2" }),
    ).toBe("trace-2");
    expect(
      extractRequestIdFromError({ status: 403, requestId: "bad id" }),
    ).toBeNull();
  });

  it("resolves support action from environment config", () => {
    const originalEnv = { ...process.env };
    process.env = { ...originalEnv };

    delete process.env.NEXT_PUBLIC_SUPPORT_URL;
    delete process.env.NEXT_PUBLIC_SUPPORT_EMAIL;
    expect(getSupportAction()).toBeNull();

    process.env.NEXT_PUBLIC_SUPPORT_EMAIL = "support@example.com";
    expect(getSupportAction()).toEqual({
      href: "mailto:support@example.com",
      label: "Email support",
    });

    process.env.NEXT_PUBLIC_SUPPORT_URL = "https://support.example.com";
    expect(getSupportAction()).toEqual({
      href: "https://support.example.com",
      label: "Contact support",
    });

    process.env = originalEnv;
  });
});
