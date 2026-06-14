import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentGraphInsightsPanel } from "@/components/documents/DocumentGraphInsightsPanel";
import { normalizeApiError } from "@/lib/api/errors";
import { getDocumentGraphInsights } from "@/lib/api/graph";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api/graph", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api/graph")>("@/lib/api/graph");
  return {
    ...actual,
    getDocumentGraphInsights: vi.fn(),
  };
});

const mockedGetInsights = vi.mocked(getDocumentGraphInsights);

const INSIGHTS_DATA = {
  entity_count: 5,
  relation_count: 3,
  avg_confidence: 0.87,
  entities_by_type: { Person: 3, Organization: 2 },
  top_entities: [
    {
      entity_id: "e-1",
      entity_type: "Person",
      canonical_name: "Alice",
      confidence: 0.9,
      evidence_count: 2,
    },
    {
      entity_id: "e-2",
      entity_type: "Organization",
      canonical_name: "Acme Corp",
      confidence: 0.85,
      evidence_count: 3,
    },
    {
      entity_id: "e-3",
      entity_type: "Person",
      canonical_name: "Bob",
      confidence: 0.78,
      evidence_count: 1,
    },
  ],
  recent_evidence: [
    {
      chunk_id: "chunk-1",
      source_document_id: "doc-abc",
      page_number: 4,
      confidence: 0.9,
      evidence_text: "Alice works at Acme Corp.",
      citation_text: null,
      citation_reference: "Report 2026, p. 4",
      extraction_run_id: "run-1",
    },
  ],
  extraction_runs: [
    {
      run_id: "run-1",
      status: "completed",
      strategy: "llm_extraction",
      entity_count: 5,
      error: null,
      created_at: "2026-06-14T10:00:00Z",
      updated_at: "2026-06-14T10:01:30Z",
    },
  ],
  last_run_at: "2026-06-14T10:01:30Z",
};

type PanelStatus =
  | "pending"
  | "extracting"
  | "completed"
  | "failed"
  | "skipped"
  | null
  | undefined;

function renderPanel(
  overrides: {
    graphExtractionStatus?: PanelStatus;
    canReindex?: boolean;
    isReindexPending?: boolean;
    onReindexGraph?: () => void;
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const status: PanelStatus =
    "graphExtractionStatus" in overrides
      ? overrides.graphExtractionStatus
      : "completed";

  return render(
    <QueryClientProvider client={queryClient}>
      <DocumentGraphInsightsPanel
        documentId="doc-abc"
        graphExtractionStatus={status}
        canReindex={overrides.canReindex ?? false}
        isReindexPending={overrides.isReindexPending ?? false}
        onReindexGraph={overrides.onReindexGraph ?? vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("DocumentGraphInsightsPanel", () => {
  beforeEach(() => {
    mockedGetInsights.mockReset();
  });

  describe("disabled/skipped state", () => {
    it("shows skipped message when extraction status is skipped", () => {
      renderPanel({ graphExtractionStatus: "skipped" });
      expect(screen.getByText(/skipped/i)).toBeInTheDocument();
    });

    it("shows no-extraction message when status is null", () => {
      renderPanel({ graphExtractionStatus: null });
      expect(screen.getByText(/not been configured/i)).toBeInTheDocument();
    });
  });

  describe("in-progress states", () => {
    it("shows extracting message when status is extracting", () => {
      renderPanel({ graphExtractionStatus: "extracting" });
      expect(screen.getByText(/in progress/i)).toBeInTheDocument();
    });

    it("shows queued message when status is pending", () => {
      renderPanel({ graphExtractionStatus: "pending" });
      expect(screen.getByText(/queued/i)).toBeInTheDocument();
    });
  });

  describe("graph unavailable (503)", () => {
    it("shows unavailable notice when graph returns 503", async () => {
      mockedGetInsights.mockRejectedValueOnce(
        normalizeApiError({
          status: 503,
          detail: "enterprise_graph_unavailable",
        }),
      );
      renderPanel({ graphExtractionStatus: "completed" });

      await waitFor(() => {
        expect(
          screen.getByTestId("graph-insights-unavailable"),
        ).toBeInTheDocument();
      });
      expect(
        screen.getByText(/enterprise graph unavailable/i),
      ).toBeInTheDocument();
    });
  });

  describe("loading state", () => {
    it("shows loading state while fetching", async () => {
      mockedGetInsights.mockImplementation(() => new Promise(() => {}));
      renderPanel({ graphExtractionStatus: "completed" });
      await waitFor(() => {
        expect(screen.getByText(/loading graph insights/i)).toBeInTheDocument();
      });
    });
  });

  describe("completed state with data", () => {
    it("shows entity count, relation count, and avg confidence", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({ graphExtractionStatus: "completed" });

      await waitFor(() => {
        expect(screen.getByText("87%")).toBeInTheDocument();
      });
      const statCards = screen.getAllByText("5");
      expect(statCards.length).toBeGreaterThanOrEqual(1);
      const threeMatches = screen.getAllByText("3");
      expect(threeMatches.length).toBeGreaterThanOrEqual(1);
    });

    it("shows entity type groups", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({ graphExtractionStatus: "completed" });

      await waitFor(() => {
        expect(screen.getByText("Person")).toBeInTheDocument();
      });
      expect(screen.getByText("Organization")).toBeInTheDocument();
    });

    it("lists entities within their type group", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({ graphExtractionStatus: "completed" });

      await waitFor(() => {
        expect(screen.getByText("Alice")).toBeInTheDocument();
      });
      expect(screen.getByText("Acme Corp")).toBeInTheDocument();
      expect(screen.getByText("Bob")).toBeInTheDocument();
    });

    it("entity names link to entity detail pages", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({ graphExtractionStatus: "completed" });

      await waitFor(() => {
        expect(screen.getByRole("link", { name: "Alice" })).toHaveAttribute(
          "href",
          expect.stringContaining("/graph/entities/e-1"),
        );
      });
    });

    it("shows evidence snippets with page numbers", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({ graphExtractionStatus: "completed" });

      await waitFor(() => {
        expect(
          screen.getByText("Alice works at Acme Corp."),
        ).toBeInTheDocument();
      });
      expect(screen.getByText(/page 4/i)).toBeInTheDocument();
      expect(screen.getByText(/report 2026, p\. 4/i)).toBeInTheDocument();
    });

    it("evidence snippets link to chunk deep-links", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({ graphExtractionStatus: "completed" });

      await waitFor(() => {
        const chunkLink = screen.getByRole("link", { name: /view chunk/i });
        expect(chunkLink).toHaveAttribute(
          "href",
          expect.stringContaining("chunk_id=chunk-1"),
        );
      });
    });

    it("shows extraction run history", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({ graphExtractionStatus: "completed" });

      await waitFor(() => {
        expect(screen.getByText("completed")).toBeInTheDocument();
      });
      expect(screen.getByText(/llm_extraction/i)).toBeInTheDocument();
      expect(screen.getByText(/5 entities/i)).toBeInTheDocument();
    });
  });

  describe("failed extraction state", () => {
    it("shows failure notice and run history with error", async () => {
      const failedData = {
        ...INSIGHTS_DATA,
        entity_count: 0,
        top_entities: [],
        entities_by_type: {},
        recent_evidence: [],
        extraction_runs: [
          {
            run_id: "run-fail",
            status: "failed",
            strategy: "llm_extraction",
            entity_count: null,
            error: "LLM timeout after 30s",
            created_at: "2026-06-14T09:00:00Z",
            updated_at: "2026-06-14T09:00:30Z",
          },
        ],
      };
      mockedGetInsights.mockResolvedValueOnce(failedData);
      renderPanel({ graphExtractionStatus: "failed" });

      await waitFor(() => {
        expect(screen.getByText(/last extraction failed/i)).toBeInTheDocument();
      });
      expect(screen.getByText("failed")).toBeInTheDocument();
      expect(screen.getByText("LLM timeout after 30s")).toBeInTheDocument();
    });

    it("shows empty state when no entities after failure", async () => {
      const failedData = {
        ...INSIGHTS_DATA,
        entity_count: 0,
        top_entities: [],
        entities_by_type: {},
        recent_evidence: [],
      };
      mockedGetInsights.mockResolvedValueOnce(failedData);
      renderPanel({ graphExtractionStatus: "failed" });

      await waitFor(() => {
        expect(screen.getByText(/no entities extracted/i)).toBeInTheDocument();
      });
    });
  });

  describe("admin re-run action", () => {
    it("shows re-run button when canReindex is true", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({ graphExtractionStatus: "completed", canReindex: true });

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /re-run graph extraction/i }),
        ).toBeInTheDocument();
      });
    });

    it("hides re-run button when canReindex is false", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({ graphExtractionStatus: "completed", canReindex: false });

      await waitFor(() => {
        expect(screen.getByText("Alice")).toBeInTheDocument();
      });
      expect(
        screen.queryByRole("button", { name: /re-run graph extraction/i }),
      ).not.toBeInTheDocument();
    });

    it("calls onReindexGraph when re-run is clicked", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      const onReindex = vi.fn();
      renderPanel({
        graphExtractionStatus: "completed",
        canReindex: true,
        onReindexGraph: onReindex,
      });

      const button = await screen.findByRole("button", {
        name: /re-run graph extraction/i,
      });
      await userEvent.click(button);
      expect(onReindex).toHaveBeenCalledOnce();
    });

    it("disables re-run button while reindex is pending", async () => {
      mockedGetInsights.mockResolvedValueOnce(INSIGHTS_DATA);
      renderPanel({
        graphExtractionStatus: "completed",
        canReindex: true,
        isReindexPending: true,
      });

      await waitFor(() => {
        const button = screen.getByRole("button", {
          name: /re-run graph extraction/i,
        });
        expect(button).toBeDisabled();
        expect(button).toHaveTextContent(/queueing/i);
      });
    });
  });

  describe("fetch not triggered when not needed", () => {
    it("does not call API when status is skipped", () => {
      renderPanel({ graphExtractionStatus: "skipped" });
      expect(mockedGetInsights).not.toHaveBeenCalled();
    });

    it("does not call API when status is pending", () => {
      renderPanel({ graphExtractionStatus: "pending" });
      expect(mockedGetInsights).not.toHaveBeenCalled();
    });

    it("does not call API when status is extracting", () => {
      renderPanel({ graphExtractionStatus: "extracting" });
      expect(mockedGetInsights).not.toHaveBeenCalled();
    });
  });
});
