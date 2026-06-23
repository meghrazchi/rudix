import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SharedAnswerPage } from "@/components/chat/SharedAnswerPage";
import { renderWithProviders } from "@/test/render";
import { mockDocumentDetail } from "@/test/msw/fixtures";

const apiBaseUrl = "http://api.test";

const server = setupServer(
  http.get(`${apiBaseUrl}/chat/answer-shared/:token`, () =>
    HttpResponse.json({
      question: "What is the policy?",
      answer: "Employees receive 20 days of annual leave.",
      shared_at: "2026-06-23T10:00:00Z",
      expires_at: null,
      access_mode: "org_only",
      confidence_score: 0.92,
      confidence_category: "high",
      citations: [
        {
          document_id: "doc-1",
          chunk_id: "chunk-1",
          filename: "Employee-Handbook.pdf",
          page_number: 3,
          text_snippet: "Employees receive 20 days of annual leave.",
          source_provider_label: "Confluence",
          source_title: "Leave policy",
          source_section: "Policy / Leave",
          source_key: "page-123",
          source_trust_status: "trusted",
          source_freshness_warning: false,
          source_freshness_warning_reason: null,
        },
      ],
    }),
  ),
  http.get(`${apiBaseUrl}/documents/:id`, () =>
    HttpResponse.json(mockDocumentDetail),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
});

describe("SharedAnswerPage", () => {
  it("opens the citation preview drawer from a shared answer citation", async () => {
    renderWithProviders(<SharedAnswerPage token="share-token" />);

    const citationButton = await screen.findByRole("button", {
      name: /leave policy/i,
    });
    await userEvent.click(citationButton);

    expect(
      await screen.findByRole("dialog", { name: /citation preview/i }),
    ).toBeInTheDocument();
    const dialog = screen.getByRole("dialog", { name: /citation preview/i });
    expect(
      within(dialog).getByRole("link", { name: /view in documents/i }),
    ).toHaveAttribute(
      "href",
      "/documents/doc-1?chunk_id=chunk-1&page=3&back=%2Fchat",
    );
  });
});
