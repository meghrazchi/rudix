"use client";

import Link from "next/link";

import { buildPipelineExplorerHref } from "@/lib/pipeline-links";

import {
  graphStatusBadge,
  statusBadge,
} from "@/components/documents/detail/detail-format";
import type { DetailSectionProps } from "@/components/documents/detail/useDocumentDetail";

/** Filename, identifiers, status badges, and lifecycle actions. */
export function DocumentHeaderCard({
  ctl,
  detail,
  currentStatus,
}: DetailSectionProps) {
  const {
    documentId,
    td,
    capabilities,
    setActionFeedback,
    setActionRequestId,
    copyFeedback,
    copyMetadataValue,
    deleteMutation,
    reindexMutation,
    graphReindexMutation,
    safeBackHref,
    graphStatus,
    canDelete,
    canReindex,
    canForceReindex,
    canAskInChat,
    canShowMoreActions,
  } = ctl;
  return (
    <section className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-bold text-[#2a2640]">
              {detail.filename}
            </h2>
            <span className={statusBadge(currentStatus)}>
              {td(`statuses.${currentStatus}`)}
            </span>
            {graphStatus ? (
              <span className={graphStatusBadge(graphStatus)}>
                {td("graphStatus", {
                  status: td(`graphStatuses.${graphStatus}`),
                })}
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-[#5c5874]">
            <span className="break-all">
              {td("documentIdLabel")} {detail.document_id}
            </span>
            <button
              type="button"
              aria-label={td("copyDocumentId")}
              onClick={() => {
                void copyMetadataValue(detail.document_id, "document-id");
              }}
              className="inline-flex h-3 w-3 cursor-pointer items-center justify-center text-[#5b5484] hover:text-[#2f2a52]"
            >
              <span
                aria-hidden="true"
                className="material-symbols-outlined text-[9px] leading-none"
              >
                content_copy
              </span>
            </button>
            {copyFeedback?.field === "document-id" ? (
              <span
                className={`text-[10px] text-[#6b6594] transition-opacity duration-300 ${
                  copyFeedback.fading ? "opacity-0" : "opacity-100"
                }`}
              >
                {td("copied")}
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-[#5c5874]">
            <span className="break-all">
              {td("checksumLabel")} {detail.checksum ?? "-"}
            </span>
            <button
              type="button"
              aria-label={td("copyChecksum")}
              disabled={!detail.checksum}
              onClick={() => {
                void copyMetadataValue(detail.checksum ?? null, "checksum");
              }}
              className="inline-flex h-3 w-3 cursor-pointer items-center justify-center text-[#5b5484] hover:text-[#2f2a52] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span
                aria-hidden="true"
                className="material-symbols-outlined text-[9px] leading-none"
              >
                content_copy
              </span>
            </button>
            {copyFeedback?.field === "checksum" ? (
              <span
                className={`text-[10px] text-[#6b6594] transition-opacity duration-300 ${
                  copyFeedback.fading ? "opacity-0" : "opacity-100"
                }`}
              >
                {td("copied")}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Link
            href={safeBackHref}
            className="inline-flex items-center gap-1.5 rounded border border-[#cbc5e6] px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            <span
              aria-hidden="true"
              className="material-symbols-outlined text-[16px]"
            >
              arrow_back
            </span>
            {td("back")}
          </Link>
          {canAskInChat ? (
            <Link
              href={`/chat?document_id=${encodeURIComponent(documentId)}`}
              className="inline-flex items-center gap-1.5 rounded border border-[#cbc5e6] bg-white px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
            >
              <span
                aria-hidden="true"
                className="material-symbols-outlined text-[16px]"
              >
                forum
              </span>
              {td("askInChat")}
            </Link>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-500">
              <span
                aria-hidden="true"
                className="material-symbols-outlined text-[16px]"
              >
                forum
              </span>
              {td("askInChat")}
            </span>
          )}
          <Link
            href={buildPipelineExplorerHref({
              runType: "document.process",
              documentId,
            })}
            className="inline-flex items-center gap-1.5 rounded border border-[#cbc5e6] bg-white px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            <span
              aria-hidden="true"
              className="material-symbols-outlined text-[16px]"
            >
              account_tree
            </span>
            {td("viewPipeline")}
          </Link>
          {canShowMoreActions ? (
            <details className="relative">
              <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded border border-[#cbc5e6] bg-white px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] [&::-webkit-details-marker]:hidden">
                <span
                  aria-hidden="true"
                  className="material-symbols-outlined text-[16px]"
                >
                  more_horiz
                </span>
                {td("moreActions")}
              </summary>
              <div className="absolute right-0 z-20 mt-1 flex min-w-[10.5rem] flex-col gap-1 rounded-lg border border-[#d8d3ea] bg-white p-1 shadow-lg">
                {capabilities.canReindex ? (
                  <>
                    {canForceReindex ? (
                      <button
                        type="button"
                        disabled={reindexMutation.isPending}
                        onClick={(event) => {
                          (
                            event.currentTarget.closest(
                              "details",
                            ) as HTMLDetailsElement | null
                          )?.removeAttribute("open");
                          setActionFeedback(null);
                          setActionRequestId(null);
                          reindexMutation.mutate({ force: true });
                        }}
                        className="inline-flex w-full items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-left text-xs font-semibold text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <span
                          aria-hidden="true"
                          className="material-symbols-outlined text-[15px]"
                        >
                          restart_alt
                        </span>
                        {reindexMutation.isPending
                          ? td("reindexQueueing")
                          : td("forceReindex")}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      disabled={!canReindex || reindexMutation.isPending}
                      onClick={(event) => {
                        (
                          event.currentTarget.closest(
                            "details",
                          ) as HTMLDetailsElement | null
                        )?.removeAttribute("open");
                        setActionFeedback(null);
                        setActionRequestId(null);
                        reindexMutation.mutate({
                          label: td("reindexDefaultProfile"),
                        });
                      }}
                      className="inline-flex w-full items-center gap-2 rounded-md border border-[#cbc5e6] bg-white px-2.5 py-2 text-left text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <span
                        aria-hidden="true"
                        className="material-symbols-outlined text-[15px]"
                      >
                        refresh
                      </span>
                      {reindexMutation.isPending
                        ? td("reindexQueueing")
                        : td("reindex")}
                    </button>
                    <button
                      type="button"
                      disabled={!canReindex || graphReindexMutation.isPending}
                      onClick={(event) => {
                        (
                          event.currentTarget.closest(
                            "details",
                          ) as HTMLDetailsElement | null
                        )?.removeAttribute("open");
                        setActionFeedback(null);
                        setActionRequestId(null);
                        graphReindexMutation.mutate();
                      }}
                      className="inline-flex w-full items-center gap-2 rounded-md border border-[#cbc5e6] bg-white px-2.5 py-2 text-left text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <span
                        aria-hidden="true"
                        className="material-symbols-outlined text-[15px]"
                      >
                        schema
                      </span>
                      {graphReindexMutation.isPending
                        ? td("reindexQueueing")
                        : td("graphReindex")}
                    </button>
                  </>
                ) : null}
                {capabilities.canDelete ? (
                  <button
                    type="button"
                    disabled={!canDelete || deleteMutation.isPending}
                    onClick={(event) => {
                      const confirmed = window.confirm(
                        td("deleteConfirm", {
                          filename: detail.filename,
                        }),
                      );
                      if (!confirmed) {
                        return;
                      }
                      (
                        event.currentTarget.closest(
                          "details",
                        ) as HTMLDetailsElement | null
                      )?.removeAttribute("open");
                      setActionFeedback(null);
                      setActionRequestId(null);
                      deleteMutation.mutate();
                    }}
                    className="inline-flex w-full items-center gap-2 rounded-md border border-rose-200 bg-rose-50 px-2.5 py-2 text-left text-xs font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <span
                      aria-hidden="true"
                      className="material-symbols-outlined text-[15px]"
                    >
                      delete
                    </span>
                    {deleteMutation.isPending ? td("deleting") : td("delete")}
                  </button>
                ) : null}
              </div>
            </details>
          ) : null}
        </div>
      </div>
    </section>
  );
}
