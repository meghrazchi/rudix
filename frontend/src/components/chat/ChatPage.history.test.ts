import { describe, expect, it } from "vitest";

import { toTurnResponseFromHistoryMessage } from "@/components/chat/ChatPage";

describe("toTurnResponseFromHistoryMessage", () => {
  it("maps historical agreement and conflict fields without throwing", () => {
    const response = toTurnResponseFromHistoryMessage({
      message_id: "assistant-1",
      role: "assistant",
      content: "The policy date is May 2026.",
      confidence_score: 0.82,
      confidence_category: "high",
      citations: [],
      created_at: "2026-05-14T10:00:03Z",
      agreement_level: "conflicting",
      conflict_detected: true,
      conflict_summary: "Sources disagree on the policy date.",
      conflicting_document_ids: ["doc-a", "doc-b"],
      preferred_document_ids: ["doc-a"],
      conflict_pairs: [
        {
          document_id_a: "doc-a",
          document_id_b: "doc-b",
          topic: "policy date",
          severity: "medium",
        },
      ],
    } as never);

    expect(response.agreement_level).toBe("conflicting");
    expect(response.conflict_detected).toBe(true);
    expect(response.conflict_summary).toBe(
      "Sources disagree on the policy date.",
    );
    expect(response.conflicting_document_ids).toEqual(["doc-a", "doc-b"]);
    expect(response.preferred_document_ids).toEqual(["doc-a"]);
    expect(response.conflict_pairs).toHaveLength(1);
  });
});
