import { describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";
import {
  CHAT_WS_ERROR_MESSAGE_KEYS,
  getChatWsErrorMessageKey,
} from "@/lib/chat-ws-errors";

describe("getChatWsErrorMessageKey", () => {
  it("maps plan_limit_exceeded to the planLimitExceeded message", () => {
    expect(getChatWsErrorMessageKey("plan_limit_exceeded")).toBe(
      "planLimitExceeded",
    );
  });

  it("maps rate limit codes to their messages", () => {
    expect(getChatWsErrorMessageKey("rate_limit_exceeded")).toBe(
      "rateLimitExceeded",
    );
    expect(getChatWsErrorMessageKey("rate_limiter_unavailable")).toBe(
      "rateLimiterUnavailable",
    );
  });

  it("maps ws_ticket_unavailable to the wsTicketUnavailable message", () => {
    expect(getChatWsErrorMessageKey("ws_ticket_unavailable")).toBe(
      "wsTicketUnavailable",
    );
  });

  it("returns null for unknown, empty, and inherited codes", () => {
    expect(getChatWsErrorMessageKey(null)).toBeNull();
    expect(getChatWsErrorMessageKey("")).toBeNull();
    expect(getChatWsErrorMessageKey("retrieval_failed")).toBeNull();
    expect(getChatWsErrorMessageKey("toString")).toBeNull();
  });

  it("only references keys that exist in chat.page.wsErrors", () => {
    const wsErrors = en.chat.page.wsErrors as Record<string, string>;
    for (const key of Object.values(CHAT_WS_ERROR_MESSAGE_KEYS)) {
      expect(wsErrors[key]).toBeTruthy();
    }
  });
});
