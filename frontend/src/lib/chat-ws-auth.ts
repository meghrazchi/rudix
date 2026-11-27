/**
 * Resolves the query parameter used to authenticate the chat WebSocket
 * handshake (R02-10, R05-13).
 *
 * The browser WebSocket API cannot send an Authorization header, so the client
 * asks `POST /chat/ws-ticket` for a single-use ticket and opens
 * `/chat/ws?ticket=…`. The access token never appears in a URL.
 *
 * Ticket only: since 0.5.0 there is no `?token=` fallback. Every failure,
 * including a backend without the ticket endpoint (404 or 405), a 503, a 429
 * or a network error, throws `ChatWsAuthUnavailableError`, which the chat UI
 * shows as an error state.
 */

import { createChatWsTicket } from "@/lib/api/chat";

export type ChatWsAuthParam = { name: "ticket"; value: string };

export class ChatWsAuthUnavailableError extends Error {
  readonly reason: unknown;

  constructor(reason: unknown) {
    super("Chat WebSocket ticket is unavailable");
    this.name = "ChatWsAuthUnavailableError";
    this.reason = reason;
  }
}

export async function resolveChatWsAuthParam(): Promise<ChatWsAuthParam> {
  let ticket: unknown;
  try {
    ({ ticket } = await createChatWsTicket());
  } catch (error) {
    throw new ChatWsAuthUnavailableError(error);
  }
  if (typeof ticket !== "string" || !ticket) {
    throw new ChatWsAuthUnavailableError("malformed_ticket_response");
  }
  return { name: "ticket", value: ticket };
}
