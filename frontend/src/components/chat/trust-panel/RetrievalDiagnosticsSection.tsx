import { formatRange } from "@/components/chat/trust-panel/trust-format";
import type { RetrievalDiagnostics } from "@/components/chat/trust-panel/SourceSelectionSection";
import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { ChatDebugResponse } from "@/lib/api/chat";

export function RetrievalDiagnosticsSection({
  retrievalDiagnostics,
  debug,
}: {
  retrievalDiagnostics: NonNullable<RetrievalDiagnostics>;
  debug: ChatDebugResponse | null;
}) {
  return (
    <div className="space-y-2 px-4 pt-4 pb-4 md:px-6 md:pt-5 md:pb-5">
      <SectionHeader icon="manage_search" label="Retrieval Diagnostics" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        <StatRow
          label="Candidates"
          value={
            retrievalDiagnostics.retrieval_candidate_count ??
            retrievalDiagnostics.retrieval_count
          }
        />
        <StatRow
          label="Selected chunks"
          value={retrievalDiagnostics.selected_count ?? 0}
        />
        <StatRow label="Top-k" value={retrievalDiagnostics.top_k ?? null} />
        <StatRow
          label="Search mode"
          value={
            retrievalDiagnostics.search_mode ??
            retrievalDiagnostics.source_scope_mode
          }
        />
        <StatRow
          label="Scope mode"
          value={retrievalDiagnostics.source_scope_mode ?? null}
        />
        <StatRow
          label="Scope label"
          value={retrievalDiagnostics.source_scope_label ?? null}
        />
        <StatRow
          label="Profile"
          value={retrievalDiagnostics.retrieval_profile_name ?? null}
        />
        <StatRow
          label="Profile scope"
          value={retrievalDiagnostics.retrieval_profile_scope ?? null}
        />
        <StatRow
          label="Profile source"
          value={retrievalDiagnostics.retrieval_profile_source ?? null}
        />
        <StatRow
          label="Request ID"
          value={retrievalDiagnostics.request_id ?? null}
        />
        <StatRow
          label="Trace ID"
          value={retrievalDiagnostics.trace_request_id ?? null}
        />
        <StatRow
          label="Rerank score range"
          value={formatRange(
            retrievalDiagnostics.rerank_score_min,
            retrievalDiagnostics.rerank_score_max,
          )}
        />
      </div>
      {retrievalDiagnostics.retrieval_filters?.length ? (
        <div className="flex flex-wrap gap-1.5">
          {retrievalDiagnostics.retrieval_filters.map((filter) => (
            <span
              key={filter}
              className="rounded-full border border-[#d7d4e8] bg-[#faf9ff] px-2 py-0.5 text-[10px] font-medium text-[#6a6780]"
            >
              {filter}
            </span>
          ))}
        </div>
      ) : null}
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        {retrievalDiagnostics.hybrid_retrieval_enabled ? (
          <>
            <StatRow
              label="Vector hits"
              value={retrievalDiagnostics.hybrid_vector_hit_count ?? 0}
            />
            <StatRow
              label="Keyword hits"
              value={retrievalDiagnostics.hybrid_keyword_hit_count ?? 0}
            />
          </>
        ) : null}
        {retrievalDiagnostics.rerank_applied ? (
          <>
            <StatRow
              label="Reranker"
              value={
                retrievalDiagnostics.rerank_model ??
                retrievalDiagnostics.rerank_provider ??
                "Enabled"
              }
            />
            {retrievalDiagnostics.rerank_fallback_used ? (
              <StatRow
                label="Rerank fallback"
                value={retrievalDiagnostics.rerank_fallback_reason ?? "Yes"}
              />
            ) : null}
          </>
        ) : null}
        {debug?.parent_context_expansion_enabled ? (
          <>
            <StatRow
              label="Parent expansion"
              value={`${debug.parent_context_expanded_count ?? 0} chunks`}
            />
            {(debug.parent_context_tokens_used ?? 0) > 0 ? (
              <StatRow
                label="Parent tokens"
                value={debug.parent_context_tokens_used}
              />
            ) : null}
          </>
        ) : null}
        {debug?.freshness_filter_enabled ? (
          <>
            {(debug.freshness_boosted_count ?? 0) > 0 ? (
              <StatRow
                label="Freshness boosted"
                value={debug.freshness_boosted_count}
              />
            ) : null}
            {(debug.freshness_excluded_count ?? 0) > 0 ? (
              <StatRow
                label="Excluded (deprecated/expired)"
                value={debug.freshness_excluded_count}
              />
            ) : null}
            {(debug.freshness_stale_count ?? 0) > 0 ? (
              <StatRow
                label="Stale sources"
                value={debug.freshness_stale_count}
              />
            ) : null}
            {((debug as { freshness_unreviewed_count?: number })
              .freshness_unreviewed_count ?? 0) > 0 ? (
              <StatRow
                label="Unreviewed sources"
                value={
                  (debug as { freshness_unreviewed_count?: number })
                    .freshness_unreviewed_count
                }
              />
            ) : null}
            {((debug as { freshness_deprecated_count?: number })
              .freshness_deprecated_count ?? 0) > 0 ? (
              <StatRow
                label="Deprecated sources"
                value={
                  (debug as { freshness_deprecated_count?: number })
                    .freshness_deprecated_count
                }
              />
            ) : null}
            {(debug as { freshness_all_excluded_fallback?: boolean })
              .freshness_all_excluded_fallback ? (
              <StatRow label="All-excluded fallback" value="Yes" />
            ) : null}
          </>
        ) : null}
        {debug?.ocr_quality_downranking_enabled &&
        (debug.ocr_low_confidence_chunk_count ?? 0) > 0 ? (
          <StatRow
            label="OCR low-conf chunks"
            value={debug.ocr_low_confidence_chunk_count}
          />
        ) : null}
      </div>
    </div>
  );
}
