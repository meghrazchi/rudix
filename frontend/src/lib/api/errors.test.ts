import { describe, expect, it } from "vitest";

import {
  ApiClientError,
  normalizeApiError,
  normalizeBackendError,
} from "@/lib/api/errors";

describe("normalizeBackendError", () => {
  it("extracts message and code from nested detail envelopes", () => {
    const normalized = normalizeBackendError({
      detail: {
        code: "chat_session_not_found",
        message: "Chat session not found",
      },
    });

    expect(normalized.code).toBe("chat_session_not_found");
    expect(normalized.message).toBe("Chat session not found");
  });

  it("falls back to plain string payloads", () => {
    const normalized = normalizeBackendError("Document not found");

    expect(normalized.code).toBeNull();
    expect(normalized.message).toBe("Document not found");
  });
});

describe("normalizeApiError", () => {
  it("maps status 409 to actionable user messaging", () => {
    const error = normalizeApiError({
      status: 409,
      payload: { detail: "Document is currently being deleted" },
      requestId: "req-409",
    });

    expect(error).toBeInstanceOf(ApiClientError);
    expect(error.status).toBe(409);
    expect(error.code).toBe("conflict");
    expect(error.message).toBe("Document is currently being deleted");
    expect(error.userMessage).toBe("The request conflicts with current state.");
    expect(error.actionMessage).toBe("Refresh the page and try again.");
    expect(error.requestId).toBe("req-409");
    expect(error.retryable).toBe(false);
  });

  it("extracts request id from payload when header request id is unavailable", () => {
    const error = normalizeApiError({
      status: 403,
      payload: {
        detail: {
          message: "Insufficient role",
          request_id: "req-403-body",
        },
      },
    });

    expect(error.requestId).toBe("req-403-body");
  });

  it("maps plan limit errors to upgrade guidance", () => {
    const error = normalizeApiError({
      status: 403,
      payload: {
        detail: {
          code: "plan_limit_exceeded",
          message: "Storage usage would exceed the plan limit (101/100).",
        },
      },
    });

    expect(error.code).toBe("plan_limit_exceeded");
    expect(error.userMessage).toBe("Your plan limit has been reached.");
    expect(error.actionMessage).toBe(
      "Upgrade your plan or reduce usage to continue.",
    );
  });
});
