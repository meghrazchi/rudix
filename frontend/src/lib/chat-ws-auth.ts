/**
 * Resolves the query parameter used to authenticate the chat WebSocket
 * handshake (R02-10).
 *
 * The browser WebSocket API cannot send an Authorization header, so the client
 * asks `POST /chat/ws-ticket` for a single-use ticket and opens
 * `/chat/ws?ticket=…`. The access token never appears in a URL.
 *
 * Fallback: only a backend that predates the ticket endpoint (404 or 405) gets
 * the legacy `?token=` handshake, which that backend still accepts by default
 * in 0.2.0. Remove this fallback together with the query token in 0.5.0.
 * Every other failure (503, 429, network) throws `ChatWsAuthUnavailableError`;
 * there is no silent downgrade to the query token.
 */

import { createChatWsTicket } from "@/lib/api/chat";
import { ApiClientError } from "@/lib/api/errors";
import { getSessionRequestContext } from "@/lib/api/request";

export type ChatWsAuthParam = { name: "ticket" | "token"; value: string };

export class ChatWsAuthUnavailableError extends Error {
  readonly reason: unknown;

  constructor(reason: unknown) {
    super("Chat WebSocket ticket is unavailable");
    this.name = "ChatWsAuthUnavailableError";
    this.reason = reason;
  }
}

const LEGACY_BACKEND_STATUSES = new Set([404, 405]);

export async function resolveChatWsAuthParam(): Promise<ChatWsAuthParam> {
  let ticket: unknown;
  try {
    ({ ticket } = await createChatWsTicket());
  } catch (error) {
    if (
      error instanceof ApiClientError &&
      LEGACY_BACKEND_STATUSES.has(error.status)
    ) {
      // TODO(0.5.0): remove with the ?token= handshake.
      return { name: "token", value: getSessionRequestContext().token ?? "" };
    }
    throw new ChatWsAuthUnavailableError(error);
  }
  if (typeof ticket !== "string" || !ticket) {
    throw new ChatWsAuthUnavailableError("malformed_ticket_response");
  }
  return { name: "ticket", value: ticket };
}
