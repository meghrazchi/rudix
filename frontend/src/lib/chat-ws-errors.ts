/**
 * Maps chat WebSocket `safe_error_code` values to translation keys under
 * `chat.page.wsErrors`. Codes without an entry fall back to the generic
 * API error message.
 */
export const CHAT_WS_ERROR_MESSAGE_KEYS: Readonly<Record<string, string>> = {
  plan_limit_exceeded: "planLimitExceeded",
  provider_busy: "providerBusy",
  rate_limit_exceeded: "rateLimitExceeded",
  rate_limiter_unavailable: "rateLimiterUnavailable",
  resume_unavailable: "resumeUnavailable",
  connection_lost: "connectionLost",
  ws_ticket_unavailable: "wsTicketUnavailable",
};

export function getChatWsErrorMessageKey(code: string | null): string | null {
  if (!code) return null;
  return Object.prototype.hasOwnProperty.call(CHAT_WS_ERROR_MESSAGE_KEYS, code)
    ? CHAT_WS_ERROR_MESSAGE_KEYS[code]
    : null;
}
