import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ChatCitationResponse,
  ChatSessionMessageResponse,
} from "@/lib/api/chat";
import {
  copyToClipboard,
  downloadMarkdown,
  formatAnswerAsMarkdown,
  formatSourceListAsMarkdown,
  formatTranscriptAsMarkdown,
  formatTurnAsMarkdown,
  sanitizeFilename,
  turnsFromMessages,
  type ExportTurn,
} from "@/lib/export-utils";

function citation(
  overrides: Partial<ChatCitationResponse> = {},
): ChatCitationResponse {
  return {
    document_id: "doc-1",
    chunk_id: "chunk-1",
    filename: "policy.pdf",
    page_number: 3,
    text_snippet: "Leave is 25 days.",
    ...overrides,
  } as ChatCitationResponse;
}

const turn: ExportTurn = {
  question: "How much leave?",
  answer: "25 days per year.",
  citations: [citation()],
  created_at: "2026-11-27T10:00:00Z",
};

describe("export-utils markdown", () => {
  it("formats a turn with question, answer and sources", () => {
    const md = formatTurnAsMarkdown(turn);
    expect(md).toContain("**Q:** How much leave?");
    expect(md).toContain("25 days per year.");
    expect(md).toContain("1. **policy.pdf** (page 3)");
    expect(md).toContain("> Leave is 25 days.");
  });

  it("omits the sources block when there are no citations", () => {
    const md = formatAnswerAsMarkdown({ ...turn, citations: [] });
    expect(md).toBe("25 days per year.");
  });

  it("falls back to a generic filename and skips a missing page", () => {
    const md = formatAnswerAsMarkdown({
      ...turn,
      citations: [
        citation({ filename: null, page_number: null, text_snippet: "" }),
      ],
    });
    expect(md).toContain("1. **Document**");
    expect(md).not.toContain("page");
  });

  it("formats a transcript with a default title and numbered turns", () => {
    const md = formatTranscriptAsMarkdown([turn, turn], "  ");
    expect(md.startsWith("# Chat Export\n")).toBe(true);
    expect(md).toContain("## Turn 1");
    expect(md).toContain("## Turn 2");
    expect(formatTranscriptAsMarkdown([turn], "HR")).toContain("# HR\n");
  });

  it("lists each cited source once", () => {
    const other = citation({ chunk_id: "chunk-2", page_number: null });
    const md = formatSourceListAsMarkdown([
      turn,
      { ...turn, citations: [citation(), other] },
    ]);
    expect(md).toBe(
      "# Source List\n\n1. **policy.pdf** — page 3\n2. **policy.pdf**\n",
    );
    expect(formatSourceListAsMarkdown([])).toBe("No sources cited.\n");
  });
});

describe("turnsFromMessages", () => {
  it("pairs each user question with the next assistant answer", () => {
    const messages = [
      { role: "assistant", content: "orphan", created_at: "t0" },
      { role: "user", content: "Q1", created_at: "t1" },
      { role: "assistant", content: "A1", created_at: "t2", citations: null },
      { role: "user", content: "Q2", created_at: "t3" },
    ] as unknown as ChatSessionMessageResponse[];
    expect(turnsFromMessages(messages)).toEqual([
      { question: "Q1", answer: "A1", citations: [], created_at: "t2" },
    ]);
  });
});

describe("browser helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("copies text to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await copyToClipboard("hello");
    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("downloads markdown through a temporary object URL", () => {
    const createObjectURL = vi.fn(() => "blob:export");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    downloadMarkdown("# hi", "chat.md");

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:export");
  });

  it("sanitizes filenames and falls back when empty", () => {
    expect(sanitizeFilename("Q3 plan/notes?.md")).toBe("Q3 plan_notes_.md");
    expect(sanitizeFilename("x".repeat(100))).toHaveLength(80);
    expect(sanitizeFilename("")).toBe("export");
  });
});
