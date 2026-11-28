import { useTranslations } from "next-intl";

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
  const t = useTranslations("chat.trustPanel");
  return (
    <div className="space-y-2 px-4 pt-4 pb-4 md:px-6 md:pt-5 md:pb-5">
      <SectionHeader icon="manage_search" label={t("diag.title")} />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        <StatRow
          label={t("diag.candidates")}
          value={
            retrievalDiagnostics.retrieval_candidate_count ??
            retrievalDiagnostics.retrieval_count
          }
        />
        <StatRow
          label={t("diag.selectedChunks")}
          value={retrievalDiagnostics.selected_count ?? 0}
        />
        <StatRow
          label={t("diag.topK")}
          value={retrievalDiagnostics.top_k ?? null}
        />
        <StatRow
          label={t("diag.searchMode")}
          value={
            retrievalDiagnostics.search_mode ??
            retrievalDiagnostics.source_scope_mode
          }
        />
        <StatRow
          label={t("diag.scopeMode")}
          value={retrievalDiagnostics.source_scope_mode ?? null}
        />
        <StatRow
          label={t("diag.scopeLabel")}
          value={retrievalDiagnostics.source_scope_label ?? null}
        />
        <StatRow
          label={t("diag.profile")}
          value={retrievalDiagnostics.retrieval_profile_name ?? null}
        />
        <StatRow
          label={t("diag.profileScope")}
          value={retrievalDiagnostics.retrieval_profile_scope ?? null}
        />
        <StatRow
          label={t("diag.profileSource")}
          value={retrievalDiagnostics.retrieval_profile_source ?? null}
        />
        <StatRow
          label={t("diag.requestId")}
          value={retrievalDiagnostics.request_id ?? null}
        />
        <StatRow
          label={t("diag.traceId")}
          value={retrievalDiagnostics.trace_request_id ?? null}
        />
        <StatRow
          label={t("diag.rerankRange")}
          value={formatRange(
            retrievalDiagnostics.rerank_score_min,
            retrievalDiagnostics.rerank_score_max,
            t,
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
              label={t("diag.vectorHits")}
              value={retrievalDiagnostics.hybrid_vector_hit_count ?? 0}
            />
            <StatRow
              label={t("diag.keywordHits")}
              value={retrievalDiagnostics.hybrid_keyword_hit_count ?? 0}
            />
          </>
        ) : null}
        {retrievalDiagnostics.rerank_applied ? (
          <>
            <StatRow
              label={t("diag.reranker")}
              value={
                retrievalDiagnostics.rerank_model ??
                retrievalDiagnostics.rerank_provider ??
                t("diag.enabled")
              }
            />
            {retrievalDiagnostics.rerank_fallback_used ? (
              <StatRow
                label={t("diag.rerankFallback")}
                value={retrievalDiagnostics.rerank_fallback_reason ?? t("yes")}
              />
            ) : null}
          </>
        ) : null}
        {debug?.parent_context_expansion_enabled ? (
          <>
            <StatRow
              label={t("diag.parentExpansion")}
              value={t("diag.parentChunks", {
                count: debug.parent_context_expanded_count ?? 0,
              })}
            />
            {(debug.parent_context_tokens_used ?? 0) > 0 ? (
              <StatRow
                label={t("diag.parentTokens")}
                value={debug.parent_context_tokens_used}
              />
            ) : null}
          </>
        ) : null}
        {debug?.freshness_filter_enabled ? (
          <>
            {(debug.freshness_boosted_count ?? 0) > 0 ? (
              <StatRow
                label={t("diag.freshnessBoosted")}
                value={debug.freshness_boosted_count}
              />
            ) : null}
            {(debug.freshness_excluded_count ?? 0) > 0 ? (
              <StatRow
                label={t("diag.excluded")}
                value={debug.freshness_excluded_count}
              />
            ) : null}
            {(debug.freshness_stale_count ?? 0) > 0 ? (
              <StatRow
                label={t("diag.staleSources")}
                value={debug.freshness_stale_count}
              />
            ) : null}
            {((debug as { freshness_unreviewed_count?: number })
              .freshness_unreviewed_count ?? 0) > 0 ? (
              <StatRow
                label={t("diag.unreviewedSources")}
                value={
                  (debug as { freshness_unreviewed_count?: number })
                    .freshness_unreviewed_count
                }
              />
            ) : null}
            {((debug as { freshness_deprecated_count?: number })
              .freshness_deprecated_count ?? 0) > 0 ? (
              <StatRow
                label={t("diag.deprecatedSources")}
                value={
                  (debug as { freshness_deprecated_count?: number })
                    .freshness_deprecated_count
                }
              />
            ) : null}
            {(debug as { freshness_all_excluded_fallback?: boolean })
              .freshness_all_excluded_fallback ? (
              <StatRow label={t("diag.allExcludedFallback")} value={t("yes")} />
            ) : null}
          </>
        ) : null}
        {debug?.ocr_quality_downranking_enabled &&
        (debug.ocr_low_confidence_chunk_count ?? 0) > 0 ? (
          <StatRow
            label={t("diag.ocrLowChunks")}
            value={debug.ocr_low_confidence_chunk_count}
          />
        ) : null}
      </div>
    </div>
  );
}
