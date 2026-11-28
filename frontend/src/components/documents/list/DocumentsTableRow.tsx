"use client";

import Link from "next/link";

import type { DocumentListResponse } from "@/lib/api/documents";
import { canDeleteDocument, canReindexDocument } from "@/lib/documents-ui";

import {
  documentSourceIcon,
  documentSourceLabel,
  documentTypeIcon,
  documentTypeIconClass,
  formatDate,
  freshnessBadge,
  qualityBadge,
  statusBadge,
  truncateFilename,
} from "@/components/documents/list/documents-list-format";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

/** One documents table row with its selection checkbox and row actions. */
export function DocumentsTableRow({
  ctl,
  document,
}: {
  ctl: DocumentsPageController;
  document: DocumentListResponse["items"][number];
}) {
  const {
    freshnessFilterOptions,
    qualityFilterOptions,
    setAssignDocumentId,
    setAssignDocumentName,
    setAssignSaveError,
    tp,
    capabilities,
    setSelectedDocumentId,
    setChunksOffset,
    setActionFeedback,
    setActionRequestId,
    selectedIds,
    setSelectedIds,
    setDeleteModalState,
    reindexMutation,
    downloadMutation,
    pendingDeleteDocumentId,
    pendingReindexDocumentId,
    pendingDownloadDocumentId,
    currentListHref,
  } = ctl;
  const deleteEnabled =
    capabilities.canDelete && canDeleteDocument(document.status);
  const reindexEnabled =
    capabilities.canReindex && canReindexDocument(document.status);
  const downloadEnabled =
    document.status !== "deleted" && document.status !== "deleting";
  const deleteBusy = pendingDeleteDocumentId === document.document_id;
  const reindexBusy = pendingReindexDocumentId === document.document_id;
  const downloadBusy = pendingDownloadDocumentId === document.document_id;

  return (
    <tr
      key={document.document_id}
      className="group align-top transition-colors hover:bg-[#faf9ff]"
    >
      {capabilities.canDelete ? (
        <td className="px-4 py-3">
          <input
            type="checkbox"
            aria-label={tp("selectDocument", {
              filename: document.filename,
            })}
            checked={selectedIds.has(document.document_id)}
            disabled={!canDeleteDocument(document.status)}
            onChange={(e) => {
              setSelectedIds((prev) => {
                const next = new Set(prev);
                if (e.target.checked) {
                  next.add(document.document_id);
                } else {
                  next.delete(document.document_id);
                }
                return next;
              });
            }}
            className="h-4 w-4 rounded border-[#c9c6dc] text-[#3525cd] accent-[#3525cd] disabled:opacity-40"
          />
        </td>
      ) : null}
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <span
            className={`material-symbols-outlined ${documentTypeIconClass(document.file_type)}`}
          >
            {documentTypeIcon(document.file_type)}
          </span>
          <div>
            <p
              className="font-semibold text-[#1b1b24]"
              title={document.filename}
            >
              {truncateFilename(document.filename)}
            </p>
            {document.collections && document.collections.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {document.collections.map((c) => (
                  <span
                    key={c.collection_id}
                    className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold text-violet-800"
                  >
                    {c.name}
                  </span>
                ))}
              </div>
            ) : null}
            {document.tags && document.tags.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {document.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
            {document.error_message ? (
              <p className="mt-1 text-xs text-rose-700">
                {document.error_message}
              </p>
            ) : null}
          </div>
        </div>
      </td>
      <td className="px-4 py-3">
        {(() => {
          const providerKey = document.source_provider ?? document.source;
          const label = documentSourceLabel(
            providerKey,
            document.source_provider_label,
            tp("localUpload"),
          );
          return (
            <div className="flex items-center gap-1.5">
              <span className="material-symbols-outlined text-[16px] text-[#6a6780]">
                {documentSourceIcon(providerKey)}
              </span>
              <span className="text-xs whitespace-nowrap text-[#464555]">
                {label ?? tp("localUpload")}
              </span>
            </div>
          );
        })()}
      </td>
      <td className="px-4 py-3 text-sm font-medium text-[#505f76] uppercase">
        {document.file_type}
      </td>
      <td className="px-4 py-3">
        <span className={statusBadge(document.status)}>{document.status}</span>
      </td>
      <td className="px-4 py-3">
        <span className={freshnessBadge(document.review_status)}>
          {
            freshnessFilterOptions.find(
              (option) =>
                option.value === (document.review_status ?? "current"),
            )?.label
          }
        </span>
      </td>
      <td className="px-4 py-3">
        <span className={qualityBadge(document.quality_state)}>
          {
            qualityFilterOptions.find(
              (option) =>
                option.value === (document.quality_state ?? "unreviewed"),
            )?.label
          }
        </span>
      </td>
      <td className="px-4 py-3 text-center font-mono text-sm text-[#1b1b24]">
        {document.page_count ?? "-"}
      </td>
      <td className="px-4 py-3 text-center font-mono text-sm text-[#1b1b24]">
        {document.chunk_count}
      </td>
      <td className="px-4 py-3 text-sm text-[#68647b]">
        {formatDate(document.created_at)}
      </td>
      <td className="px-4 py-3 text-sm text-[#68647b]">
        {formatDate(document.updated_at)}
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-end gap-1 opacity-40 transition-opacity group-hover:opacity-100">
          <button
            type="button"
            aria-label={tp("inspect")}
            onClick={() => {
              setSelectedDocumentId(document.document_id);
              setChunksOffset(0);
              setActionFeedback(null);
              setActionRequestId(null);
            }}
            className="rounded p-1 text-[#3525cd] hover:bg-[#3525cd]/10"
          >
            <span className="material-symbols-outlined text-[18px]">
              visibility
            </span>
          </button>
          <Link
            aria-label={tp("viewDetail")}
            href={`/documents/${encodeURIComponent(document.document_id)}?back=${encodeURIComponent(currentListHref)}`}
            className="rounded p-1 text-[#3525cd] hover:bg-[#3525cd]/10"
          >
            <span className="material-symbols-outlined text-[18px]">
              open_in_new
            </span>
          </Link>
          <button
            type="button"
            aria-label={tp("download")}
            disabled={!downloadEnabled || downloadBusy}
            onClick={() => {
              downloadMutation.mutate({
                documentId: document.document_id,
                filename: document.filename,
              });
            }}
            className="rounded p-1 text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="material-symbols-outlined text-[18px]">
              download
            </span>
          </button>
          <button
            type="button"
            aria-label={tp("reindex")}
            disabled={!reindexEnabled || reindexBusy}
            onClick={() => {
              reindexMutation.mutate(document.document_id);
            }}
            className="rounded p-1 text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="material-symbols-outlined text-[18px]">
              refresh
            </span>
          </button>
          <button
            type="button"
            aria-label={tp("delete")}
            disabled={!deleteEnabled || deleteBusy}
            onClick={() => {
              setDeleteModalState({
                open: true,
                documentId: document.document_id,
                filenames: [document.filename],
              });
            }}
            className="rounded p-1 text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="material-symbols-outlined text-[18px]">
              delete
            </span>
          </button>
          <button
            type="button"
            aria-label={tp("assignCollections")}
            title={tp("assignCollections")}
            onClick={() => {
              setAssignDocumentId(document.document_id);
              setAssignDocumentName(document.filename);
              setAssignSaveError(null);
            }}
            className="rounded p-1 text-violet-700 hover:bg-violet-100"
          >
            <span className="material-symbols-outlined text-[18px]">
              folder_open
            </span>
          </button>
        </div>
      </td>
    </tr>
  );
}
