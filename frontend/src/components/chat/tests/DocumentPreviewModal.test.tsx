import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ChatCitationResponse } from "@/lib/api/chat";
import { DocumentPreviewModal } from "@/components/chat/DocumentPreviewModal";
import { renderWithProviders } from "@/test/render";
import { mockDocumentDetail, mockDocumentChunks } from "@/test/msw/fixtures";

const apiBaseUrl = "http://api.test";

const server = setupServer(
  http.get(`${apiBaseUrl}/documents/:id`, () =>
    HttpResponse.json(mockDocumentDetail),
  ),
  http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
    HttpResponse.json(mockDocumentChunks),
  ),
);

const baseCitation: ChatCitationResponse = {
  document_id: "doc-1",
  chunk_id: "chunk-1",
  filename: "Employee-Handbook.pdf",
  page_number: 3,
  score: 0.84,
  similarity_score: 0.81,
  rerank_score: 0.74,
  rerank_rank: 1,
  text_snippet: "Rudix processes enterprise documents securely.",
};

function render(
  citations: ChatCitationResponse[],
  initialIndex = 0,
  onClose = vi.fn(),
) {
  return renderWithProviders(
    <DocumentPreviewModal
      citations={citations}
      initialIndex={initialIndex}
      onClose={onClose}
    />,
  );
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  Element.prototype.scrollIntoView = vi.fn();
});

describe("DocumentPreviewModal", () => {
  it("renders the cited passage banner with snippet text", async () => {
    render([baseCitation]);

    expect(
      await screen.findByText("Rudix processes enterprise documents securely."),
    ).toBeInTheDocument();
    expect(screen.getByText("Cited passage")).toBeInTheDocument();
  });

  it("shows document filename and page number in header", async () => {
    render([baseCitation]);

    expect(
      await screen.findByText("Employee-Handbook.pdf"),
    ).toBeInTheDocument();
    expect(screen.getByText("Page 3")).toBeInTheDocument();
  });

  it("shows file type chip and indexed status from document detail", async () => {
    render([baseCitation]);

    expect(await screen.findByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("indexed")).toBeInTheDocument();
  });

  it("shows rerank score in the metadata strip", async () => {
    render([baseCitation]);

    expect(await screen.findByText(/Rerank: 0\.740/)).toBeInTheDocument();
  });

  it("renders chunk text body after successful load", async () => {
    server.use(
      http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
        HttpResponse.json({
          ...mockDocumentChunks,
          items: [
            {
              ...mockDocumentChunks.items[0],
              text: "Full chunk text from the handbook.",
              text_preview: "Full chunk text from the handbook.",
            },
          ],
        }),
      ),
    );

    render([baseCitation]);

    expect(
      await screen.findByText("Full chunk text from the handbook."),
    ).toBeInTheDocument();
  });

  it("shows access restricted state on 403 and still shows snippet", async () => {
    server.use(
      http.get(`${apiBaseUrl}/documents/:id`, () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
      http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
    );

    render([baseCitation]);

    expect(await screen.findByText("Access restricted")).toBeInTheDocument();
    expect(
      screen.getByText("Rudix processes enterprise documents securely."),
    ).toBeInTheDocument();
  });

  it("shows document unavailable state on 404 and still shows snippet", async () => {
    server.use(
      http.get(`${apiBaseUrl}/documents/:id`, () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
      http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    render([baseCitation]);

    expect(await screen.findByText("Document unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("Rudix processes enterprise documents securely."),
    ).toBeInTheDocument();
  });

  it("disables download button when document is restricted", async () => {
    server.use(
      http.get(`${apiBaseUrl}/documents/:id`, () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
      http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
    );

    render([baseCitation]);

    await screen.findByText("Access restricted");
    expect(
      screen.getByRole("button", { name: /download original/i }),
    ).toBeDisabled();
  });

  it("shows View in Documents link with document id, chunk id, snippet, and back params", async () => {
    render([baseCitation]);

    await screen.findByText("Employee-Handbook.pdf");

    const link = screen.getByRole("link", { name: /view in documents/i });
    const href = link.getAttribute("href") ?? "";
    expect(href).toContain("/documents/doc-1");
    expect(href).toContain("chunk_id=chunk-1");
    expect(href).toContain("snippet=");
    expect(href).toContain("page=3");
    expect(href).toContain("back=%2Fchat");
  });

  it("calls onClose when close button is clicked", async () => {
    const onClose = vi.fn();
    render([baseCitation], 0, onClose);

    await screen.findByText("Employee-Handbook.pdf");
    await userEvent.click(
      screen.getByRole("button", { name: /close preview/i }),
    );
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows generic error with retry when chunks fetch fails with 500", async () => {
    server.use(
      http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );

    render([baseCitation]);

    expect(
      await screen.findByText(/failed to load document content/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });
});

describe("DocumentPreviewModal — offset-based highlighting", () => {
  it("renders highlighted mark when start_offset and end_offset are provided", async () => {
    const chunkText = "Rudix processes enterprise documents securely.";
    const snippet = "enterprise documents";
    const startOffset = chunkText.indexOf(snippet); // 16
    const endOffset = startOffset + snippet.length; // 36

    server.use(
      http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
        HttpResponse.json({
          ...mockDocumentChunks,
          items: [
            {
              ...mockDocumentChunks.items[0],
              text: chunkText,
              text_preview: chunkText,
            },
          ],
        }),
      ),
    );

    const citation: ChatCitationResponse = {
      ...baseCitation,
      text_snippet: snippet,
      start_offset: startOffset,
      end_offset: endOffset,
    };

    const { container } = render([citation]);

    // Chunks load async — wait until a <mark> appears in the chunk body.
    await waitFor(() => {
      expect(container.querySelector("mark")).not.toBeNull();
    });
    expect(container.querySelector("mark")?.textContent).toBe(snippet);
  });

  it("falls back to case-insensitive match when offsets are absent", async () => {
    const chunkText = "Rudix processes enterprise documents securely.";
    server.use(
      http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
        HttpResponse.json({
          ...mockDocumentChunks,
          items: [
            {
              ...mockDocumentChunks.items[0],
              text: chunkText,
              text_preview: chunkText,
            },
          ],
        }),
      ),
    );

    // Uppercase snippet — no offsets; should fall back to case-insensitive search.
    const citation: ChatCitationResponse = {
      ...baseCitation,
      text_snippet: "ENTERPRISE DOCUMENTS",
      start_offset: null,
      end_offset: null,
    };

    const { container } = render([citation]);

    await waitFor(() => {
      expect(container.querySelector("mark")).not.toBeNull();
    });
    expect(container.querySelector("mark")?.textContent?.toLowerCase()).toBe(
      "enterprise documents",
    );
  });

  it("shows fallback note when snippet cannot be located in chunk text", async () => {
    const chunkText = "Completely different text in this chunk.";
    server.use(
      http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
        HttpResponse.json({
          ...mockDocumentChunks,
          items: [
            {
              ...mockDocumentChunks.items[0],
              text: chunkText,
              text_preview: chunkText,
            },
          ],
        }),
      ),
    );

    const citation: ChatCitationResponse = {
      ...baseCitation,
      text_snippet: "xyzzy no match possible here",
      start_offset: null,
      end_offset: null,
    };

    render([citation]);

    expect(
      await screen.findByText(/exact highlight unavailable/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("mark")).not.toBeInTheDocument();
  });
});

describe("DocumentPreviewModal — multi-citation navigation", () => {
  const citationA: ChatCitationResponse = {
    ...baseCitation,
    chunk_id: "chunk-1",
    text_snippet: "First cited passage from this document.",
    page_number: 1,
  };

  const citationB: ChatCitationResponse = {
    ...baseCitation,
    chunk_id: "chunk-1",
    text_snippet: "Second cited passage from the same document.",
    page_number: 2,
  };

  it("shows citation counter when multiple citations are provided", async () => {
    render([citationA, citationB]);

    expect(await screen.findByText("Citation 1 of 2")).toBeInTheDocument();
  });

  it("does not show navigation bar for a single citation", async () => {
    render([baseCitation]);

    await screen.findByText("Employee-Handbook.pdf");
    expect(screen.queryByText(/Citation \d of \d/)).not.toBeInTheDocument();
  });

  it("previous button is disabled on the first citation", async () => {
    render([citationA, citationB], 0);

    await screen.findByText("Citation 1 of 2");
    expect(
      screen.getByRole("button", { name: /previous citation/i }),
    ).toBeDisabled();
  });

  it("next button is disabled on the last citation", async () => {
    render([citationA, citationB], 1);

    await screen.findByText("Citation 2 of 2");
    expect(
      screen.getByRole("button", { name: /next citation/i }),
    ).toBeDisabled();
  });

  it("navigating to next citation updates the counter and snippet", async () => {
    render([citationA, citationB], 0);

    await screen.findByText("Citation 1 of 2");
    expect(
      screen.getByText("First cited passage from this document."),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /next citation/i }),
    );

    expect(screen.getByText("Citation 2 of 2")).toBeInTheDocument();
    expect(
      screen.getByText("Second cited passage from the same document."),
    ).toBeInTheDocument();
  });

  it("navigating back from second citation restores first citation", async () => {
    render([citationA, citationB], 1);

    await screen.findByText("Citation 2 of 2");

    await userEvent.click(
      screen.getByRole("button", { name: /previous citation/i }),
    );

    expect(screen.getByText("Citation 1 of 2")).toBeInTheDocument();
    expect(
      screen.getByText("First cited passage from this document."),
    ).toBeInTheDocument();
  });
});
