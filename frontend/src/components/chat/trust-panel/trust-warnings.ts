import type { ChatDebugResponse } from "@/lib/api/chat";
import type { AnswerTrustMetadataResponse } from "@/lib/api/trust_metadata";

import type { TrustPanelCitation } from "@/components/chat/trust-panel/trust-types";

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
}): string[] {
  const groundedVerification = trustMetadata?.grounded_verification ?? null;
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
      warnings.push(
        "One or more cited tables have low extraction confidence — table data may be inaccurate.",
      );
    if (
      trustCitations.some(
        (c) =>
          (c as { doc_extraction_warning?: boolean }).doc_extraction_warning,
      )
    )
      warnings.push(
        "One or more source documents have poor extraction quality — text coverage may be incomplete.",
      );
    if (
      trustCitations.some(
        (c) =>
          (c as { doc_processing_warning?: boolean }).doc_processing_warning,
      )
    )
      warnings.push(
        "One or more source documents have incomplete or failed processing — content may be missing.",
      );
  }
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
  return warnings;
}
