"use client";

import { EmptyState } from "@/components/states/EmptyState";
import { LoadMoreFooter } from "@/components/pagination/LoadMoreFooter";
import type { CollectionDetailResponse } from "@/lib/api/collections";

import {
  CollectionCard,
  NewCollectionCard,
} from "@/components/collections/CollectionCards";
import type { CollectionsPageController } from "@/components/collections/useCollectionsPage";

/** Collection cards grid, empty state, and page navigation. */
export function CollectionsGrid({ ctl }: { ctl: CollectionsPageController }) {
  const {
    tc,
    capabilities,
    collectionsList,
    allCollections,
    nameSearch,
    setNameSearch,
    accessFilter,
    setAccessFilter,
    selectedCollectionId,
    setSelectedCollectionId,
    setDialogMode,
    setDialogSaveError,
    visibleCollections,
    deleteMutation,
    handleDeleteCollection,
    showGrid,
  } = ctl;
  return (
    <>
      {showGrid ? (
        <section className="grid grid-cols-1 gap-6 pb-8 md:grid-cols-2 xl:grid-cols-3">
          {visibleCollections.map((col) => (
            <CollectionCard
              key={col.collection_id}
              collection={col}
              isSelected={selectedCollectionId === col.collection_id}
              capabilities={capabilities}
              onSelect={() =>
                setSelectedCollectionId(
                  selectedCollectionId === col.collection_id
                    ? null
                    : col.collection_id,
                )
              }
              onEdit={(c) => {
                setDialogSaveError(null);
                setDialogMode({
                  mode: "edit",
                  collection: c as CollectionDetailResponse,
                });
              }}
              onDelete={handleDeleteCollection}
              isDeleting={
                deleteMutation.isPending &&
                deleteMutation.variables === col.collection_id
              }
            />
          ))}

          {visibleCollections.length === 0 ? (
            <div className="col-span-full">
              <EmptyState
                title={
                  nameSearch || accessFilter !== "all"
                    ? tc("noMatchTitle")
                    : tc("noCollectionsYetTitle")
                }
                description={
                  nameSearch || accessFilter !== "all"
                    ? undefined
                    : tc("noCollectionsYetDesc")
                }
                action={
                  nameSearch || accessFilter !== "all" ? (
                    <button
                      type="button"
                      onClick={() => {
                        setNameSearch("");
                        setAccessFilter("all");
                      }}
                      className="rounded-xl border border-[#d2cee6] bg-white px-3 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
                    >
                      {tc("clearFilters")}
                    </button>
                  ) : capabilities.canCreate ? (
                    <button
                      type="button"
                      onClick={() => {
                        setDialogSaveError(null);
                        setDialogMode("create");
                      }}
                      className="rounded-xl bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
                    >
                      {tc("newCollectionEmpty")}
                    </button>
                  ) : undefined
                }
              />
            </div>
          ) : null}

          {visibleCollections.length > 0 && capabilities.canCreate ? (
            <NewCollectionCard
              onCreate={() => {
                setDialogSaveError(null);
                setDialogMode("create");
              }}
            />
          ) : null}
        </section>
      ) : null}

      {showGrid && allCollections.length > 0 ? (
        <LoadMoreFooter
          shown={allCollections.length}
          total={collectionsList.total}
          hasMore={collectionsList.hasMore}
          isLoadingMore={collectionsList.isLoadingMore}
          onLoadMore={collectionsList.loadMore}
          className="flex flex-wrap items-center justify-between gap-3 pb-4 text-sm text-[#68647b]"
        />
      ) : null}
    </>
  );
}
