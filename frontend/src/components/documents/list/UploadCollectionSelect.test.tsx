import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CollectionSearchList } from "@/components/collections/useCollectionSearchList";
import { UploadCollectionSelect } from "@/components/documents/list/UploadCollectionSelect";
import type { CollectionListItemResponse } from "@/lib/api/collections";
import { renderWithProviders } from "@/test/render";

const collections = [
  { collection_id: "c1", name: "Finance" },
] as CollectionListItemResponse[];

function search(overrides: Partial<CollectionSearchList> = {}) {
  return {
    search: "",
    setSearch: vi.fn(),
    total: 60,
    hasMore: true,
    isLoadingMore: false,
    loadMore: vi.fn(),
    ...overrides,
  } as unknown as CollectionSearchList;
}

describe("UploadCollectionSelect (R07-06)", () => {
  it("searches on the server and loads more collections", async () => {
    const collectionSearch = search();
    const onChange = vi.fn();
    renderWithProviders(
      <UploadCollectionSelect
        collections={collections}
        collectionSearch={collectionSearch}
        value=""
        onChange={onChange}
        disabled={false}
      />,
    );

    expect(screen.getByText(/Showing 1 of 60/)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox"), "F");
    expect(collectionSearch.setSearch).toHaveBeenCalledWith("F");
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(collectionSearch.loadMore).toHaveBeenCalledTimes(1);
    await userEvent.selectOptions(screen.getByRole("combobox"), "c1");
    expect(onChange).toHaveBeenCalledWith("c1");
  });

  it("keeps the search box while a search has no matches", () => {
    renderWithProviders(
      <UploadCollectionSelect
        collections={[]}
        collectionSearch={search({ search: "zzz", total: 0, hasMore: false })}
        value=""
        onChange={vi.fn()}
        disabled={false}
      />,
    );
    expect(screen.getByRole("searchbox")).toHaveValue("zzz");
  });

  it("renders nothing without collections or a search", () => {
    const { container } = renderWithProviders(
      <UploadCollectionSelect
        collections={[]}
        value=""
        onChange={vi.fn()}
        disabled={false}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
