"use client";

import Link from "next/link";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import type { CollectionDetailResponse } from "@/lib/api/collections";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";

import { CollectionDrawerDocuments } from "@/components/collections/CollectionDrawerDocuments";
import { CollectionDrawerOverview } from "@/components/collections/CollectionDrawerOverview";
import { ManageCollectionDocumentsDialog } from "@/components/collections/ManageCollectionDocumentsDialog";
import { type CollectionCapabilities } from "@/components/collections/collection-format";
import { useCollectionDetailDrawer } from "@/components/collections/useCollectionDetailDrawer";

/** Side drawer with a collection's metadata, policy, and documents. */
export function CollectionDetailDrawer({
  collectionId,
  capabilities,
  onClose,
  onEdit,
}: {
  collectionId: string;
  capabilities: CollectionCapabilities;
  onClose: () => void;
  onEdit: (collection: CollectionDetailResponse) => void;
}) {
  const ctl = useCollectionDetailDrawer(collectionId);
  const {
    tc,
    isDocumentPickerOpen,
    setIsDocumentPickerOpen,
    documentSaveError,
    setDocumentSaveError,
    detailQuery,
    manageDocumentsMutation,
    existingDocumentIds,
    detail,
  } = ctl;

  return (
    <div className="fixed top-0 right-0 z-50 flex h-screen w-[480px] flex-col border-l border-[#e4e1ee] bg-white shadow-2xl">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[#e4e1ee] px-6 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-[#f0ecf9]"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
          <h3 className="truncate text-base font-semibold text-[#1b1b24]">
            {detail?.name ?? tc("drawerFallbackTitle")}
          </h3>
        </div>
        {detail && capabilities.canEdit ? (
          <button
            type="button"
            onClick={() => onEdit(detail)}
            className="ml-2 shrink-0 rounded-lg border border-[#e4e1ee] px-4 py-1.5 text-sm font-semibold text-[#2a2640] transition-colors hover:bg-[#f0ecf9]"
          >
            {tc("drawerEdit")}
          </button>
        ) : null}
      </div>

      {/* Scrollable content */}
      <div
        className="flex-1 space-y-6 overflow-y-auto p-6"
        style={{ scrollbarWidth: "thin" }}
      >
        {detailQuery.isLoading ? (
          <LoadingState title={tc("loadingCollection")} />
        ) : detailQuery.isError ? (
          isForbiddenError(detailQuery.error) ? (
            <ForbiddenState
              compact
              title={tc("drawerDeniedTitle")}
              description={tc("drawerDeniedDesc")}
              requestId={extractRequestIdFromError(detailQuery.error)}
            />
          ) : (
            <ErrorState
              compact
              error={detailQuery.error}
              description={getApiErrorMessage(detailQuery.error)}
              onRetry={() => void detailQuery.refetch()}
            />
          )
        ) : detail ? (
          <>
            <CollectionDrawerOverview
              ctl={ctl}
              detail={detail}
              capabilities={capabilities}
            />
            <CollectionDrawerDocuments
              ctl={ctl}
              detail={detail}
              capabilities={capabilities}
            />
          </>
        ) : null}
      </div>

      {/* Footer */}
      {detail ? (
        <div className="shrink-0 border-t border-[#e4e1ee] bg-[#f5f3ff] p-5">
          <Link
            href={`/chat?collection_id=${encodeURIComponent(collectionId)}`}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#3525cd] py-3 font-bold text-white transition-all hover:bg-[#2b1fa8]"
          >
            <span className="material-symbols-outlined">chat_bubble</span>
            {tc("openChatForCollection")}
          </Link>
        </div>
      ) : null}

      {isDocumentPickerOpen && detail ? (
        <ManageCollectionDocumentsDialog
          key={`${detail.collection_id}:${existingDocumentIds.join(",")}`}
          collectionName={detail.name}
          initialDocumentIds={existingDocumentIds}
          saving={manageDocumentsMutation.isPending}
          saveError={documentSaveError}
          onClose={() => {
            setIsDocumentPickerOpen(false);
            setDocumentSaveError(null);
          }}
          onSave={(documentIds) => manageDocumentsMutation.mutate(documentIds)}
        />
      ) : null}
    </div>
  );
}
