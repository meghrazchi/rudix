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
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ChatCitationResponse } from "@/lib/api/chat";
import { DocumentPreviewModal } from "@/components/chat/DocumentPreviewModal";
import { renderWithProviders } from "@/test/render";
import {
  mockDocumentDetail,
  mockDocumentChunks,
} from "@/test/msw/fixtures";

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

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  Element.prototype.scrollIntoView = vi.fn();
});

describe("DocumentPreviewModal", () => {
  it("renders the cited passage banner with snippet text", async () => {
    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

    expect(
      await screen.findByText("Rudix processes enterprise documents securely."),
    ).toBeInTheDocument();
    expect(screen.getByText("Cited passage")).toBeInTheDocument();
  });

  it("shows document filename and page number in header", async () => {
    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

    expect(
      await screen.findByText("Employee-Handbook.pdf"),
    ).toBeInTheDocument();
    expect(screen.getByText("Page 3")).toBeInTheDocument();
  });

  it("shows file type chip and indexed status from document detail", async () => {
    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

    expect(await screen.findByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("indexed")).toBeInTheDocument();
  });

  it("shows rerank score in the metadata strip", async () => {
    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

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

    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

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

    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

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

    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

    expect(
      await screen.findByText("Document unavailable"),
    ).toBeInTheDocument();
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

    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

    // Wait for the restricted error state to render before checking button state
    await screen.findByText("Access restricted");
    expect(
      screen.getByRole("button", { name: /download original/i }),
    ).toBeDisabled();
  });

  it("shows View in Documents link with document id, chunk id, snippet, and back params", async () => {
    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

    // Wait for any async content
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
    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={onClose} />,
    );

    await screen.findByText("Employee-Handbook.pdf");
    await userEvent.click(screen.getByRole("button", { name: /close preview/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows generic error with retry when chunks fetch fails with 500", async () => {
    server.use(
      http.get(`${apiBaseUrl}/documents/:id/chunks`, () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );

    renderWithProviders(
      <DocumentPreviewModal citation={baseCitation} onClose={vi.fn()} />,
    );

    expect(
      await screen.findByText(/failed to load document content/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });
});
