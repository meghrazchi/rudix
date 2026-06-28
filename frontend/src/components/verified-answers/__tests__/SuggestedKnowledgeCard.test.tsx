import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SuggestedKnowledgeCard } from "@/components/verified-answers/SuggestedKnowledgeCard";
import type { VerifiedAnswerResponse } from "@/lib/api/verified-answers";

// ── mocks ──────────────────────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  searchVerifiedAnswers: vi.fn(),
}));

vi.mock("@/lib/api/verified-answers", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/verified-answers")>();
  return {
    ...actual,
    searchVerifiedAnswers: (...args: unknown[]) =>
      mockApi.searchVerifiedAnswers(...args),
  };
});

// ── helpers ────────────────────────────────────────────────────────────────────

function makeCard(
  overrides: Partial<VerifiedAnswerResponse> = {},
): VerifiedAnswerResponse {
  return {
    answer_id: "00000000-0000-0000-0000-000000000001",
    organization_id: "00000000-0000-0000-0000-000000000099",
    title: "Refund Policy",
    question: "How do I get a refund?",
    answer_text: "Refunds are processed in 5 days.",
    status: "published",
    tags: "billing",
    collection_id: null,
    owner_id: null,
    requires_citations: false,
    review_date: null,
    expiry_date: null,
    approved_by_id: null,
    approved_at: null,
    published_at: null,
    deprecated_at: null,
    restored_at: null,
    rejection_note: null,
    source_message_id: null,
    created_by_id: null,
    is_stale: false,
    citations: [],
    created_at: "2026-06-28T00:00:00Z",
    updated_at: "2026-06-28T00:00:00Z",
    ...overrides,
  };
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ── tests ──────────────────────────────────────────────────────────────────────

describe("SuggestedKnowledgeCard", () => {
  it("renders nothing when no matches", async () => {
    mockApi.searchVerifiedAnswers.mockResolvedValue({
      items: [],
      total: 0,
      limit: 3,
      offset: 0,
    });
    const { container } = wrap(
      <SuggestedKnowledgeCard query="some random query" />,
    );
    await waitFor(() =>
      expect(mockApi.searchVerifiedAnswers).toHaveBeenCalled(),
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders verified answer cards when matches found", async () => {
    mockApi.searchVerifiedAnswers.mockResolvedValue({
      items: [makeCard()],
      total: 1,
      limit: 3,
      offset: 0,
    });
    wrap(<SuggestedKnowledgeCard query="How do I get a refund?" />);
    await waitFor(() =>
      expect(screen.getByText("Refund Policy")).toBeInTheDocument(),
    );
    expect(screen.getByText(/verified answers/i)).toBeInTheDocument();
  });

  it("shows a Verified badge label", async () => {
    mockApi.searchVerifiedAnswers.mockResolvedValue({
      items: [makeCard()],
      total: 1,
      limit: 3,
      offset: 0,
    });
    wrap(<SuggestedKnowledgeCard query="refund" />);
    await waitFor(() => {
      const matches = screen.getAllByText(/verified/i);
      expect(matches.length).toBeGreaterThan(0);
    });
  });

  it("shows stale warning when card is_stale", async () => {
    mockApi.searchVerifiedAnswers.mockResolvedValue({
      items: [makeCard({ is_stale: true })],
      total: 1,
      limit: 3,
      offset: 0,
    });
    wrap(<SuggestedKnowledgeCard query="refund" />);
    await waitFor(() =>
      expect(screen.getByText(/may be outdated/i)).toBeInTheDocument(),
    );
  });

  it("expands card to show full answer on Expand click", async () => {
    mockApi.searchVerifiedAnswers.mockResolvedValue({
      items: [makeCard()],
      total: 1,
      limit: 3,
      offset: 0,
    });
    wrap(<SuggestedKnowledgeCard query="refund" />);
    await waitFor(() =>
      expect(screen.getByText("Refund Policy")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /expand/i }));
    expect(screen.getByText(/how do i get a refund/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /collapse/i }),
    ).toBeInTheDocument();
  });

  it("does not fetch when query is empty", async () => {
    wrap(<SuggestedKnowledgeCard query="" />);
    await new Promise((r) => setTimeout(r, 50));
    expect(mockApi.searchVerifiedAnswers).not.toHaveBeenCalled();
  });

  it("renders multiple matching cards", async () => {
    const card2 = makeCard({
      answer_id: "00000000-0000-0000-0000-000000000002",
      title: "Return Policy",
    });
    mockApi.searchVerifiedAnswers.mockResolvedValue({
      items: [makeCard(), card2],
      total: 2,
      limit: 3,
      offset: 0,
    });
    wrap(<SuggestedKnowledgeCard query="refund" />);
    await waitFor(() =>
      expect(screen.getByText("Refund Policy")).toBeInTheDocument(),
    );
    expect(screen.getByText("Return Policy")).toBeInTheDocument();
  });
});
