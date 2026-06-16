import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GraphExplorerPage } from "@/components/graph/GraphExplorerPage";
import { normalizeApiError } from "@/lib/api/errors";
import {
  getGraphStats,
  listGraphEntities,
  listGraphRelationships,
} from "@/lib/api/graph";

vi.mock("@/lib/api/graph", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api/graph")>("@/lib/api/graph");
  return {
    ...actual,
    getGraphStats: vi.fn(),
    listGraphEntities: vi.fn(),
    listGraphRelationships: vi.fn(),
  };
});

const mockedGetGraphStats = vi.mocked(getGraphStats);
const mockedListGraphEntities = vi.mocked(listGraphEntities);
const mockedListGraphRelationships = vi.mocked(listGraphRelationships);

const EMPTY_STATS = {
  total_entities: 0,
  total_relations: 0,
  avg_confidence: null,
  low_confidence_count: 0,
  entities_by_type: [],
  graph_available: false,
};

const EMPTY_ENTITIES = {
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
  relationship_direction: "both" as const,
};

const EMPTY_RELATIONSHIPS = {
  items: [],
  total: 0,
  skip: 0,
  limit: 25,
  has_more: false,
};

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
    mockedGetGraphStats.mockReset();
    mockedListGraphEntities.mockReset();
    mockedListGraphRelationships.mockReset();
    mockedGetGraphStats.mockResolvedValue(EMPTY_STATS);
  });

  it("renders loading, empty, and result states for the explorer", async () => {
    mockedListGraphEntities.mockResolvedValueOnce(EMPTY_ENTITIES);

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

  // ------------------------------------------------------------------
  // F269 — Stats panel
  // ------------------------------------------------------------------

  it("shows stats panel when graph is available", async () => {
    mockedGetGraphStats.mockResolvedValueOnce({
      total_entities: 120,
      total_relations: 54,
      avg_confidence: 0.87,
      low_confidence_count: 3,
      entities_by_type: [
        { entity_type: "Vendor", count: 80, avg_confidence: 0.91 },
        { entity_type: "Person", count: 40, avg_confidence: 0.82 },
      ],
      graph_available: true,
    });
    mockedListGraphEntities.mockResolvedValueOnce(EMPTY_ENTITIES);

    renderPage();

    expect(await screen.findByText("Graph overview")).toBeInTheDocument();
    // Stats panel metric values
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("54")).toBeInTheDocument();
    // Entity type pill buttons in the stats panel
    expect(
      screen.getByRole("button", { name: /Vendor/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Person/i }),
    ).toBeInTheDocument();
  });

  it("hides stats panel when graph is unavailable", async () => {
    mockedGetGraphStats.mockResolvedValueOnce(EMPTY_STATS);
    mockedListGraphEntities.mockResolvedValueOnce(EMPTY_ENTITIES);

    renderPage();

    await screen.findByText("No graph entities found");
    expect(screen.queryByText("Graph overview")).not.toBeInTheDocument();
  });

  it("clicking entity type pill applies filter", async () => {
    mockedGetGraphStats.mockResolvedValueOnce({
      total_entities: 120,
      total_relations: 54,
      avg_confidence: 0.87,
      low_confidence_count: 3,
      entities_by_type: [
        { entity_type: "Vendor", count: 80, avg_confidence: 0.91 },
      ],
      graph_available: true,
    });
    mockedListGraphEntities.mockResolvedValue(EMPTY_ENTITIES);

    renderPage();

    const vendorBtn = await screen.findByRole("button", { name: /Vendor/i });
    await userEvent.click(vendorBtn);

    await waitFor(() => {
      expect(mockedListGraphEntities).toHaveBeenLastCalledWith(
        expect.objectContaining({ entity_type: "Vendor" }),
      );
    });
  });

  it("clicking active type pill clears filter", async () => {
    mockedGetGraphStats.mockResolvedValueOnce({
      total_entities: 10,
      total_relations: 5,
      avg_confidence: 0.9,
      low_confidence_count: 0,
      entities_by_type: [
        { entity_type: "Person", count: 10, avg_confidence: 0.9 },
      ],
      graph_available: true,
    });
    mockedListGraphEntities.mockResolvedValue(EMPTY_ENTITIES);

    renderPage();

    const personBtn = await screen.findByRole("button", { name: /Person/i });
    await userEvent.click(personBtn);
    await waitFor(() => {
      expect(mockedListGraphEntities).toHaveBeenLastCalledWith(
        expect.objectContaining({ entity_type: "Person" }),
      );
    });

    // click again to deselect
    await userEvent.click(personBtn);
    await waitFor(() => {
      expect(mockedListGraphEntities).toHaveBeenLastCalledWith(
        expect.objectContaining({ entity_type: undefined }),
      );
    });
  });

  // ------------------------------------------------------------------
  // F269 — Relationships tab
  // ------------------------------------------------------------------

  it("shows relationships tab and loads relationships", async () => {
    mockedListGraphEntities.mockResolvedValue(EMPTY_ENTITIES);
    mockedListGraphRelationships.mockResolvedValueOnce({
      items: [
        {
          relation_id: "rel-1",
          from_entity_id: "entity-1",
          rel_type: "OWNS",
          to_entity_id: "entity-2",
          status: "verified",
          confidence: 0.9,
          properties: {},
        },
      ],
      total: 1,
      skip: 0,
      limit: 25,
      has_more: false,
    });

    renderPage();

    const relTab = screen.getByRole("button", { name: "Relationships" });
    await userEvent.click(relTab);

    expect(await screen.findByText("OWNS")).toBeInTheDocument();
  });

  it("relationships tab shows empty state when no results", async () => {
    mockedListGraphEntities.mockResolvedValue(EMPTY_ENTITIES);
    mockedListGraphRelationships.mockResolvedValueOnce(EMPTY_RELATIONSHIPS);

    renderPage();

    await userEvent.click(screen.getByRole("button", { name: "Relationships" }));

    expect(
      await screen.findByText("No relationships found"),
    ).toBeInTheDocument();
  });

  it("relationships tab filters are forwarded to API", async () => {
    mockedListGraphEntities.mockResolvedValue(EMPTY_ENTITIES);
    mockedListGraphRelationships.mockResolvedValue(EMPTY_RELATIONSHIPS);

    renderPage();

    await userEvent.click(screen.getByRole("button", { name: "Relationships" }));
    await screen.findByText("No relationships found");

    await userEvent.type(
      screen.getByPlaceholderText("OWNS"),
      "OWNS",
    );
    await userEvent.click(screen.getByRole("button", { name: "Filter" }));

    await waitFor(() => {
      expect(mockedListGraphRelationships).toHaveBeenLastCalledWith(
        expect.objectContaining({ rel_type: "OWNS" }),
      );
    });
  });

  it("tab toggle switches between entities and relationships views", async () => {
    mockedListGraphEntities.mockResolvedValue(EMPTY_ENTITIES);
    mockedListGraphRelationships.mockResolvedValue(EMPTY_RELATIONSHIPS);

    renderPage();

    // Start on entities tab — entity type filter is visible
    expect(screen.getByLabelText("Entity type")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Relationships" }));
    await screen.findByText("No relationships found");

    // Switched to relationships — entity type filter is hidden
    expect(screen.queryByLabelText("Entity type")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Entities" }));

    expect(await screen.findByLabelText("Entity type")).toBeInTheDocument();
  });
});
