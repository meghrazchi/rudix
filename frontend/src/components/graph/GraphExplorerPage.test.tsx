import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GraphExplorerPage } from "@/components/graph/GraphExplorerPage";
import { normalizeApiError } from "@/lib/api/errors";
import { listGraphEntities } from "@/lib/api/graph";

vi.mock("@/lib/api/graph", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api/graph")>("@/lib/api/graph");
  return {
    ...actual,
    listGraphEntities: vi.fn(),
  };
});

const mockedListGraphEntities = vi.mocked(listGraphEntities);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <GraphExplorerPage />
    </QueryClientProvider>,
  );
}

describe("GraphExplorerPage", () => {
  beforeEach(() => {
    mockedListGraphEntities.mockReset();
  });

  it("renders loading, empty, and result states for the explorer", async () => {
    mockedListGraphEntities.mockResolvedValueOnce({
      items: [],
      total: 0,
      skip: 0,
      limit: 20,
      query: null,
      entity_type: null,
      min_confidence: null,
      source_document_id: null,
      source_connector: null,
      rel_type: null,
      relationship_direction: "both",
    });

    renderPage();

    expect(
      await screen.findByText("No graph entities found"),
    ).toBeInTheDocument();

    mockedListGraphEntities.mockResolvedValueOnce({
      items: [
        {
          entity_id: "entity-1",
          entity_type: "Vendor",
          canonical_name: "Acme Corp",
          normalized_name: "acme corp",
          aliases: ["Acme"],
          alias_count: 1,
          workspace_id: "ws-1",
          external_source_id: "src-1",
          resolution_status: "verified",
          resolution_confidence: 0.92,
          confidence: 0.95,
          last_updated_at: "2026-06-14T10:00:00Z",
          evidence_count: 2,
          related_document_count: 1,
        },
      ],
      total: 1,
      skip: 0,
      limit: 20,
      query: "acme",
      entity_type: "Vendor",
      min_confidence: 0.8,
      source_document_id: "doc-1",
      source_connector: "confluence",
      rel_type: "OWNS",
      relationship_direction: "out",
    });

    await userEvent.type(
      screen.getByPlaceholderText("Entity name, alias, or external source"),
      "acme",
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Entity type"),
      "Vendor",
    );
    await userEvent.clear(screen.getByLabelText("Minimum confidence"));
    await userEvent.type(screen.getByLabelText("Minimum confidence"), "0.8");
    await userEvent.type(screen.getByLabelText("Source document"), "doc-1");
    await userEvent.type(
      screen.getByLabelText("Source connector"),
      "confluence",
    );
    await userEvent.type(screen.getByLabelText("Relationship type"), "OWNS");
    await userEvent.selectOptions(
      screen.getByLabelText("Relationship direction"),
      "out",
    );
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => {
      expect(mockedListGraphEntities).toHaveBeenCalledWith(
        expect.objectContaining({
          query: "acme",
          entity_type: "Vendor",
          min_confidence: 0.8,
          source_document_id: "doc-1",
          source_connector: "confluence",
          rel_type: "OWNS",
          relationship_direction: "out",
        }),
      );
    });
    expect(screen.getByRole("link", { name: "Acme Corp" })).toHaveAttribute(
      "href",
      "/graph/entities/entity-1",
    );
    expect(screen.getByText("1 matching entities")).toBeInTheDocument();
  });

  it("shows loading state while the explorer query is pending", () => {
    mockedListGraphEntities.mockImplementationOnce(
      () => new Promise<never>(() => {}),
    );
    renderPage();

    expect(screen.getByText("Loading graph explorer...")).toBeInTheDocument();
  });

  it("shows forbidden state for 403 responses", async () => {
    mockedListGraphEntities.mockRejectedValueOnce(
      normalizeApiError({
        status: 403,
        payload: { detail: "forbidden internal detail" },
        requestId: "graph-403",
      }),
    );

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Graph explorer restricted" }),
    ).toBeInTheDocument();
    expect(screen.getByText("graph-403")).toBeInTheDocument();
  });

  it("shows an error state when the graph backend is unavailable", async () => {
    mockedListGraphEntities.mockRejectedValueOnce(
      normalizeApiError({
        status: 503,
        payload: { detail: "enterprise_graph_unavailable" },
        requestId: "graph-503",
      }),
    );

    renderPage();

    expect(
      await screen.findByText("Graph explorer unavailable"),
    ).toBeInTheDocument();
    expect(screen.getByText("graph-503")).toBeInTheDocument();
  });
});
