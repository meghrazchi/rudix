import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const resolveChatWsAuthParam = vi.fn();

vi.mock("@/lib/chat-ws-auth", () => ({
  resolveChatWsAuthParam: () => resolveChatWsAuthParam(),
}));

import { useChatWebSocket } from "@/lib/use-chat-websocket";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((evt: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((evt: { code: number; reason: string }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(): void {}

  close(): void {}
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  resolveChatWsAuthParam.mockReset();
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useChatWebSocket auth", () => {
  it("reports ws_ticket_unavailable and reconnects with a fresh ticket", async () => {
    resolveChatWsAuthParam
      .mockRejectedValueOnce(new Error("503"))
      .mockResolvedValueOnce({ name: "ticket", value: "fresh-ticket" });
    const { result } = renderHook(() => useChatWebSocket());

    act(() => result.current.sendQuery({ question: "hi", rerank: true }));
    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toBe("ws_ticket_unavailable");
    expect(FakeWebSocket.instances).toHaveLength(0);

    act(() => result.current.sendQuery({ question: "again", rerank: true }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(resolveChatWsAuthParam).toHaveBeenCalledTimes(2);
    expect(
      new URL(FakeWebSocket.instances[0].url).searchParams.get("ticket"),
    ).toBe("fresh-ticket");
  });
});
