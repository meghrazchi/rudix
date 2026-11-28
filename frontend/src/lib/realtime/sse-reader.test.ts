import { describe, expect, it } from "vitest";

import { readSseFrames, SseParser } from "@/lib/realtime/sse-reader";
import { parseRealtimeEvent } from "@/lib/realtime/types";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

async function collect(chunks: string[]) {
  const frames = [];
  for await (const frame of readSseFrames(streamOf(chunks))) {
    frames.push(frame);
  }
  return frames;
}

describe("SseParser", () => {
  it("parses id, event, data, and comments", () => {
    const parser = new SseParser();
    expect(
      parser.push(
        ': keep-alive\n\nid: 7\nevent: document.status\ndata: {"a":1}\n\n',
      ),
    ).toEqual([
      { kind: "comment", text: "keep-alive" },
      { kind: "event", id: "7", event: "document.status", data: '{"a":1}' },
    ]);
  });

  it("joins multi-line data and defaults the event name", () => {
    const parser = new SseParser();
    expect(parser.push("data: one\ndata:two\ndata\n\n")).toEqual([
      { kind: "event", id: null, event: "message", data: "one\ntwo\n" },
    ]);
  });

  it("accepts CRLF and lone CR line endings, also split across chunks", () => {
    const parser = new SseParser();
    expect(parser.push("id: 1\r\nevent: x\r\ndata: a\r")).toEqual([]);
    expect(parser.push("\n\r\n")).toEqual([
      { kind: "event", id: "1", event: "x", data: "a" },
    ]);
    expect(parser.push("data: b\r\r")).toEqual([
      { kind: "event", id: null, event: "message", data: "b" },
    ]);
  });

  it("does not dispatch events without data and ignores unknown fields", () => {
    const parser = new SseParser();
    expect(parser.push("event: lonely\nretry: 10\nfoo: bar\n\n")).toEqual([]);
    expect(parser.push("id: a\u0000b\ndata: x\n\n")).toEqual([
      { kind: "event", id: null, event: "message", data: "x" },
    ]);
  });

  it("keeps a partial line until the next chunk", () => {
    const parser = new SseParser();
    expect(parser.push("data: hel")).toEqual([]);
    expect(parser.push("lo\n\n")).toEqual([
      { kind: "event", id: null, event: "message", data: "hello" },
    ]);
  });
});

describe("readSseFrames", () => {
  it("decodes a body split mid-frame", async () => {
    const frames = await collect(["id: 3\nevent: incident\nda", "ta: {}\n\n"]);
    expect(frames).toEqual([
      { kind: "event", id: "3", event: "incident", data: "{}" },
    ]);
  });
});

describe("parseRealtimeEvent", () => {
  const envelope = {
    type: "document.status",
    organization_id: "org-1",
    occurred_at: "2026-11-28T00:00:00Z",
    payload: { document_id: "d1", status: "indexed", filename: "x.pdf" },
  };

  it("keeps whitelisted payload keys only", () => {
    expect(
      parseRealtimeEvent("document.status", JSON.stringify(envelope)),
    ).toEqual({
      ...envelope,
      payload: { document_id: "d1", status: "indexed" },
    });
  });

  it("rejects malformed or mismatched frames", () => {
    expect(parseRealtimeEvent("document.status", "not json")).toBeNull();
    expect(parseRealtimeEvent("incident", JSON.stringify(envelope))).toBeNull();
    expect(
      parseRealtimeEvent(
        "chat.message",
        JSON.stringify({ ...envelope, type: "chat.message" }),
      ),
    ).toBeNull();
    expect(
      parseRealtimeEvent(
        "document.status",
        JSON.stringify({ ...envelope, payload: { document_id: 1 } }),
      ),
    ).toBeNull();
    expect(
      parseRealtimeEvent(
        "document.status",
        JSON.stringify({ ...envelope, organization_id: 5 }),
      ),
    ).toBeNull();
    expect(parseRealtimeEvent("document.status", "[]")).toBeNull();
    expect(
      parseRealtimeEvent(
        "documents.changed",
        JSON.stringify({
          type: "documents.changed",
          organization_id: "o",
          payload: {},
        }),
      ),
    ).toEqual({
      type: "documents.changed",
      organization_id: "o",
      occurred_at: "",
      payload: {},
    });
  });
});
