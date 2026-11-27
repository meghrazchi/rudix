import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { http, HttpResponse } from "msw";

import { clearSessionStorage, writeSessionToStorage } from "@/lib/auth-session";
import {
  ChatWsAuthUnavailableError,
  resolveChatWsAuthParam,
} from "@/lib/chat-ws-auth";
import { createMockApiServer } from "@/test/msw/server";

const server = createMockApiServer();

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  clearSessionStorage();
});

afterAll(() => {
  server.close();
});

function ticketStatus(status: number) {
  server.use(
    http.post("*/chat/ws-ticket", () =>
      HttpResponse.json({ detail: "x" }, { status }),
    ),
  );
}

describe("resolveChatWsAuthParam", () => {
  it("returns a ticket when the endpoint succeeds", async () => {
    await expect(resolveChatWsAuthParam()).resolves.toEqual({
      name: "ticket",
      value: "msw-ws-ticket",
    });
  });

  it.each([404, 405])(
    "throws without a token fallback when the endpoint returns %i",
    async (status) => {
      writeSessionToStorage({
        userId: "user-1",
        email: null,
        role: "member",
        organizationId: "org-1",
        organizationName: null,
        accessToken: "legacy-access-token",
      });
      ticketStatus(status);
      const result = resolveChatWsAuthParam();
      await expect(result).rejects.toBeInstanceOf(ChatWsAuthUnavailableError);
      await expect(result).rejects.not.toHaveProperty(
        "value",
        "legacy-access-token",
      );
    },
  );

  it.each([503, 429])(
    "throws without a token fallback on %i",
    async (status) => {
      ticketStatus(status);
      await expect(resolveChatWsAuthParam()).rejects.toBeInstanceOf(
        ChatWsAuthUnavailableError,
      );
    },
  );

  it("throws on a network error", async () => {
    server.use(http.post("*/chat/ws-ticket", () => HttpResponse.error()));
    await expect(resolveChatWsAuthParam()).rejects.toBeInstanceOf(
      ChatWsAuthUnavailableError,
    );
  });

  it("throws on a malformed ticket response", async () => {
    server.use(
      http.post("*/chat/ws-ticket", () =>
        HttpResponse.json({ expires_in: 30 }),
      ),
    );
    await expect(resolveChatWsAuthParam()).rejects.toBeInstanceOf(
      ChatWsAuthUnavailableError,
    );
  });
});
