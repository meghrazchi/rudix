import type { ChatDebugResponse } from "@/lib/api/chat";
import type { AnswerTrustMetadataResponse } from "@/lib/api/trust_metadata";

import type {
  TrustPanelCitation,
  TrustT,
} from "@/components/chat/trust-panel/trust-types";

/** Builds the ordered list of warning banners shown at the top of the panel. */
export function buildTrustWarnings({
  confidenceCategory,
  citationValidationFailed,
  verificationFailed,
  sourceFreshnessWarning,
  sourceFreshnessWarningReason,
  policyDisclaimer,
  trustMetadata,
  trustCitations,
  debug,
  t,
}: {
  confidenceCategory: "low" | "medium" | "high";
  citationValidationFailed: boolean;
  verificationFailed: boolean;
  sourceFreshnessWarning: boolean;
  sourceFreshnessWarningReason: string | null;
  policyDisclaimer: string | null;
  trustMetadata: AnswerTrustMetadataResponse | null | undefined;
  trustCitations: TrustPanelCitation[];
  debug: ChatDebugResponse | null;
  t: TrustT;
}): string[] {
  const groundedVerification = trustMetadata?.grounded_verification ?? null;
  const warnings: string[] = [];
  if (confidenceCategory === "low") warnings.push(t("warn.lowConfidence"));
  if (citationValidationFailed) warnings.push(t("warn.citationFailed"));
  if (verificationFailed) warnings.push(t("warn.verificationFailed"));
  if (sourceFreshnessWarning) {
    const freshnessRecord = trustMetadata?.freshness;
    if (
      freshnessRecord?.warning_reasons &&
      freshnessRecord.warning_reasons.length > 0
    ) {
      freshnessRecord.warning_reasons.forEach((r) => warnings.push(r));
    } else {
      warnings.push(sourceFreshnessWarningReason ?? t("warn.sourcesStale"));
    }
    if (freshnessRecord?.all_excluded_fallback)
      warnings.push(t("warn.allExcluded"));
  }
  if (trustCitations.some((c) => c.doc_stale_warning || c.doc_expired_warning))
    warnings.push(t("warn.citedStale"));
  if (
    trustCitations.some(
      (c) => (c as { doc_unreviewed_warning?: boolean }).doc_unreviewed_warning,
    )
  )
    warnings.push(t("warn.citedPending"));
  if (
    trustCitations.some(
      (c) => (c as { doc_deprecated_warning?: boolean }).doc_deprecated_warning,
    )
  )
    warnings.push(t("warn.citedDeprecated"));
  if (trustCitations.some((c) => c.doc_ocr_low_confidence_warning))
    warnings.push(t("warn.citedOcr"));
  // F315 — evidence quality warnings
  const evidenceQuality = trustMetadata?.evidence_quality ?? null;
  if (evidenceQuality) {
    evidenceQuality.warning_reasons.forEach((r) => warnings.push(r));
  } else {
    if (
      trustCitations.some(
        (c) =>
          (c as { table_low_confidence_warning?: boolean })
            .table_low_confidence_warning,
      )
    )
      warnings.push(t("warn.tableLow"));
    if (
      trustCitations.some(
        (c) =>
          (c as { doc_extraction_warning?: boolean }).doc_extraction_warning,
      )
    )
      warnings.push(t("warn.extractionPoor"));
    if (
      trustCitations.some(
        (c) =>
          (c as { doc_processing_warning?: boolean }).doc_processing_warning,
      )
    )
      warnings.push(t("warn.processingIncomplete"));
  }
  if (policyDisclaimer) warnings.push(policyDisclaimer);
  if ((debug?.grounded_verification_removed_count ?? 0) > 0)
    warnings.push(
      t("warn.removedClaims", {
        count: debug!.grounded_verification_removed_count ?? 0,
      }),
    );
  if (
    groundedVerification &&
    groundedVerification.claim_count > 0 &&
    groundedVerification.aggregate_support_score < 0.6
  ) {
    warnings.push(t("warn.weakSupport"));
  }
  if (
    groundedVerification &&
    groundedVerification.unsupported_count > 0 &&
    groundedVerification.claim_count > 0
  ) {
    warnings.push(
      t("warn.unsupportedClaims", {
        unsupported: groundedVerification.unsupported_count,
        total: groundedVerification.claim_count,
      }),
    );
  }
  const conflictRecord = trustMetadata?.conflict ?? null;
  if (conflictRecord?.detected) {
    warnings.push(
      conflictRecord.conflict_summary
        ? t("warn.conflictSummary", {
            summary: conflictRecord.conflict_summary,
          })
        : t("warn.conflictDefault"),
    );
  } else if (conflictRecord?.agreement_level === "partial") {
    warnings.push(t("warn.conflictPartial"));
  }
  return warnings;
}
