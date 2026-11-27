/**
 * Newest-first chat history pages (R05-11).
 *
 * `GET /chat/sessions/{id}/messages?order=desc` returns the newest messages
 * first. The thread renders oldest at the top, so each page is put back into
 * conversation order. A page boundary can split a question from its answer:
 * answers at the start of a page whose question is on the next (older) page
 * are held back and joined to that page when it loads.
 */

import type { ChatSessionMessageResponse } from "@/lib/api/chat";

import { buildTurnsFromSessionMessages } from "@/components/chat/chat-turns";
import type { ChatTurn } from "@/components/chat/chat-types";

export type HistoryPageState = {
  /** Cursor for the next older page, or null when the oldest page is loaded. */
  nextCursor: string | null;
  /** Messages held back until their question arrives with the older page. */
  held: ChatSessionMessageResponse[];
};

const ROLE_RANK: Record<string, number> = { user: 0, assistant: 1 };

function timestampOf(message: ChatSessionMessageResponse): number {
  const parsed = Date.parse(message.created_at);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * Oldest first. A `desc` page is reversed, then stably sorted by the server's
 * key (created_at, user before assistant), so a page already in ascending
 * order also comes out right.
 */
export function toConversationOrder(
  items: readonly ChatSessionMessageResponse[],
): ChatSessionMessageResponse[] {
  return [...items].reverse().sort((a, b) => {
    const byTime = timestampOf(a) - timestampOf(b);
    if (byTime !== 0) return byTime;
    return (ROLE_RANK[a.role] ?? 2) - (ROLE_RANK[b.role] ?? 2);
  });
}

/**
 * Turns for one newest-first page. `carried` are the messages held back from
 * the newer page; they follow this page in time.
 */
export function buildHistoryPage(
  items: readonly ChatSessionMessageResponse[],
  nextCursor: string | null | undefined,
  carried: readonly ChatSessionMessageResponse[] = [],
): { turns: ChatTurn[]; state: HistoryPageState } {
  const ordered = [...toConversationOrder(items), ...carried];
  const cursor = nextCursor ?? null;
  if (cursor === null) {
    return {
      turns: buildTurnsFromSessionMessages(ordered),
      state: { nextCursor: null, held: [] },
    };
  }
  let firstQuestion = 0;
  while (
    firstQuestion < ordered.length &&
    ordered[firstQuestion].role !== "user"
  ) {
    firstQuestion += 1;
  }
  return {
    turns: buildTurnsFromSessionMessages(ordered.slice(firstQuestion)),
    state: { nextCursor: cursor, held: ordered.slice(0, firstQuestion) },
  };
}
