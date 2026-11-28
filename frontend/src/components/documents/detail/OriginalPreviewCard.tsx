"use client";

import { documentTypeIcon } from "@/components/documents/detail/detail-format";
import type { DetailSectionProps } from "@/components/documents/detail/useDocumentDetail";

/** Original file preview card with the download action. */
export function OriginalPreviewCard({
  ctl,
  detail,
}: Omit<DetailSectionProps, "currentStatus">) {
  const {
    td,
    setActionFeedback,
    setActionRequestId,
    downloadMutation,
    canDownloadOriginal,
  } = ctl;
  return (
    <section className="rounded-xl border border-[#e4e1f2] bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-base font-bold text-[#2a2640]">
        {td("previewTitle")}
      </h3>
      <div className="rounded-2xl border border-dashed border-[#d7d4e8] bg-white p-4">
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="flex h-32 w-24 items-center justify-center rounded-lg border border-[#ddd7f6] bg-[#faf9ff] shadow-sm">
            <span className="material-symbols-outlined text-[44px] text-[#3525cd]">
              {documentTypeIcon(detail.file_type)}
            </span>
          </div>
          <div className="space-y-1">
            <p className="text-sm font-semibold text-[#2a2640]">
              {td("viewOriginal", {
                type: detail.file_type.toUpperCase(),
              })}
            </p>
            <p className="font-mono text-xs break-all text-[#6e6a86]">
              Source endpoint: /api/v1/documents/{detail.document_id}
              /download
            </p>
          </div>
          <button
            type="button"
            disabled={!canDownloadOriginal || downloadMutation.isPending}
            onClick={() => {
              setActionFeedback(null);
              setActionRequestId(null);
              downloadMutation.mutate();
            }}
            className="inline-flex items-center gap-2 rounded border border-[#cbc5e6] bg-white px-3 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="material-symbols-outlined text-[18px]">
              download
            </span>
            {downloadMutation.isPending ? td("downloading") : td("download")}
          </button>
        </div>
      </div>
    </section>
  );
}
