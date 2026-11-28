import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SourceScopeSelector } from "@/components/chat/SourceScopeSelector";

const labels = {
  triggerAriaLabel: "Select scope",
  scopeAllDocuments: "All documents",
  scopeCollection: "Collections",
  scopeConnectors: "Connectors",
  scopeNoRag: "No documents",
  selectDocuments: "Select documents",
  documentSearchPlaceholder: "Search documents",
  selectCollections: "Search collections",
  selectConnectors: "Search connectors",
  loadingDocuments: "Loading documents",
  loadingCollections: "Loading collections",
  loadingConnectors: "Loading connectors",
  noDocumentsAvailable: "No documents",
  noDocumentsMatch: "No match",
  noCollections: "No collections",
  noConnectors: "No connectors",
  documentSelected: "Selected",
  documentSelect: "Select",
  allDocumentsHint: "All",
  cancel: "Cancel",
  apply: "Apply",
};

function renderSelector(overrides: Record<string, unknown> = {}) {
  const props = {
    headingLabel: "Scope",
    triggerLabel: "Scope",
    labels,
    scopeMode: "all" as const,
    onScopeModeChange: vi.fn(),
    selectedCollectionIds: [],
    selectedConnectorConnectionIds: [],
    selectedProviderSourceIds: [],
    selectedDocumentIds: [],
    collections: [{ collection_id: "c1", name: "Finance" }],
    connectorConnections: [],
    indexedDocuments: [
      { document_id: "d1", filename: "a.pdf", chunk_count: 1 },
    ],
    isCollectionsLoading: false,
    isConnectorsLoading: false,
    isDocumentsLoading: false,
    onToggleCollection: vi.fn(),
    onToggleConnectorConnection: vi.fn(),
    onToggleProviderSource: vi.fn(),
    onToggleDocument: vi.fn(),
    ...overrides,
  };
  render(<SourceScopeSelector {...props} />);
  return props;
}

describe("SourceScopeSelector paging (R07-06)", () => {
  it("shows the document count and loads more", async () => {
    const onLoadMore = vi.fn();
    renderSelector({
      documentsPaging: {
        total: 45,
        hasMore: true,
        isLoadingMore: false,
        onLoadMore,
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "Select scope" }));
    await userEvent.click(screen.getByLabelText("Select documents"));

    expect(screen.getByText(/Showing 1 of 45/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("sends the collection search to the server and pages collections", async () => {
    const onCollectionSearchQueryChange = vi.fn();
    const onLoadMore = vi.fn();
    renderSelector({
      onCollectionSearchQueryChange,
      collectionsPaging: {
        total: 80,
        hasMore: true,
        isLoadingMore: false,
        onLoadMore,
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "Select scope" }));
    await userEvent.click(screen.getByLabelText("Collections"));
    await userEvent.type(
      screen.getByPlaceholderText("Search collections"),
      "Fin",
    );

    expect(onCollectionSearchQueryChange).toHaveBeenLastCalledWith("Fin");
    expect(screen.getByText(/Showing 1 of 80/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });
});
