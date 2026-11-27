/**
 * R05-13: the chat WebSocket drops mid-stream, the client reconnects with a
 * fresh ticket, resumes by message id and last stream sequence, discards the
 * overlapping replay, and the answer appears exactly once.
 *
 * Runs in the `chromium-chat-ws` Playwright project, whose dev server is
 * built with NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED=true. The socket is served by
 * page.routeWebSocket (contracts 4.2.6 and 4.2.7 of the 0.5.0 plan); no
 * backend runs.
 */
import {
  expect,
  test,
  type Page,
  type Route,
  type WebSocketRoute,
} from "@playwright/test";

import { dismissOnboardingChecklist } from "./support/onboarding";

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";
const SESSION_ID = "session-ws-resume";
const MESSAGE_ID = "8d2f4d0e-5b8c-4c39-9f1e-2f3a4b5c6d7e";
const FINAL_ANSWER = "Employees get 25 days of annual leave.";

const memberSession = {
  userId: "e2e-user-ws",
  email: "member@example.com",
  role: "member" as const,
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-access-token-ws",
  refreshToken: "e2e-refresh-token-ws",
};

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
};

async function fulfillJson(route: Route, body: unknown): Promise<void> {
  await route.fulfill({
    status: 200,
    headers: { "content-type": "application/json", ...CORS },
    body: JSON.stringify(body),
  });
}

async function installApiMocks(page: Page, tickets: string[]): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    if (method === "OPTIONS") {
      await route.fulfill({ status: 200, headers: CORS });
      return;
    }
    if (path === "/documents" && method === "GET") {
      await fulfillJson(route, {
        items: [
          {
            document_id: "doc-ws-1",
            filename: "Leave-Policy.pdf",
            file_type: "pdf",
            status: "indexed",
            page_count: 3,
            chunk_count: 9,
            error_message: null,
            error_details: null,
            created_at: "2026-06-04T00:00:00Z",
            updated_at: "2026-06-04T00:00:00Z",
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
      });
      return;
    }
    if (path === "/collections" && method === "GET") {
      await fulfillJson(route, { items: [], total: 0, limit: 20, offset: 0 });
      return;
    }
    if (path === "/chat/sessions" && method === "GET") {
      await fulfillJson(route, { items: [], total: 0, limit: 10, offset: 0 });
      return;
    }
    if (path === "/chat/sessions" && method === "POST") {
      await fulfillJson(route, {
        session_id: SESSION_ID,
        title: "Leave",
        message_count: 0,
        created_at: "2026-06-04T00:00:00Z",
        updated_at: "2026-06-04T00:00:00Z",
      });
      return;
    }
    if (path === `/chat/sessions/${SESSION_ID}/messages` && method === "GET") {
      await fulfillJson(route, {
        items: [],
        total: null,
        limit: 100,
        offset: 0,
        next_cursor: null,
      });
      return;
    }
    if (path === "/chat/ws-ticket" && method === "POST") {
      const ticket = `ticket-${tickets.length + 1}`;
      tickets.push(ticket);
      await fulfillJson(route, { ticket, expires_in: 30 });
      return;
    }
    await route.fallback();
  });
}

let sequence = 0;

function event(
  name: string,
  extra: {
    stream_sequence?: number;
    payload?: Record<string, unknown> | null;
    message_id?: string | null;
  } = {},
): string {
  sequence += 1;
  return JSON.stringify({
    event: name,
    request_id: "req-ws-resume",
    conversation_id: SESSION_ID,
    message_id: extra.message_id === undefined ? MESSAGE_ID : extra.message_id,
    sequence,
    stream_sequence: extra.stream_sequence ?? null,
    timestamp: new Date().toISOString(),
    payload: extra.payload ?? null,
    safe_error_code: null,
  });
}

function delta(streamSequence: number, text: string): string {
  return event("generation.delta", {
    stream_sequence: streamSequence,
    payload: { text },
  });
}

const finalResponse = {
  chat_session_id: SESSION_ID,
  message_id: MESSAGE_ID,
  answer: FINAL_ANSWER,
  confidence_score: 0.82,
  confidence_category: "high",
  confidence_explanation: null,
  not_found: false,
  citations: [],
  citation_validation_failed: false,
  debug: null,
  created_at: "2026-06-04T00:00:05Z",
};

test.describe("Chat WebSocket resume (R05-13)", () => {
  test("drops mid-stream, resumes, and shows the answer once", async ({
    page,
  }) => {
    const tickets: string[] = [];
    const sockets: WebSocketRoute[] = [];
    const socketUrls: string[] = [];
    let resumeCommand: Record<string, unknown> | null = null;
    const resumed = new Promise<void>((resolve) => {
      void page.routeWebSocket(/\/chat\/ws/, (ws) => {
        sockets.push(ws);
        socketUrls.push(ws.url());
        const index = sockets.length;
        ws.onMessage((raw) => {
          const command = JSON.parse(String(raw)) as {
            command: string;
            payload?: Record<string, unknown>;
          };
          if (index === 1 && command.command === "chat.start") {
            ws.send(event("chat.request.received", { message_id: null }));
            ws.send(
              event("generation.started", {
                stream_sequence: 1,
                payload: { mode: "live" },
              }),
            );
            ws.send(delta(2, "Employees get "));
            ws.send(delta(3, "25 days "));
            // Unexpected drop mid-stream (not a client close, retryable code).
            void ws.close({ code: 1012, reason: "service restart" });
            return;
          }
          if (index === 2 && command.command === "chat.resume") {
            resumeCommand = command;
            ws.send(
              event("chat.resumed", {
                payload: { message_id: MESSAGE_ID, replayed: 2 },
              }),
            );
            // Overlapping replay: sequence 3 was already applied.
            ws.send(delta(3, "25 days "));
            ws.send(delta(4, "of annual leave."));
            resolve();
          }
        });
      });
    });

    await installApiMocks(page, tickets);
    await page.goto("/chat");
    await page.evaluate(
      ({ key, value }) =>
        window.localStorage.setItem(key, JSON.stringify(value)),
      { key: SESSION_STORAGE_KEY, value: memberSession },
    );
    await page.goto("/chat");
    await dismissOnboardingChecklist(page);

    await page
      .getByPlaceholder(/Type a message/i)
      .fill("How many days of annual leave do employees get?");
    await page.getByRole("button", { name: /Send message/i }).click();

    await resumed;
    expect(sockets).toHaveLength(2);
    // Ticket-only handshake, a fresh ticket per connection, never a token.
    expect(new URL(socketUrls[0]).searchParams.get("ticket")).toBe("ticket-1");
    expect(new URL(socketUrls[1]).searchParams.get("ticket")).toBe("ticket-2");
    for (const url of socketUrls) {
      expect(new URL(url).searchParams.has("token")).toBe(false);
    }
    expect(resumeCommand).toEqual({
      command: "chat.resume",
      payload: { message_id: MESSAGE_ID, last_stream_sequence: 3 },
    });

    // The streamed text holds the replayed sequence 3 once, still provisional.
    const streaming = page.getByTestId("streaming-answer");
    await expect(streaming).toHaveText(FINAL_ANSWER);
    await expect(streaming).toHaveAttribute("data-stream-state", "provisional");

    const live = sockets[1];
    live.send(
      event("generation.final", {
        stream_sequence: 5,
        payload: {
          answer: FINAL_ANSWER,
          not_found: false,
          citations: [],
          confidence_score: 0.82,
          confidence_category: "high",
          citation_validation_failed: false,
        },
      }),
    );
    live.send(
      event("chat.completed", {
        stream_sequence: 6,
        payload: { response: finalResponse },
      }),
    );
    // A duplicate terminal frame must not add a second answer.
    live.send(
      event("chat.completed", {
        stream_sequence: 6,
        payload: { response: finalResponse },
      }),
    );

    await expect(page.getByTestId("streaming-answer")).toHaveCount(0);
    await expect(page.getByText(FINAL_ANSWER, { exact: true })).toHaveCount(1);
    await expect(page.locator("li[data-chat-turn]")).toHaveCount(1);
  });
});
