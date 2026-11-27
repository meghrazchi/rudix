import { describe, expect, it } from "vitest";

import {
  buildHistoryPage,
  toConversationOrder,
} from "@/components/chat/chat-history";
import type { ChatSessionMessageResponse } from "@/lib/api/chat";

function message(
  id: string,
  role: "user" | "assistant",
  createdAt: string,
): ChatSessionMessageResponse {
  return {
    message_id: id,
    role,
    content: `${role} ${id}`,
    confidence_score: role === "assistant" ? 0.9 : null,
    confidence_category: role === "assistant" ? "high" : null,
    citations: [],
    created_at: createdAt,
  } as ChatSessionMessageResponse;
}

const u1 = message("u1", "user", "2026-05-14T10:00:00Z");
const a1 = message("a1", "assistant", "2026-05-14T10:00:01Z");
const u2 = message("u2", "user", "2026-05-14T10:01:00Z");
const a2 = message("a2", "assistant", "2026-05-14T10:01:01Z");
const u3 = message("u3", "user", "2026-05-14T10:02:00Z");
const a3 = message("a3", "assistant", "2026-05-14T10:02:01Z");

describe("newest-first history pages (R05-11)", () => {
  it("puts a desc page back into conversation order", () => {
    expect(
      toConversationOrder([a2, u2, a1, u1]).map((m) => m.message_id),
    ).toEqual(["u1", "a1", "u2", "a2"]);
    // An ascending page (older servers, mocks) also comes out right.
    expect(toConversationOrder([u1, a1, u2]).map((m) => m.message_id)).toEqual([
      "u1",
      "a1",
      "u2",
    ]);
  });

  it("orders the question first within one timestamp", () => {
    const same = "2026-05-14T10:00:00Z";
    const q = message("q", "user", same);
    const a = message("a", "assistant", same);
    const odd = { ...message("x", "assistant", "not-a-date"), role: "system" };
    expect(toConversationOrder([a, q]).map((m) => m.message_id)).toEqual([
      "q",
      "a",
    ]);
    expect(
      toConversationOrder([odd, a, q] as ChatSessionMessageResponse[]).map(
        (m) => m.message_id,
      ),
    ).toEqual(["x", "q", "a"]);
  });

  it("holds back an answer whose question is on the next older page", () => {
    // Newest page of 3 (desc): a3, u3, a2 -> a2's question u2 is older.
    const first = buildHistoryPage([a3, u3, a2], "cursor-1");
    expect(first.turns.map((t) => t.response.message_id)).toEqual(["a3"]);
    expect(first.state).toEqual({ nextCursor: "cursor-1", held: [a2] });

    const older = buildHistoryPage([u2, a1, u1], null, first.state.held);
    expect(older.turns.map((t) => [t.question, t.response.message_id])).toEqual(
      [
        ["user u1", "a1"],
        ["user u2", "a2"],
      ],
    );
    expect(older.state).toEqual({ nextCursor: null, held: [] });
  });

  it("returns every turn when the page is the oldest", () => {
    const only = buildHistoryPage([a1, u1], undefined);
    expect(only.turns).toHaveLength(1);
    expect(only.state.nextCursor).toBeNull();
  });
});
