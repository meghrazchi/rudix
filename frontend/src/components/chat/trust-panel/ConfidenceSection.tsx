import {
  confidenceBadgeClass,
  confidenceBarClass,
  pct,
  reasonImpactIcon,
  score,
} from "@/components/chat/trust-panel/trust-format";
import {
  trustLevelBadge,
  type TrustLevel,
} from "@/components/chat/trust-panel/trust-badges";
import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type { ChatConfidenceExplanationResponse } from "@/lib/api/chat";
import type {
  AnswerTrustMetadataResponse,
  ConfidenceReasonRecord,
} from "@/lib/api/trust_metadata";

export function ConfidenceSection({
  confidenceScore,
  confidenceCategory,
  confidenceExplanation,
  trustMetadata,
}: {
  confidenceScore: number;
  confidenceCategory: "low" | "medium" | "high";
  confidenceExplanation: ChatConfidenceExplanationResponse | null;
  trustMetadata: AnswerTrustMetadataResponse | null | undefined;
}) {
  const barWidth = `${Math.round(confidenceScore * 100)}%`;

  return (
    <div className="space-y-3 px-4 pt-4 md:px-6 md:pt-5">
      <SectionHeader icon="check_circle" label="Trust Score" />
      <div className="flex items-center gap-3">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#e8e5f5]">
          <div
            className={`h-full rounded-full transition-all ${confidenceBarClass(confidenceCategory)}`}
            style={{ width: barWidth }}
            role="progressbar"
            aria-valuenow={Math.round(confidenceScore * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Confidence score"
          />
        </div>
        <span className="w-12 text-right text-sm font-bold text-[#2f2a46] tabular-nums">
          {pct(confidenceScore)}
        </span>
        {trustMetadata?.confidence.trust_level ? (
          (() => {
            const badge = trustLevelBadge(
              trustMetadata.confidence.trust_level as TrustLevel,
            );
            return (
              <span className={badge.cls} data-testid="trust-level-badge">
                <span
                  className="material-symbols-outlined text-[10px]"
                  aria-hidden="true"
                >
                  {badge.icon}
                </span>
                {badge.label}
              </span>
            );
          })()
        ) : (
          <span className={confidenceBadgeClass(confidenceCategory)}>
            {confidenceCategory}
          </span>
        )}
      </div>
      {trustMetadata?.confidence.reasons &&
        trustMetadata.confidence.reasons.length > 0 && (
          <div
            className="space-y-1"
            data-testid="confidence-reasons"
            aria-label="Confidence signals"
          >
            {trustMetadata.confidence.reasons.map(
              (reason: ConfidenceReasonRecord) => {
                const { icon, cls } = reasonImpactIcon(reason.impact);
                return (
                  <div key={reason.code} className="flex items-start gap-1.5">
                    <span
                      className={`material-symbols-outlined mt-0.5 shrink-0 text-[12px] ${cls}`}
                      aria-hidden="true"
                    >
                      {icon}
                    </span>
                    <span className="text-[11px] text-[#6a6780]">
                      {reason.label}
                    </span>
                  </div>
                );
              },
            )}
          </div>
        )}
      {confidenceExplanation && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
          <StatRow
            label="Top similarity"
            value={score(confidenceExplanation.top_similarity)}
          />
          <StatRow
            label="Avg similarity"
            value={score(confidenceExplanation.average_similarity)}
          />
          <StatRow
            label="Rerank score"
            value={score(confidenceExplanation.top_rerank_score)}
          />
          <StatRow
            label="Citation coverage"
            value={pct(confidenceExplanation.citation_coverage_score)}
          />
          <StatRow
            label="Citation support"
            value={score(confidenceExplanation.citation_support_score)}
          />
          <StatRow
            label="Source agreement"
            value={score(confidenceExplanation.retrieval_agreement_score)}
          />
          {trustMetadata?.confidence.freshness_multiplier != null &&
            trustMetadata.confidence.freshness_multiplier < 1.0 && (
              <StatRow
                label="Freshness factor"
                value={pct(trustMetadata.confidence.freshness_multiplier)}
              />
            )}
          {trustMetadata?.confidence.ocr_quality_multiplier != null &&
            trustMetadata.confidence.ocr_quality_multiplier < 1.0 && (
              <StatRow
                label="OCR quality factor"
                value={pct(trustMetadata.confidence.ocr_quality_multiplier)}
              />
            )}
          {trustMetadata?.confidence.conflict_multiplier != null &&
            trustMetadata.confidence.conflict_multiplier < 1.0 && (
              <StatRow
                label="Conflict factor"
                value={pct(trustMetadata.confidence.conflict_multiplier)}
              />
            )}
          {trustMetadata?.confidence.table_quality_multiplier != null &&
            trustMetadata.confidence.table_quality_multiplier < 1.0 && (
              <StatRow
                label="Table quality factor"
                value={pct(trustMetadata.confidence.table_quality_multiplier)}
              />
            )}
          {trustMetadata?.confidence.extraction_quality_multiplier != null &&
            trustMetadata.confidence.extraction_quality_multiplier < 1.0 && (
              <StatRow
                label="Extraction quality factor"
                value={pct(
                  trustMetadata.confidence.extraction_quality_multiplier,
                )}
              />
            )}
          {trustMetadata?.confidence.graph_evidence_boost != null &&
            trustMetadata.confidence.graph_evidence_boost > 0 && (
              <StatRow
                label="Graph boost"
                value={`+${pct(trustMetadata.confidence.graph_evidence_boost)}`}
              />
            )}
        </div>
      )}
    </div>
  );
}
