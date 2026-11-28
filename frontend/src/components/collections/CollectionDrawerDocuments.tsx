"use client";

import Link from "next/link";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import type { CollectionDetailResponse } from "@/lib/api/collections";
import { getApiErrorMessage } from "@/lib/api/errors";

import {
  COLLECTION_DOCS_PAGE_SIZE,
  type CollectionCapabilities,
} from "@/components/collections/collection-format";
import type { CollectionDrawerController } from "@/components/collections/useCollectionDetailDrawer";

/** Drawer document list with manage, remove, and load-more controls. */
export function CollectionDrawerDocuments({
  ctl,
  detail,
  capabilities,
}: {
  ctl: CollectionDrawerController;
  detail: CollectionDetailResponse;
  capabilities: CollectionCapabilities;
}) {
  const {
    tc,
    setDocsLimit,
    actionFeedback,
    setIsDocumentPickerOpen,
    setDocumentSaveError,
    docsQuery,
    removeDocMutation,
    docs,
    canLoadMore,
    fileIcon,
  } = ctl;
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h5 className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
          {tc("indexedDocumentsTitle")}
        </h5>
        <span className="text-[12px] text-[#6a6780]">
          {tc("docsTotal", { n: docs?.total ?? 0 })}
        </span>
      </div>

      {actionFeedback ? (
        <p
          role="status"
          className="rounded-xl border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
        >
          {actionFeedback}
        </p>
      ) : null}

      {capabilities.canManageDocuments &&
      !detail.is_dynamic &&
      (docs?.items.length ?? 0) > 0 ? (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-[#e4e1ee] bg-white px-3 py-2">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[#1b1b24]">
              {tc("manageDocumentsTitle")}
            </p>
            <p className="text-xs text-[#6a6780]">
              {tc("manageDocumentsSubtitle")}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setDocumentSaveError(null);
              setIsDocumentPickerOpen(true);
            }}
            className="rounded-xl bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            {tc("manageDocumentsButton")}
          </button>
        </div>
      ) : null}
      {detail.is_dynamic && (docs?.items.length ?? 0) === 0 ? (
        <p className="rounded-xl border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-700">
          This dynamic collection has no matching documents yet. Adjust the
          rules or refresh to update membership.
        </p>
      ) : null}

      {docsQuery.isLoading ? (
        <LoadingState compact title={tc("loadingDocuments")} />
      ) : docsQuery.isError ? (
        <ErrorState
          compact
          error={docsQuery.error}
          description={getApiErrorMessage(docsQuery.error)}
          onRetry={() => void docsQuery.refetch()}
        />
      ) : docs && docs.items.length === 0 ? (
        <EmptyState
          compact
          title={tc("noDocumentsTitle")}
          description={tc("noDocumentsDesc")}
          action={
            capabilities.canManageDocuments && !detail.is_dynamic ? (
              <button
                type="button"
                onClick={() => {
                  setDocumentSaveError(null);
                  setIsDocumentPickerOpen(true);
                }}
                className="rounded-xl bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
              >
                {tc("manageDocumentsButton")}
              </button>
            ) : undefined
          }
        />
      ) : docs && docs.items.length > 0 ? (
        <div className="space-y-0.5">
          {docs.items.map((doc) => (
            <div
              key={doc.document_id}
              className="flex items-center justify-between rounded-xl border-b border-[#e4e1ee]/40 p-2 transition-colors last:border-0 hover:bg-[#f5f3ff]"
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="material-symbols-outlined shrink-0 text-[20px] text-[#6a6780]">
                  {fileIcon(doc.file_type)}
                </span>
                <Link
                  href={`/documents/${encodeURIComponent(doc.document_id)}`}
                  className="truncate text-sm font-medium text-[#1b1b24] hover:text-[#3525cd]"
                  onClick={(e) => e.stopPropagation()}
                >
                  {doc.filename}
                </Link>
              </div>
              <div className="ml-2 flex shrink-0 items-center gap-2">
                <span
                  className={`text-[11px] font-bold ${doc.status === "indexed" ? "text-green-600" : doc.status === "processing" ? "animate-pulse text-[#3525cd]" : "text-[#6a6780]"}`}
                >
                  {doc.status === "indexed"
                    ? tc("docStatusReady")
                    : doc.status === "processing"
                      ? tc("docStatusIndexing")
                      : doc.status}
                </span>
                {capabilities.canManageDocuments && !detail.is_dynamic ? (
                  <button
                    type="button"
                    aria-label={tc("removeAriaLabel")}
                    disabled={removeDocMutation.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          tc("removeDocConfirm", {
                            filename: doc.filename,
                          }),
                        )
                      ) {
                        removeDocMutation.mutate(doc.document_id);
                      }
                    }}
                    className="rounded p-1 text-[#b0abc8] transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40"
                  >
                    <span className="material-symbols-outlined text-[16px]">
                      remove_circle_outline
                    </span>
                  </button>
                ) : null}
              </div>
            </div>
          ))}

          {canLoadMore ? (
            <div className="flex items-center justify-between gap-3 pt-2">
              <span className="text-xs text-[#6a6780]">
                {tc("docsShowing", {
                  shown: docs.items.length,
                  total: docs.total,
                })}
              </span>
              <button
                type="button"
                onClick={() =>
                  setDocsLimit((current) =>
                    Math.min(current + COLLECTION_DOCS_PAGE_SIZE, docs.total),
                  )
                }
                className="rounded-lg border border-[#e4e1ee] px-3 py-1 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
              >
                {tc("loadMoreDocs")}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
