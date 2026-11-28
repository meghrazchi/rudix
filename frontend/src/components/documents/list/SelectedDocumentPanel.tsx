"use client";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError } from "@/lib/forbidden";

import {
  CHUNK_PAGE_SIZE,
  deriveDetailStatus,
  formatDate,
  freshnessBadge,
  statusBadge,
} from "@/components/documents/list/documents-list-format";
import { ListMetricCard as MetricCard } from "@/components/documents/list/ListMetricCard";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

/** Inline detail and chunk preview of the inspected document. */
export function SelectedDocumentPanel({
  ctl,
}: {
  ctl: DocumentsPageController;
}) {
  const {
    freshnessFilterOptions,
    tp,
    selectedDocumentId,
    setSelectedDocumentId,
    setChunksOffset,
    detailQuery,
    statusQuery,
    chunksQuery,
    selectedDetail,
    selectedStatus,
    selectedChunks,
    detailForbidden,
    canGoPrevChunks,
    canGoNextChunks,
  } = ctl;
  if (!selectedDocumentId) {
    return null;
  }
  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-lg font-bold text-[#2a2640]">
          {tp("detailTitle")}
        </h2>
        <button
          type="button"
          onClick={() => setSelectedDocumentId(null)}
          className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f]"
        >
          {tp("close")}
        </button>
      </div>

      {detailQuery.isLoading ? (
        <LoadingState title={tp("loadingDetails")} />
      ) : null}

      {(detailQuery.isError || statusQuery.isError) && detailForbidden ? (
        <ForbiddenState
          compact
          title={tp("detailAccessDenied")}
          description={tp("detailAccessDeniedDesc")}
          requestId={extractRequestIdFromError(
            detailQuery.error ?? statusQuery.error,
          )}
        />
      ) : null}

      {detailQuery.isError && !detailForbidden ? (
        <ErrorState
          error={detailQuery.error}
          description={getApiErrorMessage(detailQuery.error)}
        />
      ) : null}

      {selectedDetail ? (
        <div className="space-y-4">
          {selectedDetail.review_status &&
          ["stale", "expired", "needs_review", "archived"].includes(
            selectedDetail.review_status,
          ) ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {tp("freshnessWarning", {
                status:
                  freshnessFilterOptions.find(
                    (option) => option.value === selectedDetail.review_status,
                  )?.label ?? selectedDetail.review_status,
              })}
            </p>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <MetricCard
              label={tp("tableFilename")}
              value={selectedDetail.filename}
            />
            <MetricCard
              label={tp("tableType")}
              value={selectedDetail.file_type.toUpperCase()}
            />
            <MetricCard
              label={tp("tableStatus")}
              value={deriveDetailStatus(selectedDetail, selectedStatus)}
              valueClass={statusBadge(
                deriveDetailStatus(selectedDetail, selectedStatus),
              )}
              plain={false}
            />
            <MetricCard
              label={tp("tableUpdated")}
              value={formatDate(selectedDetail.updated_at)}
            />
            <MetricCard
              label={tp("freshnessLabel")}
              value={
                freshnessFilterOptions.find(
                  (option) =>
                    option.value ===
                    (selectedDetail.review_status ?? "current"),
                )?.label ?? tp("freshnessCurrent")
              }
              valueClass={freshnessBadge(selectedDetail.review_status)}
              plain={false}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <MetricCard
              label={tp("tablePages")}
              value={selectedDetail.page_count ?? "-"}
            />
            <MetricCard
              label={tp("tableChunks")}
              value={selectedDetail.chunk_count}
            />
            <MetricCard
              label={tp("metricChecksum")}
              value={selectedDetail.checksum ?? "-"}
              mono
            />
          </div>

          {selectedDetail.error_message ? (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {selectedDetail.error_message}
            </p>
          ) : null}

          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <h3 className="text-base font-bold text-[#2a2640]">
                {tp("chunkPreviews")}
              </h3>
              {chunksQuery.isFetching ? (
                <span className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  {tp("refreshing")}
                </span>
              ) : null}
            </div>

            {chunksQuery.isLoading ? (
              <LoadingState compact title={tp("loadingChunks")} />
            ) : null}

            {chunksQuery.isError ? (
              <ErrorState
                compact
                error={chunksQuery.error}
                description={getApiErrorMessage(chunksQuery.error)}
              />
            ) : null}

            {selectedChunks && selectedChunks.items.length === 0 ? (
              <EmptyState compact title={tp("noChunksYet")} />
            ) : null}

            {selectedChunks && selectedChunks.items.length > 0 ? (
              <div className="space-y-2">
                {selectedChunks.items.map((chunk) => (
                  <article
                    key={chunk.chunk_id}
                    className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-3"
                  >
                    <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                      <span>
                        {tp("chunkIndex", { index: chunk.chunk_index })}
                      </span>
                      <span>
                        {tp("chunkPage", { n: chunk.page_number ?? "-" })}
                      </span>
                      <span>{tp("chunkTokens", { n: chunk.token_count })}</span>
                    </div>
                    <p className="text-sm text-[#2a2640]">
                      {chunk.text_preview}
                    </p>
                  </article>
                ))}
                <div className="mt-2 flex items-center justify-between gap-2">
                  <p className="text-xs text-[#6e6a86]">
                    {tp("showingChunks", {
                      shown: selectedChunks.items.length,
                      total: selectedChunks.total,
                    })}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={!canGoPrevChunks}
                      onClick={() =>
                        setChunksOffset((current) =>
                          Math.max(0, current - CHUNK_PAGE_SIZE),
                        )
                      }
                      className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {tp("previous")}
                    </button>
                    <button
                      type="button"
                      disabled={!canGoNextChunks}
                      onClick={() =>
                        setChunksOffset((current) => current + CHUNK_PAGE_SIZE)
                      }
                      className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {tp("next")}
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
