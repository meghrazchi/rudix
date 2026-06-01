import { describe, expect, it } from "vitest";

import type { AuditLogListItemResponse } from "@/lib/api/admin-usage";
import {
  formatAuditStatusLabel,
  getAuditResultFilter,
  getAuditStatusCode,
  getAuditStatusFilter,
  matchesAuditResultFilter,
  matchesAuditStatusFilter,
  sanitizeAuditMetadata,
} from "@/lib/admin-audit";

function event(
  metadata: Record<string, unknown>,
  result: "success" | "failure" | "unknown" = "unknown",
): AuditLogListItemResponse {
  return {
    audit_log_id: "audit-1",
    organization_id: "org-1",
    user_id: "user-1",
    action: "chat.query.completed",
    resource_type: "chat_session",
    resource_id: "session-1",
    request_id: "req-1",
    result,
    metadata,
    created_at: "2026-05-17T10:00:00Z",
  };
}

describe("admin-audit utils", () => {
  it("redacts sensitive metadata keys", () => {
    const sanitized = sanitizeAuditMetadata({
      status_code: 200,
      authorization: "Bearer secret-token",
      nested: {
        api_key: "value",
      },
    });

    expect(sanitized.authorization).toBe("[redacted]");
    expect((sanitized.nested as Record<string, unknown>).api_key).toBe(
      "[redacted]",
    );
  });

  it("classifies audit status code categories", () => {
    expect(getAuditStatusCode({ status_code: 200 })).toBe(200);
    expect(getAuditStatusCode({ http_status: "404" })).toBe(404);
    expect(getAuditStatusFilter(event({ status_code: 200 }))).toBe("success");
    expect(getAuditStatusFilter(event({ status_code: 404 }))).toBe(
      "client_error",
    );
    expect(getAuditStatusFilter(event({ status_code: 503 }))).toBe(
      "server_error",
    );
    expect(getAuditStatusFilter(event({}))).toBe("unknown");
  });

  it("matches status filters and labels", () => {
    const sample = event({ status_code: 500 });
    expect(matchesAuditStatusFilter(sample, "all")).toBe(true);
    expect(matchesAuditStatusFilter(sample, "server_error")).toBe(true);
    expect(matchesAuditStatusFilter(sample, "success")).toBe(false);
    expect(formatAuditStatusLabel("client_error")).toBe("Client error");
  });

  it("matches result filters", () => {
    const success = event({ status_code: 200 }, "success");
    const failure = event({ status_code: 503 }, "failure");
    const unknown = event({}, "unknown");

    expect(getAuditResultFilter(success)).toBe("success");
    expect(getAuditResultFilter(failure)).toBe("failure");
    expect(getAuditResultFilter(unknown)).toBe("unknown");
    expect(matchesAuditResultFilter(success, "success")).toBe(true);
    expect(matchesAuditResultFilter(success, "failure")).toBe(false);
    expect(matchesAuditResultFilter(unknown, "all")).toBe(true);
  });
});
