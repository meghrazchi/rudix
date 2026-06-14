import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GraphEntityDetailPage } from "@/components/graph/GraphEntityDetailPage";
import { normalizeApiError } from "@/lib/api/errors";
import { getGraphEntity } from "@/lib/api/graph";

vi.mock("@/lib/api/graph", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api/graph")>("@/lib/api/graph");
  return {
    ...actual,
    getGraphEntity: vi.fn(),
  };
});

const mockedGetGraphEntity = vi.mocked(getGraphEntity);

function renderPage(entityId = "entity-1") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <GraphEntityDetailPage entityId={entityId} />
    </QueryClientProvider>,
  );
}

describe("GraphEntityDetailPage", () => {
  beforeEach(() => {
    mockedGetGraphEntity.mockReset();
  });

  it("shows provenance-backed details and connected documents", async () => {
    mockedGetGraphEntity.mockResolvedValueOnce({
      entity: {
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
        evidence_count: 1,
        related_document_count: 1,
      },
      aliases: [
        {
          alias_id: "alias-1",
          entity_id: "entity-1",
          alias_name: "Acme",
          normalized_name: "acme",
          source_document_id: "doc-1",
          chunk_id: "chunk-1",
          workspace_id: "ws-1",
          source_external_id: null,
          source_connector: "confluence",
          language: "en",
          confidence: 0.9,
          evidence_text: "Acme",
          page_number: 1,
          created_at: "2026-06-14T09:58:00Z",
          updated_at: "2026-06-14T09:58:00Z",
        },
      ],
      evidence: [
        {
          chunk_id: "chunk-1",
          source_document_id: "doc-1",
          workspace_id: "ws-1",
          document_version_id: "v1",
          page_number: 1,
          source_connector: "confluence",
          external_url: "https://example.com/doc-1",
          extraction_run_id: "run-1",
          confidence: 0.9,
          evidence_text: "Acme Corp is our vendor.",
          citation_text: "Acme Corp is our vendor.",
          citation_reference: "Policy p. 1",
          created_at: "2026-06-14T09:58:00Z",
        },
      ],
      relationships: [
        {
          relation_id: "rel-1",
          from_entity_id: "entity-1",
          rel_type: "OWNS",
          to_entity_id: "entity-2",
          status: "verified",
          confidence: 0.88,
          properties: { evidence_text: "Acme owns Contoso." },
        },
      ],
      connected_documents: [
        {
          document_id: "doc-1",
          page_numbers: [1],
          evidence_count: 1,
          max_confidence: 0.9,
          source_connectors: ["confluence"],
        },
      ],
      connected_entities: [
        {
          entity_id: "entity-2",
          entity_type: "Organization",
          canonical_name: "Contoso",
          normalized_name: "contoso",
          relation_count: 1,
        },
      ],
      summary: {
        alias_count: 1,
        evidence_count: 1,
        relationship_count: 1,
        connected_document_count: 1,
        connected_entity_count: 1,
      },
    });

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Acme Corp" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Document doc-1")).toHaveLength(2);
    expect(screen.getByText("Acme Corp is our vendor.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Contoso" })).toHaveAttribute(
      "href",
      "/graph/entities/entity-2",
    );
    expect(screen.getByRole("link", { name: "Open evidence" })).toHaveAttribute(
      "href",
      "/documents/doc-1?chunk_id=chunk-1&back=%2Fgraph%2Fentities%2Fentity-1",
    );
  });

  it("applies relationship filters and refetches detail data", async () => {
    mockedGetGraphEntity.mockResolvedValue({
      entity: {
        entity_id: "entity-1",
        entity_type: "Vendor",
        canonical_name: "Acme Corp",
        normalized_name: "acme corp",
        aliases: [],
        alias_count: 0,
        workspace_id: null,
        external_source_id: null,
        resolution_status: null,
        resolution_confidence: null,
        confidence: null,
        last_updated_at: "2026-06-14T10:00:00Z",
        evidence_count: 0,
        related_document_count: 0,
      },
      aliases: [],
      evidence: [],
      relationships: [],
      connected_documents: [],
      connected_entities: [],
      summary: {
        alias_count: 0,
        evidence_count: 0,
        relationship_count: 0,
        connected_document_count: 0,
        connected_entity_count: 0,
      },
    });

    renderPage();

    await screen.findByRole("heading", { name: "Acme Corp" });
    await userEvent.type(screen.getByPlaceholderText("OWNS"), "OWNS");
    await userEvent.selectOptions(screen.getByLabelText("Direction"), "out");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      expect(mockedGetGraphEntity).toHaveBeenLastCalledWith("entity-1", {
        rel_type: "OWNS",
        relationship_direction: "out",
        limit: 100,
      });
    });
  });

  it("shows forbidden state for 403 responses", async () => {
    mockedGetGraphEntity.mockRejectedValueOnce(
      normalizeApiError({
        status: 403,
        payload: { detail: "forbidden internal detail" },
        requestId: "entity-403",
      }),
    );

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Graph entity restricted" }),
    ).toBeInTheDocument();
    expect(screen.getByText("entity-403")).toBeInTheDocument();
  });
});
