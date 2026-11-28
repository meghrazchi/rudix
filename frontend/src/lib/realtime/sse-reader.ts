/**
 * Server-Sent Events parser for `fetch` response bodies (R07-07).
 *
 * `EventSource` cannot send an `Authorization` header, so the streams are read with
 * `fetch` and parsed here following the WHATWG event-stream rules: lines end in CRLF, LF,
 * or CR; `data:` lines are joined with `\n`; one leading space after the colon is dropped;
 * lines starting with `:` are comments (keep-alives); a blank line dispatches the event;
 * an event without data is not dispatched.
 */

export type SseEventFrame = {
  kind: "event";
  id: string | null;
  event: string;
  data: string;
};

export type SseCommentFrame = { kind: "comment"; text: string };

export type SseFrame = SseEventFrame | SseCommentFrame;

export class SseParser {
  private buffer = "";
  private pendingCr = false;
  private data: string[] = [];
  private eventName = "";
  private id: string | null = null;
  private hasId = false;

  /** Feed decoded text; returns every frame completed by it. */
  push(chunk: string): SseFrame[] {
    let text = chunk;
    if (this.pendingCr && text.startsWith("\n")) {
      text = text.slice(1); // the LF of a CRLF split across chunks
    }
    this.pendingCr = false;
    this.buffer += text;
    const frames: SseFrame[] = [];
    let start = 0;
    for (let index = 0; index < this.buffer.length; index += 1) {
      const char = this.buffer[index];
      if (char !== "\n" && char !== "\r") {
        continue;
      }
      const line = this.buffer.slice(start, index);
      if (char === "\r") {
        if (index + 1 < this.buffer.length) {
          if (this.buffer[index + 1] === "\n") {
            index += 1;
          }
        } else {
          this.pendingCr = true;
        }
      }
      start = index + 1;
      const frame = this.processLine(line);
      if (frame) {
        frames.push(frame);
      }
    }
    this.buffer = this.buffer.slice(start);
    return frames;
  }

  private processLine(line: string): SseFrame | null {
    if (line === "") {
      return this.dispatch();
    }
    if (line.startsWith(":")) {
      return { kind: "comment", text: line.slice(1).trimStart() };
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }
    if (field === "data") {
      this.data.push(value);
    } else if (field === "event") {
      this.eventName = value;
    } else if (field === "id" && !value.includes("\u0000")) {
      this.id = value;
      this.hasId = true;
    }
    return null;
  }

  private dispatch(): SseFrame | null {
    const data = this.data;
    const eventName = this.eventName || "message";
    const id = this.hasId ? this.id : null;
    this.data = [];
    this.eventName = "";
    this.hasId = false;
    this.id = null;
    if (data.length === 0) {
      return null;
    }
    return { kind: "event", id, event: eventName, data: data.join("\n") };
  }
}

/** Yield frames from a response body until it ends. */
export async function* readSseFrames(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        for (const frame of parser.push(decoder.decode())) {
          yield frame;
        }
        return;
      }
      for (const frame of parser.push(
        decoder.decode(value, { stream: true }),
      )) {
        yield frame;
      }
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // The stream is already closed or errored.
    }
    reader.releaseLock();
  }
}
