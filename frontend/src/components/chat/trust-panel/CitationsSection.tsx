import {
  conflictBadge,
  extractionQualityBadge,
  freshnessBadge,
  ocrBadge,
  processingWarningBadge,
  tableExtractionBadge,
  trustStatusBadge,
} from "@/components/chat/trust-panel/trust-badges";
import { fmtDate, score } from "@/components/chat/trust-panel/trust-format";
import type { TrustPanelCitation } from "@/components/chat/trust-panel/trust-types";
import { SectionHeader } from "@/components/chat/trust-panel/TrustPrimitives";
import { trackFeatureEvent } from "@/lib/analytics";

export function CitationsSection({
  trustCitations,
  messageId,
  onOpenCitation,
}: {
  trustCitations: TrustPanelCitation[];
  messageId: string;
  onOpenCitation: (citation: TrustPanelCitation) => void;
}) {
  return (
    <>
      {trustCitations.length > 0 && (
        <div className="space-y-2 px-4 pt-4 md:px-6 md:pt-5">
          <SectionHeader
            icon="source"
            label={`Sources (${trustCitations.length})`}
          />
          <div className="space-y-1.5">
            {trustCitations.map((citation, ci) => {
              const title =
                citation.source_title ??
                citation.filename ??
                "Unknown document";
              const trust = trustStatusBadge(citation.source_trust_status);
              const ocr = ocrBadge(
                citation.doc_ocr_quality_status,
                citation.doc_ocr_low_confidence_warning,
              );
              const conflict = conflictBadge(citation.conflict_status);
              const pageRef = citation.page_number
                ? `p. ${citation.page_number}`
                : (citation.source_section ?? null);
              const citExt = citation as {
                freshness_state?: string | null;
                doc_last_updated_at?: string | null;
                doc_unreviewed_warning?: boolean;
                doc_deprecated_warning?: boolean;
                doc_version_label?: string | null;
                source_last_synced_at?: string | null;
                table_low_confidence_warning?: boolean;
                doc_extraction_quality?: string | null;
                doc_extraction_warning?: boolean;
                doc_processing_warning?: boolean;
              };
              const freshness = freshnessBadge(
                citExt.freshness_state,
                citation.doc_stale_warning,
                citation.doc_expired_warning,
                citExt.doc_unreviewed_warning,
                citExt.doc_deprecated_warning,
              );
              const tableConfBadge = tableExtractionBadge(
                citExt.table_low_confidence_warning,
              );
              const extractionBadge = extractionQualityBadge(
                citExt.doc_extraction_quality,
                citExt.doc_extraction_warning,
              );
              const processingBadge = processingWarningBadge(
                citExt.doc_processing_warning,
              );
              const lastUpdated = fmtDate(citExt.doc_last_updated_at);
              const lastSynced = fmtDate(citExt.source_last_synced_at);
              const versionLabel = citExt.doc_version_label;
              return (
                <div
                  key={`tp:${citation.document_id}:${citation.chunk_id}:${ci}`}
                  className="flex items-start justify-between gap-2 rounded-lg border border-[#e2dff1] bg-white px-3 py-2"
                  data-freshness-state={citExt.freshness_state ?? undefined}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[11px] font-medium text-[#1b1b24]">
                      {title}
                      {versionLabel ? (
                        <span className="ml-1 text-[10px] font-normal text-[#9d98b5]">
                          v{versionLabel}
                        </span>
                      ) : null}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      {pageRef ? (
                        <span className="text-[10px] text-[#9d98b5]">
                          {pageRef}
                        </span>
                      ) : null}
                      {trust ? (
                        <span className={trust.cls}>{trust.label}</span>
                      ) : null}
                      {freshness ? (
                        <span
                          className={freshness.cls}
                          data-testid="freshness-state-badge"
                        >
                          {freshness.label}
                        </span>
                      ) : null}
                      {ocr ? (
                        <span className={ocr.cls}>{ocr.label}</span>
                      ) : null}
                      {tableConfBadge ? (
                        <span
                          className={tableConfBadge.cls}
                          data-testid="table-low-confidence-badge"
                        >
                          {tableConfBadge.label}
                        </span>
                      ) : null}
                      {extractionBadge ? (
                        <span
                          className={extractionBadge.cls}
                          data-testid="extraction-warning-badge"
                        >
                          {extractionBadge.label}
                        </span>
                      ) : null}
                      {processingBadge ? (
                        <span
                          className={processingBadge.cls}
                          data-testid="processing-warning-badge"
                        >
                          {processingBadge.label}
                        </span>
                      ) : null}
                      {conflict ? (
                        <span className={conflict.cls}>{conflict.label}</span>
                      ) : null}
                    </div>
                    {lastUpdated || lastSynced ? (
                      <p className="mt-0.5 text-[10px] text-[#9d98b5]">
                        {lastUpdated ? `Updated ${lastUpdated}` : null}
                        {lastUpdated && lastSynced ? " · " : null}
                        {lastSynced ? `Synced ${lastSynced}` : null}
                      </p>
                    ) : null}
                    {typeof citation.score === "number" ? (
                      <p className="mt-0.5 text-[10px] text-[#9d98b5]">
                        Score {score(citation.score)}
                        {typeof citation.rerank_score === "number"
                          ? ` · Rerank ${score(citation.rerank_score)}`
                          : ""}
                        {citation.is_table_chunk ? " · Table" : ""}
                      </p>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    aria-label={`Preview ${title}`}
                    onClick={() => {
                      void trackFeatureEvent(
                        "feature.chat.trust_panel_citation_clicked",
                        {
                          surface: "app",
                          route: "/chat",
                          pageKey: "chat",
                          featureArea: "chat",
                          entityId: messageId,
                          source: "trust_panel",
                        },
                      );
                      onOpenCitation(citation);
                    }}
                    className="shrink-0 self-center rounded-md p-1 text-[#9d98b5] transition-colors hover:bg-[#ede9f9] hover:text-[#3525cd]"
                  >
                    <span
                      className="material-symbols-outlined text-[14px]"
                      aria-hidden="true"
                    >
                      open_in_new
                    </span>
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
