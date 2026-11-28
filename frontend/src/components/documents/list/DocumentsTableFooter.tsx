"use client";

import { DOCUMENT_PAGE_SIZE } from "@/components/documents/list/documents-list-format";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

/** Bulk-delete bar and page navigation under the documents table. */
export function DocumentsTableFooter({
  ctl,
}: {
  ctl: DocumentsPageController;
}) {
  const {
    tp,
    capabilities,
    setOffset,
    selectedIds,
    setDeleteModalState,
    documents,
    isBulkDeleting,
    someSelected,
    canGoPrevDocuments,
    canGoNextDocuments,
    currentPage,
    paginationItems,
  } = ctl;
  return (
    <>
      {someSelected && capabilities.canDelete ? (
        <div className="flex items-center justify-between gap-3 border-t border-rose-100 bg-rose-50 px-4 py-2">
          <p className="text-sm font-semibold text-rose-800">
            {selectedIds.size === 1
              ? tp("bulkSelectedSingle", { count: selectedIds.size })
              : tp("bulkSelectedPlural", { count: selectedIds.size })}
          </p>
          <button
            type="button"
            disabled={isBulkDeleting}
            onClick={() => {
              const filenames = documents
                .filter((d) => selectedIds.has(d.document_id))
                .map((d) => d.filename);
              setDeleteModalState({
                open: true,
                documentId: null,
                filenames,
              });
            }}
            className="flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="material-symbols-outlined text-[16px]">
              delete
            </span>
            {tp("deleteSelected", { count: selectedIds.size })}
          </button>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e5e3f1] bg-[#fcfbff] px-4 py-3">
        <button
          type="button"
          aria-label={tp("previous")}
          disabled={!canGoPrevDocuments}
          onClick={() =>
            setOffset((current) => Math.max(0, current - DOCUMENT_PAGE_SIZE))
          }
          className="flex items-center gap-1 rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
        >
          <span
            aria-hidden="true"
            className="material-symbols-outlined text-[18px]"
          >
            chevron_left
          </span>
          {tp("previous")}
        </button>
        <div className="flex items-center gap-1 text-sm">
          {paginationItems.map((item, index) =>
            item === null ? (
              <span key={`ellipsis-${index}`} className="px-2 text-[#6a6780]">
                ...
              </span>
            ) : (
              <button
                key={item}
                type="button"
                onClick={() => setOffset((item - 1) * DOCUMENT_PAGE_SIZE)}
                className={`rounded px-2 py-1 ${
                  currentPage === item
                    ? "bg-[#3525cd] text-white"
                    : "text-[#1b1b24] hover:bg-[#f1eff9]"
                }`}
              >
                {item}
              </button>
            ),
          )}
        </div>
        <button
          type="button"
          aria-label={tp("next")}
          disabled={!canGoNextDocuments}
          onClick={() => setOffset((current) => current + DOCUMENT_PAGE_SIZE)}
          className="flex items-center gap-1 rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {tp("next")}
          <span
            aria-hidden="true"
            className="material-symbols-outlined text-[18px]"
          >
            chevron_right
          </span>
        </button>
      </div>
    </>
  );
}
