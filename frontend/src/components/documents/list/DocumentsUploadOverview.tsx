"use client";

import { ACCEPTED_UPLOAD_TYPES_LABEL } from "@/components/documents/upload-validation";
import { MAX_UPLOAD_SIZE_MB } from "@/components/documents/list/upload-batch";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

/** Read-only badge, upload drop zone, indexing status card, and upload feedback. */
export function DocumentsUploadOverview({
  ctl,
}: {
  ctl: DocumentsPageController;
}) {
  const {
    setIsUploadModalOpen,
    uploadFeedback,
    isPageDropActive,
    handlePageUploadDragOver,
    handlePageUploadDragLeave,
    handlePageUploadDrop,
    isReindexAllPending,
    handleReindexAllNonIndexedDocuments,
    tp,
    capabilities,
    reindexMutation,
    allDocumentsStatusCount,
    indexedStatusCount,
    processingStatusCount,
    failedStatusCount,
    reindexAllEligibleCount,
    indexedUsagePercent,
  } = ctl;
  return (
    <>
      {!capabilities.canUpload ? (
        <div className="flex justify-end">
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold tracking-wide text-slate-600 uppercase">
            {tp("readOnlyRole")}
          </span>
        </div>
      ) : null}

      <section className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-3">
        <button
          type="button"
          disabled={!capabilities.canUpload}
          onClick={() => setIsUploadModalOpen(true)}
          onDragOver={handlePageUploadDragOver}
          onDragLeave={handlePageUploadDragLeave}
          onDrop={(event) => {
            void handlePageUploadDrop(event);
          }}
          className={`group cursor-pointer rounded-xl border-2 border-dashed p-6 text-center transition-all disabled:cursor-not-allowed disabled:opacity-60 md:col-span-2 ${
            isPageDropActive
              ? "border-[#3525cd] bg-[#f1efff]"
              : "border-[#3525cd]/20 bg-white hover:border-[#3525cd] hover:bg-[#3525cd]/[0.02]"
          }`}
        >
          <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-full bg-[#3525cd]/10 transition-transform group-hover:scale-110">
            <span className="material-symbols-outlined text-3xl text-[#3525cd]">
              {isPageDropActive ? "upload_file" : "cloud_upload"}
            </span>
          </div>
          <h2 className="text-xl font-semibold text-[#1b1b24]">
            {tp("uploadTitle")}
          </h2>
          <p className="mx-auto mt-1 max-w-xl text-sm text-[#68647b]">
            {tp("uploadDescription", {
              types: ACCEPTED_UPLOAD_TYPES_LABEL,
              maxMb: MAX_UPLOAD_SIZE_MB,
            })}
          </p>
          <div className="mt-4 flex justify-center gap-2">
            <span className="rounded-full border border-[#e5e3f1] bg-[#f8f7ff] px-3 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b75] uppercase">
              PDF
            </span>
            <span className="rounded-full border border-[#e5e3f1] bg-[#f8f7ff] px-3 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b75] uppercase">
              DOCX
            </span>
            <span className="rounded-full border border-[#e5e3f1] bg-[#f8f7ff] px-3 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b75] uppercase">
              TXT
            </span>
          </div>
        </button>

        <aside className="relative overflow-hidden rounded-xl border border-[#e5e3f1] bg-white p-4 shadow-sm">
          <p className="mb-3 text-xs font-bold tracking-[0.08em] text-[#3525cd] uppercase">
            {tp("indexingStatus")}
          </p>
          <div className="space-y-3">
            <div className="flex items-end justify-between">
              <span className="text-sm text-[#68647b]">{tp("totalFiles")}</span>
              <span className="text-2xl font-bold text-[#1b1b24]">
                {allDocumentsStatusCount.toLocaleString()}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-[#efecf9]">
              <div
                className="h-full bg-[#3525cd] transition-all"
                style={{ width: `${indexedUsagePercent}%` }}
              />
            </div>
            <p className="text-xs text-[#68647b]">
              {tp("indexedCount", { count: indexedStatusCount })} •{" "}
              {tp("processingCount", { count: processingStatusCount })} •{" "}
              {tp("failedCount", { count: failedStatusCount })}
            </p>
            <button
              type="button"
              onClick={() => {
                void handleReindexAllNonIndexedDocuments();
              }}
              disabled={
                !capabilities.canReindex ||
                reindexMutation.isPending ||
                isReindexAllPending ||
                reindexAllEligibleCount <= 0
              }
              className="w-full rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isReindexAllPending ? tp("reindexAllQueuing") : tp("reindexAll")}
            </button>
          </div>
        </aside>
      </section>

      {uploadFeedback ? (
        <p
          role="status"
          className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
        >
          {tp("lastUploadState")}{" "}
          <span className="font-semibold uppercase">
            {uploadFeedback.state}
          </span>{" "}
          — {uploadFeedback.message}
          {uploadFeedback.requestId
            ? ` (Trace ID: ${uploadFeedback.requestId})`
            : ""}
        </p>
      ) : null}
    </>
  );
}
