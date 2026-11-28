"use client";

import { useState } from "react";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  listDocuments,
  type DocumentListItemResponse,
} from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";

import { COLLECTION_PICKER_PAGE_SIZE } from "@/components/collections/collection-format";

type ManageCollectionDocumentsDialogProps = {
  collectionName: string;
  initialDocumentIds: string[];
  saving: boolean;
  saveError: string | null;
  onClose: () => void;
  onSave: (documentIds: string[]) => void;
};

/** Paged, searchable picker of indexed documents for a manual collection. */
export function ManageCollectionDocumentsDialog({
  collectionName,
  initialDocumentIds,
  saving,
  saveError,
  onClose,
  onSave,
}: ManageCollectionDocumentsDialogProps) {
  const tc = useTranslations("collections.page");
  const [searchQuery, setSearchQuery] = useState("");
  const [pageOffset, setPageOffset] = useState(0);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(
    () => new Set(initialDocumentIds),
  );

  const documentsQuery = useQuery({
    queryKey: queryKeys.documentViews.collectionPicker(
      searchQuery.trim(),
      pageOffset,
    ),
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: COLLECTION_PICKER_PAGE_SIZE,
        offset: pageOffset,
        filename_query: searchQuery.trim() || undefined,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
    placeholderData: (previous) => previous,
  });

  const documents = documentsQuery.data?.items ?? [];
  const totalDocuments = documentsQuery.data?.total ?? 0;
  const currentPage = Math.floor(pageOffset / COLLECTION_PICKER_PAGE_SIZE) + 1;
  const totalPages = Math.max(
    1,
    Math.ceil(totalDocuments / COLLECTION_PICKER_PAGE_SIZE),
  );
  const canGoPrev = pageOffset > 0;
  const canGoNext = pageOffset + COLLECTION_PICKER_PAGE_SIZE < totalDocuments;
  const selectedCount = selectedDocumentIds.size;
  const selectedOnPage = documents.filter((document) =>
    selectedDocumentIds.has(document.document_id),
  );
  const allOnPageSelected =
    documents.length > 0 && selectedOnPage.length === documents.length;
  const someOnPageSelected =
    selectedOnPage.length > 0 && selectedOnPage.length < documents.length;

  function toggleDocument(documentId: string) {
    setSelectedDocumentIds((previous) => {
      const next = new Set(previous);
      if (next.has(documentId)) {
        next.delete(documentId);
      } else {
        next.add(documentId);
      }
      return next;
    });
  }

  function togglePageSelection() {
    setSelectedDocumentIds((previous) => {
      const next = new Set(previous);
      if (allOnPageSelected) {
        for (const document of documents) {
          next.delete(document.document_id);
        }
      } else {
        for (const document of documents) {
          next.add(document.document_id);
        }
      }
      return next;
    });
  }

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-[#17172a]/40 px-4"
      onClick={onClose}
    >
      <div
        className="flex w-full max-w-2xl flex-col rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">
              {tc("manageDocumentsTitle")}
            </h2>
            <p className="text-sm text-[#68647b]">{collectionName}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            {tc("cancel")}
          </button>
        </div>

        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="relative flex-1">
            <span className="material-symbols-outlined absolute top-1/2 left-3 -translate-y-1/2 text-[20px] text-[#9993b8]">
              search
            </span>
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => {
                setSearchQuery(event.target.value);
                setPageOffset(0);
              }}
              placeholder={tc("manageDocumentsSearchPlaceholder")}
              className="h-10 w-full rounded-xl border border-[#d2cee6] bg-white pr-3 pl-10 text-sm text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            />
          </div>
          <span className="rounded-full bg-[#f3f1ff] px-3 py-1 text-xs font-semibold text-[#3525cd]">
            {tc("manageDocumentsSelected", { n: selectedCount })}
          </span>
        </div>

        <div className="mb-3 flex items-center justify-between gap-3 rounded-2xl border border-[#e4e1ee] bg-[#faf9ff] px-3 py-2 text-xs text-[#6a6780]">
          <label className="flex cursor-pointer items-center gap-2 font-semibold text-[#2a2640]">
            <input
              type="checkbox"
              checked={allOnPageSelected}
              ref={(input) => {
                if (input) {
                  input.indeterminate = someOnPageSelected;
                }
              }}
              onChange={togglePageSelection}
              className="accent-[#3525cd]"
            />
            <span>{tc("selectAllOnPage")}</span>
          </label>
          <span className="font-semibold">
            {tc("pageOf", { page: currentPage, total: totalPages })}
          </span>
        </div>

        <div className="max-h-[28rem] overflow-y-auto rounded-2xl border border-[#e4e1ee] bg-[#faf9ff] p-3">
          {documentsQuery.isLoading ? (
            <LoadingState compact title={tc("loadingDocuments")} />
          ) : documentsQuery.isError ? (
            <ErrorState
              compact
              error={documentsQuery.error}
              description={getApiErrorMessage(documentsQuery.error)}
              onRetry={() => void documentsQuery.refetch()}
            />
          ) : documents.length === 0 ? (
            <EmptyState
              compact
              title={tc("noDocumentsTitle")}
              description={tc("manageDocumentsNoMatch")}
            />
          ) : (
            <div className="space-y-2">
              {documents.map((document: DocumentListItemResponse) => {
                const selected = selectedDocumentIds.has(document.document_id);
                return (
                  <button
                    key={document.document_id}
                    type="button"
                    onClick={() => toggleDocument(document.document_id)}
                    className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2 text-left transition-colors ${
                      selected
                        ? "border-[#3525cd] bg-[#ece8ff]"
                        : "border-[#e2dff1] bg-white hover:bg-[#f7f5ff]"
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-[#2a2640]">
                        {document.filename}
                      </span>
                      <span className="mt-0.5 block text-xs text-[#6a6780]">
                        {document.source_provider_label ??
                          tc("documentSourceFallback")}
                      </span>
                    </span>
                    <span className="rounded-full bg-[#f1f0f5] px-2 py-1 text-[10px] font-semibold text-[#6a6780]">
                      {selected ? tc("selected") : tc("select")}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {totalDocuments > COLLECTION_PICKER_PAGE_SIZE ? (
          <div className="mt-3 flex items-center justify-between gap-3">
            <button
              type="button"
              disabled={!canGoPrev}
              onClick={() =>
                setPageOffset((previous) =>
                  Math.max(0, previous - COLLECTION_PICKER_PAGE_SIZE),
                )
              }
              className="rounded-lg border border-[#e4e1ee] px-3 py-1.5 text-xs font-semibold text-[#3e376f] disabled:opacity-40"
            >
              {tc("previousDocs")}
            </button>
            <span className="text-xs text-[#6a6780]">
              {tc("docsShowing", {
                shown: documents.length,
                total: totalDocuments,
              })}
            </span>
            <button
              type="button"
              disabled={!canGoNext}
              onClick={() =>
                setPageOffset((previous) =>
                  Math.min(
                    previous + COLLECTION_PICKER_PAGE_SIZE,
                    Math.max(0, (totalPages - 1) * COLLECTION_PICKER_PAGE_SIZE),
                  ),
                )
              }
              className="rounded-lg border border-[#e4e1ee] px-3 py-1.5 text-xs font-semibold text-[#3e376f] disabled:opacity-40"
            >
              {tc("nextDocs")}
            </button>
          </div>
        ) : null}

        {saveError ? (
          <p className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {saveError}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[#d2cee6] bg-white px-4 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
          >
            {tc("cancel")}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => onSave(Array.from(selectedDocumentIds))}
            className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? tc("saving") : tc("updateDocuments")}
          </button>
        </div>
      </div>
    </div>
  );
}
