import { describe, expect, it } from "vitest";

import {
  observabilityRedactionConstants,
  redactObservabilityValue,
} from "@/lib/observability/redaction";

describe("redactObservabilityValue", () => {
  it("redacts sensitive keys while preserving safe identifiers", () => {
    const input = {
      request_id: "req-1",
      trace_id: "trace-1",
      token: "secret-token",
      nested: {
        question: "What is in this document?",
        message: "safe text",
      },
    };

    const redacted = redactObservabilityValue(input) as Record<string, unknown>;
    const nested = redacted.nested as Record<string, unknown>;

    expect(redacted.request_id).toBe("req-1");
    expect(redacted.trace_id).toBe("trace-1");
    expect(redacted.token).toBe(observabilityRedactionConstants.REDACTED_VALUE);
    expect(nested.question).toBe(
      observabilityRedactionConstants.REDACTED_VALUE,
    );
    expect(nested.message).toBe("safe text");
  });

  it("handles circular references safely", () => {
    const payload: Record<string, unknown> = {
      id: "node-1",
    };
    payload.self = payload;

    const redacted = redactObservabilityValue(payload) as Record<
      string,
      unknown
    >;
    expect(redacted.self).toBe(observabilityRedactionConstants.CIRCULAR_VALUE);
  });

  it("truncates very long strings", () => {
    const longString = "x".repeat(500);
    const redacted = redactObservabilityValue({
      note: longString,
    }) as Record<string, unknown>;

    expect(typeof redacted.note).toBe("string");
    expect((redacted.note as string).length).toBeLessThan(longString.length);
    expect((redacted.note as string).endsWith("…")).toBe(true);
  });
});
