"use client";

import type {
  ChatCitationResponse,
  ChatConfidenceExplanationResponse,
  ChatDebugResponse,
} from "@/lib/api/chat";
import type {
  AnswerTrustMetadataResponse,
  CitationTrustRecord,
  ConfidenceReasonRecord,
  ConflictStatusRecord,
  QueryInterpretationRecord,
} from "@/lib/api/trust_metadata";
import {
  agreementLevelClass,
  agreementLevelLabel,
} from "@/components/chat/ConflictIndicators";

type TrustPanelCitation = ChatCitationResponse | CitationTrustRecord;

// Minimum props the trust panel needs — a deliberate subset of ChatTurn["response"].
export type TrustPanelProps = {
  messageId: string;
  confidenceScore: number;
  confidenceCategory: "low" | "medium" | "high";
  confidenceExplanation: ChatConfidenceExplanationResponse | null;
  citationValidationFailed: boolean;
  verificationFailed: boolean;
  sourceFreshnessWarning: boolean;
  sourceFreshnessWarningReason: string | null;
  policyApplied: boolean;
  policyOutcome: string | null;
  policyViolatedRules: string[];
  policyWarningFlags: string[];
  policyDisclaimer: string | null;
  citations: TrustPanelCitation[];
  debug: ChatDebugResponse | null;
  trustMetadata?: AnswerTrustMetadataResponse | null;
  showInterpretationDetails?: boolean;
  onOpenCitation: (citation: TrustPanelCitation) => void;
};

function pct(v: number | null | undefined): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "N/A";
  return `${(v * 100).toFixed(1)}%`;
}

function score(v: number | null | undefined): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "N/A";
  return v.toFixed(3);
}

function confidenceBarClass(category: "low" | "medium" | "high"): string {
  if (category === "high") return "bg-emerald-500";
  if (category === "medium") return "bg-amber-400";
  return "bg-rose-400";
}

function confidenceBadgeClass(category: "low" | "medium" | "high"): string {
  if (category === "high")
    return "inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase text-emerald-800";
  if (category === "medium")
    return "inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-800";
  return "inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[10px] font-bold uppercase text-rose-800";
}

type TrustLevel = "high" | "medium" | "low" | "warning" | "not_found";

function trustLevelBadge(level: TrustLevel): {
  label: string;
  cls: string;
  icon: string;
} {
  if (level === "high")
    return {
      label: "High",
      icon: "check_circle",
      cls: "inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase text-emerald-800",
    };
  if (level === "medium")
    return {
      label: "Medium",
      icon: "check_circle",
      cls: "inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-800",
    };
  if (level === "warning")
    return {
      label: "Warning",
      icon: "warning",
      cls: "inline-flex items-center gap-1 rounded-full border border-orange-200 bg-orange-50 px-2 py-0.5 text-[10px] font-bold uppercase text-orange-800",
    };
  if (level === "not_found")
    return {
      label: "Not Found",
      icon: "search_off",
      cls: "inline-flex items-center gap-1 rounded-full border border-[#e0dced] bg-[#faf9ff] px-2 py-0.5 text-[10px] font-bold uppercase text-[#6a6780]",
    };
  return {
    label: "Low",
    icon: "error",
    cls: "inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[10px] font-bold uppercase text-rose-800",
  };
}

function reasonImpactIcon(impact: "positive" | "negative" | "neutral"): {
  icon: string;
  cls: string;
} {
  if (impact === "positive")
    return { icon: "arrow_upward", cls: "text-emerald-600" };
  if (impact === "negative")
    return { icon: "arrow_downward", cls: "text-rose-500" };
  return { icon: "remove", cls: "text-[#9d98b5]" };
}

function trustStatusBadge(
  status: string | null | undefined,
): { label: string; cls: string } | null {
  if (!status || status === "uploaded") return null;
  if (status === "trusted")
    return {
      label: "Trusted",
      cls: "rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-800 uppercase",
    };
  if (status === "stale")
    return {
      label: "Stale",
      cls: "rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  if (status === "revoked" || status === "deleted")
    return {
      label: status.charAt(0).toUpperCase() + status.slice(1),
      cls: "rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  return {
    label: status.charAt(0).toUpperCase() + status.slice(1),
    cls: "rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6a6780] uppercase",
  };
}

function ocrBadge(
  quality: string | null | undefined,
  warn: boolean | undefined,
): { label: string; cls: string } | null {
  if (!warn && (!quality || quality === "high" || quality === "not_required"))
    return null;
  if (quality === "low" || quality === "failed" || warn)
    return {
      label: "OCR low confidence",
      cls: "rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  if (quality === "medium")
    return {
      label: "OCR medium",
      cls: "rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6a6780] uppercase",
    };
  return null;
}

function freshnessBadge(
  state: string | null | undefined,
  staleWarn: boolean | undefined,
  expiredWarn: boolean | undefined,
  unreviewedWarn: boolean | undefined,
  deprecatedWarn: boolean | undefined,
): { label: string; cls: string } | null {
  const effective =
    state ??
    (expiredWarn
      ? "expired"
      : staleWarn
        ? "stale"
        : unreviewedWarn
          ? "unreviewed"
          : deprecatedWarn
            ? "deprecated"
            : null);
  if (!effective || effective === "current" || effective === "unknown")
    return null;
  if (effective === "stale")
    return {
      label: "Stale",
      cls: "rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  if (effective === "expired")
    return {
      label: "Expired",
      cls: "rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  if (effective === "deprecated")
    return {
      label: "Deprecated",
      cls: "rounded-full border border-orange-200 bg-orange-50 px-1.5 py-0.5 text-[9px] font-semibold text-orange-800 uppercase",
    };
  if (effective === "draft")
    return {
      label: "Draft",
      cls: "rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6a6780] uppercase",
    };
  if (effective === "unreviewed")
    return {
      label: "Unreviewed",
      cls: "rounded-full border border-yellow-200 bg-yellow-50 px-1.5 py-0.5 text-[9px] font-semibold text-yellow-800 uppercase",
    };
  return null;
}

function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return null;
  }
}

function conflictBadge(
  status: "preferred" | "conflicting" | "neutral" | null | undefined,
): { label: string; cls: string } | null {
  if (status === "preferred")
    return {
      label: "Preferred",
      cls: "rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-800 uppercase",
    };
  if (status === "conflicting")
    return {
      label: "Conflicting",
      cls: "rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  return null;
}

function claimSupportBadge(
  status: "supported" | "partially_supported" | "unsupported" | "unverifiable",
): { label: string; cls: string } {
  if (status === "supported")
    return {
      label: "Supported",
      cls: "rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-800 uppercase",
    };
  if (status === "partially_supported")
    return {
      label: "Partial",
      cls: "rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  if (status === "unverifiable")
    return {
      label: "Unverifiable",
      cls: "rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold text-[#6a6780] uppercase",
    };
  return {
    label: "Unsupported",
    cls: "rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
  };
}

function queryComplexityLabel(
  complexity: QueryInterpretationRecord["complexity"],
): string {
  if (complexity === "multi_part") return "multi-part";
  return complexity;
}

function SectionHeader({ icon, label }: { icon: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5 border-b border-[#ece9f5] pb-1.5">
      <span
        className="material-symbols-outlined text-[15px] text-[#3525cd]"
        aria-hidden="true"
      >
        {icon}
      </span>
      <span className="text-[10px] font-bold tracking-widest text-[#3525cd] uppercase">
        {label}
      </span>
    </div>
  );
}

function StatRow({
  label,
  value,
  subtle,
}: {
  label: string;
  value: string | number | null | undefined;
  subtle?: boolean;
}) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex items-center justify-between gap-2 py-0.5">
      <span
        className={`text-[11px] ${subtle ? "text-[#9d98b5]" : "text-[#6a6780]"}`}
      >
        {label}
      </span>
      <span className="text-[11px] font-medium text-[#2f2a46]">
        {String(value)}
      </span>
    </div>
  );
}

function WarningBanner({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-900">
      <span
        className="material-symbols-outlined shrink-0 text-[14px] text-amber-700"
        aria-hidden="true"
      >
        warning
      </span>
      <span>{children}</span>
    </div>
  );
}

function SourceConflictSection({
  conflict,
}: {
  conflict: ConflictStatusRecord;
}) {
  return (
    <div className="space-y-2" data-testid="source-conflict-section">
      <SectionHeader icon="warning" label="Source Conflict" />
      <div className="flex flex-wrap items-center gap-2">
        <span className={agreementLevelClass(conflict.agreement_level)}>
          {agreementLevelLabel(conflict.agreement_level)}
        </span>
        {conflict.conflict_count > 0 && (
          <span className="text-[11px] text-[#6a6780]">
            {conflict.conflict_count} conflict pair
            {conflict.conflict_count !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      {conflict.conflict_summary ? (
        <p className="text-[11px] leading-snug text-[#6a6780]">
          {conflict.conflict_summary}
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        {conflict.conflicting_document_ids.length > 0 && (
          <StatRow
            label="Sources in conflict"
            value={conflict.conflicting_document_ids.length}
          />
        )}
        {conflict.preferred_document_ids.length > 0 && (
          <StatRow
            label="Preferred source count"
            value={conflict.preferred_document_ids.length}
          />
        )}
        {conflict.preferred_document_ids.length === 0 && conflict.detected && (
          <div className="col-span-2 text-[11px] text-[#9d98b5]">
            No preferred source could be determined — treat all sources with
            equal caution.
          </div>
        )}
      </div>
    </div>
  );
}

export function AnswerTrustPanel({
  messageId,
  confidenceScore,
  confidenceCategory,
  confidenceExplanation,
  citationValidationFailed,
  verificationFailed,
  sourceFreshnessWarning,
  sourceFreshnessWarningReason,
  policyApplied,
  policyOutcome,
  policyViolatedRules,
  policyWarningFlags,
  policyDisclaimer,
  citations,
  debug,
  trustMetadata,
  showInterpretationDetails = false,
  onOpenCitation,
}: TrustPanelProps) {
  const barWidth = `${Math.round(confidenceScore * 100)}%`;
  const graphUsed = debug?.graph_context_used ?? false;
  const graphEnabled = debug?.graph_context_enabled ?? false;
  const groundedVerification = trustMetadata?.grounded_verification ?? null;
  const trustCitations = trustMetadata?.citations ?? citations;
  const queryInterpretation = trustMetadata?.query_interpretation ?? null;
  const verificationApplied =
    groundedVerification?.applied ??
    debug?.grounded_verification_applied ??
    false;
  const claimSupportRecords = groundedVerification?.claims ?? [];

  // Compute warnings list
  const warnings: string[] = [];
  if (confidenceCategory === "low")
    warnings.push(
      "Low confidence — validate this answer against cited sources.",
    );
  if (citationValidationFailed)
    warnings.push(
      "Citation validation failed — some citations could not be verified.",
    );
  if (verificationFailed)
    warnings.push(
      "Answer verification failed — claims may not be fully grounded.",
    );
  if (sourceFreshnessWarning) {
    const freshnessRecord = trustMetadata?.freshness;
    if (
      freshnessRecord?.warning_reasons &&
      freshnessRecord.warning_reasons.length > 0
    ) {
      freshnessRecord.warning_reasons.forEach((r) => warnings.push(r));
    } else {
      warnings.push(
        sourceFreshnessWarningReason ??
          "One or more sources may be stale or unreviewed.",
      );
    }
    if (freshnessRecord?.all_excluded_fallback)
      warnings.push(
        "All trusted sources were excluded. The answer uses deprecated or expired content.",
      );
  }
  if (trustCitations.some((c) => c.doc_stale_warning || c.doc_expired_warning))
    warnings.push("One or more cited sources are stale or expired.");
  if (
    trustCitations.some(
      (c) => (c as { doc_unreviewed_warning?: boolean }).doc_unreviewed_warning,
    )
  )
    warnings.push("One or more cited sources are pending review.");
  if (
    trustCitations.some(
      (c) => (c as { doc_deprecated_warning?: boolean }).doc_deprecated_warning,
    )
  )
    warnings.push("One or more cited sources are deprecated or archived.");
  if (trustCitations.some((c) => c.doc_ocr_low_confidence_warning))
    warnings.push(
      "One or more sources have low OCR confidence — text accuracy may be reduced.",
    );
  if (policyDisclaimer) warnings.push(policyDisclaimer);
  if ((debug?.grounded_verification_removed_count ?? 0) > 0)
    warnings.push(
      `${debug!.grounded_verification_removed_count} unsupported claim(s) were removed from the answer.`,
    );
  if (
    groundedVerification &&
    groundedVerification.claim_count > 0 &&
    groundedVerification.aggregate_support_score < 0.6
  ) {
    warnings.push("Citation support is weak — review the mapped claims.");
  }
  if (
    groundedVerification &&
    groundedVerification.unsupported_count > 0 &&
    groundedVerification.claim_count > 0
  ) {
    warnings.push(
      `${groundedVerification.unsupported_count}/${groundedVerification.claim_count} claim(s) are not supported by citations.`,
    );
  }
  const conflictRecord = trustMetadata?.conflict ?? null;
  if (conflictRecord?.detected) {
    warnings.push(
      conflictRecord.conflict_summary
        ? `Source conflict: ${conflictRecord.conflict_summary}`
        : "Sources disagree on one or more claims. Prefer the marked source.",
    );
  } else if (conflictRecord?.agreement_level === "partial") {
    warnings.push(
      "Sources partially disagree. Verify claims against cited sources.",
    );
  }

  const showRetrievalSection =
    debug &&
    ((debug.retrieval_count ?? 0) > 0 ||
      (debug.selected_count ?? 0) > 0 ||
      debug.hybrid_retrieval_enabled);

  const showModelSection =
    debug && (debug.llm_model || debug.embedding_model || debug.llm_provider);

  return (
    <div
      data-testid={`trust-panel-${messageId}`}
      className="mt-2 space-y-5 rounded-xl border border-[#d7d4e8] bg-[#faf9ff] p-4 text-[#2f2a46]"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="material-symbols-outlined text-[16px] text-[#3525cd]"
            aria-hidden="true"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            check_circle
          </span>
          <span className="text-xs font-bold text-[#2f2a46]">
            Answer Explanation
          </span>
        </div>
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="space-y-1.5">
          {warnings.map((w, i) => (
            <WarningBanner key={i}>{w}</WarningBanner>
          ))}
        </div>
      )}

      {/* Confidence */}
      <div className="space-y-3">
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

      {/* Source Conflict */}
      {conflictRecord && conflictRecord.agreement_level !== "full" && (
        <SourceConflictSection conflict={conflictRecord} />
      )}

      {/* Claim support */}
      {groundedVerification && groundedVerification.claim_count > 0 && (
        <div className="space-y-2">
          <SectionHeader
            icon="fact_check"
            label={`Claim Support (${groundedVerification.supported_count}/${groundedVerification.claim_count})`}
          />
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
            <StatRow
              label="Aggregate support"
              value={pct(groundedVerification.aggregate_support_score)}
            />
            <StatRow
              label="Verification score"
              value={pct(groundedVerification.score)}
            />
            <StatRow
              label="Supported claims"
              value={groundedVerification.supported_count}
            />
            <StatRow
              label="Partial claims"
              value={groundedVerification.partially_supported_count}
            />
            <StatRow
              label="Unsupported claims"
              value={groundedVerification.unsupported_count}
            />
            <StatRow
              label="Unverifiable claims"
              value={groundedVerification.unverifiable_count}
            />
          </div>
          <div className="space-y-1.5">
            {claimSupportRecords.length > 0 ? (
              claimSupportRecords.map((claim) => {
                const badge = claimSupportBadge(claim.support_status);
                const mappedCitations = claim.citation_indices
                  .map((index) => ({
                    index,
                    citation: trustCitations[index - 1],
                  }))
                  .filter(
                    (
                      item,
                    ): item is {
                      index: number;
                      citation: ChatCitationResponse;
                    } => Boolean(item.citation),
                  );
                return (
                  <div
                    key={`claim-${claim.claim_index}-${claim.claim_text}`}
                    className="rounded-lg border border-[#e2dff1] bg-white px-3 py-2"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-[11px] leading-4 font-medium text-[#1b1b24]">
                          {claim.claim_text}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-1">
                          <span className={badge.cls}>{badge.label}</span>
                          <span className="text-[10px] text-[#9d98b5]">
                            Claim {claim.claim_index}
                          </span>
                          <span className="text-[10px] text-[#9d98b5]">
                            Support {pct(claim.support_score)}
                          </span>
                        </div>
                      </div>
                    </div>
                    {mappedCitations.length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {mappedCitations.map(({ index, citation }) => {
                          const title =
                            citation.source_title ??
                            citation.filename ??
                            "Source";
                          return (
                            <button
                              type="button"
                              key={`${claim.claim_index}-${index}-${citation.document_id}-${citation.chunk_id}`}
                              onClick={() => onOpenCitation(citation)}
                              className="rounded-full border border-[#d7d4e8] bg-[#faf9ff] px-2 py-0.5 text-[10px] font-medium text-[#3525cd] transition-colors hover:bg-[#ede9f9]"
                              aria-label={`Preview source ${index} for claim ${claim.claim_index}`}
                              title={title}
                            >
                              Source {index}
                              {citation.page_number
                                ? ` · p. ${citation.page_number}`
                                : ""}
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="mt-2 text-[10px] text-[#9d98b5]">
                        No validated citations mapped to this claim.
                      </p>
                    )}
                  </div>
                );
              })
            ) : (
              <div className="rounded-lg border border-dashed border-[#d7d4e8] bg-white px-3 py-2 text-[11px] text-[#6a6780]">
                Claim-level citation mapping is not available for this answer
                snapshot.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Citations */}
      {trustCitations.length > 0 && (
        <div className="space-y-2">
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
              };
              const freshness = freshnessBadge(
                citExt.freshness_state,
                citation.doc_stale_warning,
                citation.doc_expired_warning,
                citExt.doc_unreviewed_warning,
                citExt.doc_deprecated_warning,
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
                    onClick={() => onOpenCitation(citation)}
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

      {/* Retrieval Diagnostics */}
      {showRetrievalSection && (
        <div className="space-y-2">
          <SectionHeader icon="manage_search" label="Retrieval" />
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
            <StatRow
              label="Retrieved chunks"
              value={debug!.retrieval_count ?? 0}
            />
            <StatRow
              label="Selected chunks"
              value={debug!.selected_count ?? 0}
            />
            {debug!.hybrid_retrieval_enabled ? (
              <>
                <StatRow
                  label="Vector hits"
                  value={debug!.hybrid_vector_hit_count ?? 0}
                />
                <StatRow
                  label="Keyword hits"
                  value={debug!.hybrid_keyword_hit_count ?? 0}
                />
              </>
            ) : null}
            {debug!.rerank_applied ? (
              <>
                <StatRow
                  label="Reranker"
                  value={
                    debug!.rerank_model ?? debug!.rerank_provider ?? "Enabled"
                  }
                />
                {debug!.rerank_input_count ? (
                  <StatRow
                    label="Rerank inputs"
                    value={debug!.rerank_input_count}
                  />
                ) : null}
                {debug!.rerank_fallback_used ? (
                  <StatRow
                    label="Rerank fallback"
                    value={debug!.rerank_fallback_reason ?? "Yes"}
                  />
                ) : null}
              </>
            ) : null}
            {debug!.parent_context_expansion_enabled ? (
              <>
                <StatRow
                  label="Parent expansion"
                  value={`${debug!.parent_context_expanded_count ?? 0} chunks`}
                />
                {(debug!.parent_context_tokens_used ?? 0) > 0 ? (
                  <StatRow
                    label="Parent tokens"
                    value={debug!.parent_context_tokens_used}
                  />
                ) : null}
              </>
            ) : null}
            {debug!.freshness_filter_enabled ? (
              <>
                {(debug!.freshness_boosted_count ?? 0) > 0 ? (
                  <StatRow
                    label="Freshness boosted"
                    value={debug!.freshness_boosted_count}
                  />
                ) : null}
                {(debug!.freshness_excluded_count ?? 0) > 0 ? (
                  <StatRow
                    label="Excluded (deprecated/expired)"
                    value={debug!.freshness_excluded_count}
                  />
                ) : null}
                {(debug!.freshness_stale_count ?? 0) > 0 ? (
                  <StatRow
                    label="Stale sources"
                    value={debug!.freshness_stale_count}
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
            {debug!.ocr_quality_downranking_enabled &&
            (debug!.ocr_low_confidence_chunk_count ?? 0) > 0 ? (
              <StatRow
                label="OCR low-conf chunks"
                value={debug!.ocr_low_confidence_chunk_count}
              />
            ) : null}
          </div>
        </div>
      )}

      {showInterpretationDetails && queryInterpretation ? (
        <div className="space-y-2">
          <SectionHeader icon="manage_search" label="Query Interpretation" />
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
            <StatRow label="Intent" value={queryInterpretation.intent_label} />
            <StatRow
              label="Strategy"
              value={queryInterpretation.retrieval_strategy}
            />
            <StatRow
              label="Complexity"
              value={queryComplexityLabel(queryInterpretation.complexity)}
            />
          </div>
          {queryInterpretation.rewrite_preview_enabled ? (
            <div className="space-y-2">
              {queryInterpretation.rewritten_query_preview ? (
                <div className="rounded-lg border border-[#e2dff1] bg-white px-3 py-2">
                  <p className="text-[10px] font-semibold tracking-widest text-[#6a6780] uppercase">
                    Rewrite preview
                  </p>
                  <p className="mt-1 text-[11px] leading-snug text-[#2f2a46]">
                    {queryInterpretation.rewritten_query_preview}
                  </p>
                </div>
              ) : null}
              {queryInterpretation.sub_queries.length > 0 ? (
                <div className="space-y-1 rounded-lg border border-[#e2dff1] bg-white px-3 py-2">
                  <p className="text-[10px] font-semibold tracking-widest text-[#6a6780] uppercase">
                    Sub-queries
                  </p>
                  <div className="space-y-1">
                    {queryInterpretation.sub_queries.map((subQuery, index) => (
                      <div
                        key={`${queryInterpretation.retrieval_strategy}-${index}-${subQuery}`}
                        className="rounded-md bg-[#faf9ff] px-2 py-1 text-[11px] leading-snug text-[#2f2a46]"
                      >
                        {subQuery}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <p className="text-[11px] text-[#6a6780]">
              Rewrite preview is disabled by organization policy.
            </p>
          )}
        </div>
      ) : null}

      {/* Model & Prompt */}
      {showModelSection && (
        <div className="space-y-2">
          <SectionHeader icon="model_training" label="Model" />
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
            <StatRow label="Provider" value={debug!.llm_provider ?? null} />
            <StatRow label="LLM model" value={debug!.llm_model ?? null} />
            <StatRow
              label="Embeddings"
              value={debug!.embedding_model ?? null}
            />
            {debug!.prompt_template_key ? (
              <StatRow
                label="Prompt template"
                value={
                  debug!.prompt_template_version
                    ? `${debug!.prompt_template_key} v${debug!.prompt_template_version}`
                    : debug!.prompt_template_key
                }
              />
            ) : null}
            {debug!.fallback_used ? (
              <>
                <StatRow
                  label="Fallback from"
                  value={debug!.fallback_from ?? "primary"}
                />
                <StatRow
                  label="Fallback to"
                  value={debug!.fallback_to ?? null}
                />
                {debug!.fallback_reason ? (
                  <StatRow
                    label="Fallback reason"
                    value={debug!.fallback_reason}
                  />
                ) : null}
              </>
            ) : null}
            {debug!.detected_language ? (
              <StatRow
                label="Detected language"
                value={debug!.detected_language}
              />
            ) : null}
            {debug!.answer_language_used ? (
              <StatRow
                label="Answer language"
                value={debug!.answer_language_used}
              />
            ) : null}
          </div>
        </div>
      )}

      {/* Knowledge Graph */}
      {(graphUsed || (graphEnabled && debug?.graph_context_unavailable)) && (
        <div className="space-y-2">
          <SectionHeader icon="hub" label="Knowledge Graph" />
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
            {debug?.graph_context_unavailable ? (
              <div className="col-span-2">
                <p className="text-[11px] text-[#9d98b5]">
                  {debug.graph_context_reason ?? "Graph context unavailable."}
                </p>
              </div>
            ) : (
              <>
                <StatRow
                  label="Seed entities"
                  value={debug?.graph_seed_entity_count ?? 0}
                />
                <StatRow
                  label="Related entities"
                  value={debug?.graph_related_entity_count ?? 0}
                />
                <StatRow
                  label="Graph chunks"
                  value={debug?.graph_chunk_count ?? 0}
                />
                <StatRow
                  label="Max hops"
                  value={debug?.graph_max_hops_used ?? null}
                />
                {(debug?.graph_relation_types_used?.length ?? 0) > 0 ? (
                  <StatRow
                    label="Relation types"
                    value={debug!.graph_relation_types_used!.join(", ")}
                  />
                ) : null}
              </>
            )}
          </div>
        </div>
      )}

      {/* Grounded Verification */}
      {verificationApplied && (
        <div className="space-y-2">
          <SectionHeader icon="fact_check" label="Verification" />
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
            {debug?.grounded_verification_verdict ? (
              <StatRow
                label="Verdict"
                value={debug.grounded_verification_verdict}
              />
            ) : null}
            {typeof debug?.grounded_verification_score === "number" ? (
              <StatRow
                label="Score"
                value={score(debug.grounded_verification_score)}
              />
            ) : null}
            {(debug?.grounded_verification_claim_count ?? 0) > 0 ? (
              <>
                <StatRow
                  label="Claims checked"
                  value={debug!.grounded_verification_claim_count}
                />
                <StatRow
                  label="Supported"
                  value={debug!.grounded_verification_supported_count ?? 0}
                />
                {(debug?.grounded_verification_unsupported_count ?? 0) > 0 ? (
                  <StatRow
                    label="Unsupported"
                    value={debug!.grounded_verification_unsupported_count}
                  />
                ) : null}
                {(debug?.grounded_verification_removed_count ?? 0) > 0 ? (
                  <StatRow
                    label="Removed"
                    value={debug!.grounded_verification_removed_count}
                  />
                ) : null}
              </>
            ) : null}
            {debug?.grounded_verification_model ? (
              <StatRow
                label="Verifier model"
                value={debug.grounded_verification_model}
                subtle
              />
            ) : null}
          </div>
        </div>
      )}

      {/* Policy */}
      {policyApplied && (
        <div className="space-y-2">
          <SectionHeader icon="policy" label="Policy" />
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
            {policyOutcome ? (
              <StatRow label="Outcome" value={policyOutcome} />
            ) : null}
            {policyViolatedRules.length > 0 ? (
              <StatRow
                label="Violated rules"
                value={policyViolatedRules.join(", ")}
              />
            ) : null}
            {policyWarningFlags.length > 0 ? (
              <StatRow label="Warnings" value={policyWarningFlags.join(", ")} />
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
