import Link from "next/link";
import { useTranslations } from "next-intl";

import { ScopeConnectorSection } from "@/components/chat/ScopeConnectorSection";
import { formatDate } from "@/components/chat/chat-format";
import { CONTEXT_MODAL_PAGE_SIZE } from "@/components/chat/chat-types";
import type { ChatScopeController } from "@/components/chat/hooks/useChatScope";
import type { ContextModalController } from "@/components/chat/hooks/useContextModal";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import type { DocumentListItemResponse } from "@/lib/api/documents";

/** Context scope picker modal: collections, connector sources, documents. */
export function ScopeControls({
  scope,
  contextModal,
}: {
  scope: ChatScopeController;
  contextModal: ContextModalController;
}) {
  const tc = useTranslations("chat.page");
  const {
    collectionsListQuery,
    collections,
    selectedCollectionIds,
    toggleCollection,
    filteredSelectedDocumentIds,
    toggleDocument,
    scopeMode,
    hasConnectorScopeSelection,
    contextScopeItemCount,
  } = scope;
  const {
    contextModalRef,
    contextSearchQuery,
    setContextSearchQuery,
    setContextPage,
    isContextModalOpen,
    setIsContextModalOpen,
    contextModalQuery,
    contextModalTotal,
    contextPageCount,
    boundedContextPage,
    contextPageStartIndex,
    contextPageEndIndex,
  } = contextModal;

  if (!isContextModalOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#1f1a3f]/45 p-4">
      <div
        ref={contextModalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-context-modal-title"
        className="max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-[#e2dff1] px-4 py-3">
          <div>
            <h2
              id="chat-context-modal-title"
              className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase"
            >
              {tc("contextModalTitle")}
            </h2>
            <p className="mt-1 text-xs text-[#6a6780]">
              {tc("contextModalSubtitle")}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setIsContextModalOpen(false);
              setContextSearchQuery("");
              setContextPage(1);
            }}
            className="rounded-lg border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            {tc("close")}
          </button>
        </div>
        <div className="border-b border-[#ece8f7] px-4 py-3">
          <div className="relative">
            <span
              className="material-symbols-outlined pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-[18px] text-[#6a6780]"
              aria-hidden="true"
            >
              search
            </span>
            <input
              type="text"
              value={contextSearchQuery}
              onChange={(event) => {
                setContextSearchQuery(event.target.value);
                setContextPage(1);
              }}
              placeholder={tc("contextSearchPlaceholder")}
              className="h-10 w-full rounded-lg border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-sm text-[#2f2a46] ring-[#3525cd]/20 outline-none focus:ring"
            />
          </div>
        </div>
        <div className="hide-scrollbar max-h-[52vh] overflow-y-auto px-4 py-3">
          <div className="mb-4 rounded-xl border border-[#e8e5f3] bg-[#faf9ff] p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div>
                <p className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                  {tc("collectionsTitle")}
                </p>
                <p className="text-xs text-[#6a6780]">
                  {tc("collectionsSubtitle")}
                </p>
              </div>
              <span className="rounded-full bg-[#ece8ff] px-2 py-1 text-[10px] font-semibold text-[#3525cd]">
                {tc("numSelected", { n: selectedCollectionIds.length })}
              </span>
            </div>
            {collectionsListQuery.isLoading ? (
              <LoadingState compact title={tc("loadingCollections")} />
            ) : collectionsListQuery.isError ? (
              <ErrorState
                compact
                error={collectionsListQuery.error}
                description={getApiErrorMessage(collectionsListQuery.error)}
                onRetry={() => {
                  void collectionsListQuery.refetch();
                }}
              />
            ) : collections.length === 0 ? (
              <p className="text-xs text-[#777587]">{tc("noCollections")}</p>
            ) : (
              <div className="space-y-2">
                {collections.map((collection) => {
                  const collectionSelected = selectedCollectionIds.includes(
                    collection.collection_id,
                  );
                  return (
                    <button
                      key={collection.collection_id}
                      type="button"
                      onClick={() => toggleCollection(collection.collection_id)}
                      className={`flex w-full items-start justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${
                        collectionSelected
                          ? "border-[#3525cd] bg-[#ece8ff]"
                          : "border-[#e2dff1] bg-white hover:bg-[#faf9ff]"
                      }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-[#2f2a46]">
                          {collection.name}
                        </span>
                        <span className="block text-[11px] text-[#6a6780]">
                          {collection.description ?? tc("collectionScopeHint")}
                        </span>
                      </span>
                      <span
                        className={`rounded-full px-2 py-1 text-[10px] font-semibold ${
                          collectionSelected
                            ? "bg-[#ece8ff] text-[#3525cd]"
                            : "bg-[#f1f0f5] text-[#6a6780]"
                        }`}
                      >
                        {collectionSelected
                          ? tc("collectionSelected")
                          : tc("collectionSelect")}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <ScopeConnectorSection scope={scope} />

          {contextModalQuery.isLoading ? (
            <LoadingState compact title={tc("loadingDocuments")} />
          ) : contextModalQuery.isError ? (
            <ErrorState
              compact
              error={contextModalQuery.error}
              description={getApiErrorMessage(contextModalQuery.error)}
              onRetry={() => {
                void contextModalQuery.refetch();
              }}
            />
          ) : contextModalQuery.data?.items.length === 0 &&
            !contextSearchQuery.trim() ? (
            <EmptyState
              compact
              title={tc("noDocumentsAvailable")}
              action={
                <Link
                  href="/documents"
                  className="text-sm font-semibold text-[#3525cd] hover:underline"
                >
                  {tc("goToDocuments")}
                </Link>
              }
            />
          ) : contextModalQuery.data?.items.length === 0 ? (
            <EmptyState
              compact
              title={tc("noDocumentsMatch")}
              description={tc("noDocumentsMatchHint")}
            />
          ) : (
            <ul className="space-y-2">
              {(contextModalQuery.data?.items ?? []).map((document) => (
                <DocumentSelectorItem
                  key={document.document_id}
                  document={document}
                  checked={filteredSelectedDocumentIds.includes(
                    document.document_id,
                  )}
                  onToggle={() => toggleDocument(document.document_id)}
                  chunksMeta={tc("documentChunks", {
                    count: document.chunk_count,
                    date: formatDate(document.updated_at),
                  })}
                />
              ))}
            </ul>
          )}
        </div>
        {contextModalTotal > CONTEXT_MODAL_PAGE_SIZE ? (
          <div className="flex items-center justify-between border-t border-[#ece8f7] px-4 py-3 text-xs text-[#5f5a74]">
            <p>
              {tc("contextShowingRange", {
                start: contextPageStartIndex,
                end: contextPageEndIndex,
                total: contextModalTotal,
              })}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setContextPage((previous) => Math.max(1, previous - 1));
                }}
                disabled={
                  boundedContextPage <= 1 || contextModalQuery.isFetching
                }
                className="rounded border border-[#d2cee6] px-2 py-1 font-semibold text-[#3525cd] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {tc("previous")}
              </button>
              <span className="font-mono text-[11px] text-[#4f4b63]">
                {tc("contextPageOf", {
                  page: boundedContextPage,
                  total: contextPageCount,
                })}
              </span>
              <button
                type="button"
                onClick={() => {
                  setContextPage((previous) =>
                    Math.min(contextPageCount, previous + 1),
                  );
                }}
                disabled={
                  boundedContextPage >= contextPageCount ||
                  contextModalQuery.isFetching
                }
                className="rounded border border-[#d2cee6] px-2 py-1 font-semibold text-[#3525cd] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {tc("next")}
              </button>
            </div>
          </div>
        ) : null}
        <div className="flex items-center justify-between border-t border-[#e2dff1] bg-[#faf9ff] px-4 py-3">
          {scopeMode === "collection" ? (
            selectedCollectionIds.length > 0 ? (
              <p className="text-xs text-[#5f5a74]">
                {tc("collectionsSelected", {
                  n: selectedCollectionIds.length,
                })}
              </p>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[#d7d4e8] bg-[#f0ecf9] px-2.5 py-1 text-xs font-semibold text-[#3525cd]">
                <span
                  className="material-symbols-outlined text-[14px]"
                  aria-hidden="true"
                >
                  folder_open
                </span>
                {tc("selectCollections")}
              </span>
            )
          ) : scopeMode === "connectors" ? (
            hasConnectorScopeSelection ? (
              <p className="text-xs text-[#5f5a74]">
                {tc("connectorSourcesSelected", {
                  count: contextScopeItemCount,
                })}
              </p>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[#d7d4e8] bg-[#f0ecf9] px-2.5 py-1 text-xs font-semibold text-[#3525cd]">
                <span
                  className="material-symbols-outlined text-[14px]"
                  aria-hidden="true"
                >
                  hub
                </span>
                {tc("selectConnectorSources")}
              </span>
            )
          ) : filteredSelectedDocumentIds.length > 0 ? (
            <p className="text-xs text-[#5f5a74]">
              {tc("documentsSelected", {
                count: filteredSelectedDocumentIds.length,
              })}
            </p>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#d7d4e8] bg-[#f0ecf9] px-2.5 py-1 text-xs font-semibold text-[#3525cd]">
              <span
                className="material-symbols-outlined text-[14px]"
                aria-hidden="true"
              >
                check_circle
              </span>
              {tc("allFilesIncluded", { count: contextScopeItemCount })}
            </span>
          )}
          <button
            type="button"
            onClick={() => {
              setIsContextModalOpen(false);
              setContextSearchQuery("");
              setContextPage(1);
            }}
            className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            {tc("done")}
          </button>
        </div>
      </div>
    </div>
  );
}

function DocumentSelectorItem({
  document,
  checked,
  onToggle,
  chunksMeta,
}: {
  document: DocumentListItemResponse;
  checked: boolean;
  onToggle: () => void;
  chunksMeta: string;
}) {
  return (
    <li>
      <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-sm text-[#2f2a46] transition hover:border-[#c9c3e6] hover:bg-white">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="mt-0.5 accent-[#3525cd]"
        />
        <span className="min-w-0">
          <span className="block truncate font-semibold">
            {document.filename}
          </span>
          <span className="mt-1 block text-xs text-[#6a6780]">
            {chunksMeta}
          </span>
        </span>
      </label>
    </li>
  );
}
