"use client";

import { DocumentChunkingDiagnosticsPanel } from "@/components/documents/DocumentChunkingDiagnosticsPanel";
import { DocumentExtractionDiagnosticsPanel } from "@/components/documents/DocumentExtractionDiagnosticsPanel";
import { DocumentGraphInsightsPanel } from "@/components/documents/DocumentGraphInsightsPanel";
import { DocumentLanguagePanel } from "@/components/documents/detail/DocumentLanguagePanel";
import { DocumentOcrPanels } from "@/components/documents/detail/DocumentOcrPanels";
import {
  formatDate,
  statusBadge,
} from "@/components/documents/detail/detail-format";
import type { DetailSectionProps } from "@/components/documents/detail/useDocumentDetail";

/** Overview tab: errors, file summary, indexing, OCR, language, diagnostics. */
export function DocumentOverviewTab({
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
    reindexMutation,
    graphReindexMutation,
    graphStatus,
    selectedChunks,
    chunkingIssueCount,
    canReindex,
  } = ctl;
  return (
    <div className="space-y-4">
      {detail.error_message ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-3 text-sm text-rose-800">
          <p className="font-semibold">{td("processingError")}</p>
          <p className="mt-1">{detail.error_message}</p>
          {detail.error_details ? (
            <ul className="mt-2 space-y-1 text-xs">
              <li>
                <span className="font-semibold">{td("errorStage")}</span>{" "}
                {detail.error_details.stage}
              </li>
              <li>
                <span className="font-semibold">{td("errorCode")}</span>{" "}
                {detail.error_details.code}
              </li>
              <li>
                <span className="font-semibold">{td("errorCategory")}</span>{" "}
                {detail.error_details.category}
              </li>
              <li>
                <span className="font-semibold">{td("errorRetryable")}</span>{" "}
                {detail.error_details.retryable
                  ? td("errorYes")
                  : td("errorNo")}
              </li>
              <li>
                <span className="font-semibold">{td("errorMessage")}</span>{" "}
                {detail.error_details.message}
              </li>
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
          <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {td("fileSummary")}
          </h4>
          <div className="space-y-2 text-sm text-[#2a2640]">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("filenameLabel")}</span>
              <span className="font-semibold">{detail.filename}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("fileTypeLabel")}</span>
              <span className="font-semibold">
                {detail.file_type.toUpperCase()}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("createdLabel")}</span>
              <span className="font-semibold">
                {formatDate(detail.created_at)}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("updatedLabel")}</span>
              <span className="font-semibold">
                {formatDate(detail.updated_at)}
              </span>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
          <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {td("indexingIntelligence")}
          </h4>
          <div className="space-y-2 text-sm text-[#2a2640]">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("statusLabel")}</span>
              <span className={statusBadge(currentStatus)}>
                {currentStatus}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("embeddingModel")}</span>
              <span className="font-semibold">
                {selectedChunks?.items[0]?.embedding_model ?? "-"}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("indexVersion")}</span>
              <span className="font-semibold">
                {selectedChunks?.items[0]?.index_version ?? "-"}
              </span>
            </div>
            {detail.embedding_provider_type && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-[#69637f]">
                  {td("embeddingProvider")}
                </span>
                <span className="font-semibold">
                  {detail.embedding_provider_type}
                </span>
              </div>
            )}
            {detail.embedding_vector_dimension != null && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-[#69637f]">{td("vectorDimension")}</span>
                <span className="font-semibold">
                  {detail.embedding_vector_dimension}
                </span>
              </div>
            )}
            <div className="flex items-center justify-between gap-3">
              <span className="text-[#69637f]">{td("pipelineSurface")}</span>
              <span className="font-semibold">{td("backendWorker")}</span>
            </div>
          </div>
        </div>
      </div>

      <DocumentOcrPanels ctl={ctl} detail={detail} />
      <DocumentLanguagePanel ctl={ctl} detail={detail} />

      {/* Extraction diagnostics (F237) */}
      {detail.file_type === "pdf" && detail.extraction_snapshot ? (
        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
          <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {td("extractionDiagnostics")}
          </h4>
          <DocumentExtractionDiagnosticsPanel
            snapshot={detail.extraction_snapshot}
          />
        </div>
      ) : null}

      <DocumentChunkingDiagnosticsPanel
        documentId={documentId}
        detail={detail}
        canReindex={canReindex}
        isReindexPending={reindexMutation.isPending}
        chunkingIssueCount={chunkingIssueCount}
        onQueueReindex={(payload, label) => {
          setActionFeedback(null);
          setActionRequestId(null);
          reindexMutation.mutate({ payload, label });
        }}
      />

      <DocumentGraphInsightsPanel
        documentId={documentId}
        graphExtractionStatus={graphStatus}
        canReindex={canReindex && capabilities.canReindex}
        isReindexPending={graphReindexMutation.isPending}
        onReindexGraph={() => {
          setActionFeedback(null);
          setActionRequestId(null);
          graphReindexMutation.mutate();
        }}
      />

      <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
        <h4 className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {td("aiSummary")}
        </h4>
        <p className="text-sm leading-relaxed text-[#2a2640]">
          {td("aiSummaryBody", {
            status: currentStatus,
            chunks: detail.chunk_count,
            pages:
              detail.page_count != null
                ? td("acrossPages", {
                    pages: detail.page_count,
                  })
                : "",
          })}
        </p>
      </div>
    </div>
  );
}
