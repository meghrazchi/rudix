import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import ar from "@/i18n/messages/ar.json";
import de from "@/i18n/messages/de.json";
import en from "@/i18n/messages/en.json";
import es from "@/i18n/messages/es.json";
import fa from "@/i18n/messages/fa.json";
import fr from "@/i18n/messages/fr.json";
import {
  answerModeBadge,
  claimSupportBadge,
  conflictBadge,
  extractionQualityBadge,
  freshnessBadge,
  ocrBadge,
  processingWarningBadge,
  tableExtractionBadge,
  trustLevelBadge,
  trustStatusBadge,
} from "@/components/chat/trust-panel/trust-badges";
import {
  buildRetrievalSummary,
  formatRange,
  queryComplexityLabel,
} from "@/components/chat/trust-panel/trust-format";
import type { TrustT } from "@/components/chat/trust-panel/trust-types";
import { buildTrustWarnings } from "@/components/chat/trust-panel/trust-warnings";

const LOCALES = { en, de, es, fr, ar, fa } as const;

function translatorFor(locale: keyof typeof LOCALES) {
  const onError = vi.fn();
  const t = createTranslator({
    locale,
    messages: LOCALES[locale] as unknown as typeof en,
    namespace: "chat.trustPanel",
    onError,
  }) as unknown as TrustT;
  return { t, onError };
}

const RETRIEVAL = {
  retrieval_count: 12,
  selected_count: 1,
  top_k: 5,
  search_mode: "hybrid",
  rerank_applied: true,
  rerank_fallback_used: true,
  rerank_fallback_reason: "timeout",
};

describe("trust panel helpers (R07-12)", () => {
  it("keeps the English wording of the retrieval summary", () => {
    const { t } = translatorFor("en");
    expect(buildRetrievalSummary(RETRIEVAL, t)).toBe(
      "Scope: all documents · 12 candidates reviewed · 1 chunk selected · top-k 5 · Mode: hybrid · reranking fell back (timeout)",
    );
    expect(
      buildRetrievalSummary(
        {
          ...RETRIEVAL,
          source_scope_label: "Handbook",
          retrieval_profile_name: "default",
          retrieval_profile_source: "org",
          rerank_fallback_used: false,
          top_k: undefined,
        },
        t,
      ),
    ).toBe(
      "Scope: Handbook · Profile: default (org) · 12 candidates reviewed · 1 chunk selected · Mode: hybrid · reranking was applied",
    );
    expect(
      buildRetrievalSummary(
        { ...RETRIEVAL, rerank_applied: false, rerank_fallback_used: false },
        t,
      ),
    ).toContain("reranking was off");
    expect(
      buildRetrievalSummary({ ...RETRIEVAL, rerank_fallback_reason: null }, t),
    ).toContain("reranking fell back");
  });

  it("formats ranges and complexity labels", () => {
    const { t } = translatorFor("en");
    expect(formatRange(null, null, t)).toBe("N/A");
    expect(formatRange(0.1, 0.9, t)).toBe("0.100 - 0.900");
    expect(formatRange(0.1, null, t)).toBe("from 0.100");
    expect(formatRange(null, 0.9, t)).toBe("up to 0.900");
    expect(queryComplexityLabel("multi_part", t)).toBe("multi-part");
    expect(queryComplexityLabel("simple", t)).toBe("simple");
    expect(queryComplexityLabel("complex", t)).toBe("complex");
  });

  it("builds warnings with counts and conflict text", () => {
    const { t } = translatorFor("en");
    const warnings = buildTrustWarnings({
      confidenceCategory: "low",
      citationValidationFailed: true,
      verificationFailed: true,
      sourceFreshnessWarning: true,
      sourceFreshnessWarningReason: null,
      policyDisclaimer: "Policy note",
      trustMetadata: {
        freshness: { warning_reasons: [], all_excluded_fallback: true },
        evidence_quality: null,
        grounded_verification: {
          claim_count: 4,
          unsupported_count: 2,
          aggregate_support_score: 0.4,
        },
        conflict: {
          detected: true,
          conflict_summary: "A vs B",
          agreement_level: "conflicting",
        },
      } as never,
      trustCitations: [
        {
          doc_stale_warning: true,
          doc_unreviewed_warning: true,
          doc_deprecated_warning: true,
          doc_ocr_low_confidence_warning: true,
          table_low_confidence_warning: true,
          doc_extraction_warning: true,
          doc_processing_warning: true,
        },
      ] as never,
      debug: { grounded_verification_removed_count: 3 } as never,
      t,
    });
    expect(warnings).toEqual(
      expect.arrayContaining([
        "Low confidence — validate this answer against cited sources.",
        "One or more sources may be stale or unreviewed.",
        "3 unsupported claim(s) were removed from the answer.",
        "2/4 claim(s) are not supported by citations.",
        "Source conflict: A vs B",
        "Policy note",
        "Citation support is weak — review the mapped claims.",
      ]),
    );
    const partial = buildTrustWarnings({
      confidenceCategory: "high",
      citationValidationFailed: false,
      verificationFailed: false,
      sourceFreshnessWarning: false,
      sourceFreshnessWarningReason: null,
      policyDisclaimer: null,
      trustMetadata: {
        conflict: { detected: false, agreement_level: "partial" },
      } as never,
      trustCitations: [],
      debug: null,
      t,
    });
    expect(partial).toEqual([
      "Sources partially disagree. Verify claims against cited sources.",
    ]);
  });

  it("returns translated badge labels", () => {
    const { t } = translatorFor("de");
    expect(trustLevelBadge("high", t).label).toBe("Hoch");
    expect(trustLevelBadge("not_found", t).label).toBe("Nicht gefunden");
    expect(trustStatusBadge("revoked", t)?.label).toBe("Widerrufen");
    expect(trustStatusBadge("deleted", t)?.label).toBe("Gelöscht");
    expect(trustStatusBadge("custom", t)?.label).toBe("Custom");
    expect(ocrBadge("medium", false, t)?.label).toBe("OCR: mittel");
    expect(tableExtractionBadge(true, t)?.label).toBeTruthy();
    expect(processingWarningBadge(true, t)?.label).toBeTruthy();
    expect(extractionQualityBadge("encrypted", true, t)?.label).toBe(
      "Verschlüsselt",
    );
    expect(answerModeBadge("guidance", t)?.label).toBeTruthy();
    expect(conflictBadge("preferred", t)?.label).toBe("Bevorzugt");
    expect(freshnessBadge("draft", false, false, false, false, t)?.label).toBe(
      "Entwurf",
    );
    expect(claimSupportBadge("partially_supported", t).label).toBe("Teilweise");
  });

  it.each(Object.keys(LOCALES) as (keyof typeof LOCALES)[])(
    "formats every helper message in %s without errors",
    (locale) => {
      const { t, onError } = translatorFor(locale);
      buildRetrievalSummary(RETRIEVAL, t);
      buildRetrievalSummary({ ...RETRIEVAL, rerank_fallback_reason: null }, t);
      formatRange(0.1, null, t);
      formatRange(null, 0.9, t);
      t("conflict.pairs", { count: 2 });
      t("conflict.pairs", { count: 1 });
      t("claims.title", { supported: 1, total: 2 });
      t("sources.title", { count: 3 });
      t("warn.removedClaims", { count: 2 });
      t("warn.unsupportedClaims", { unsupported: 1, total: 2 });
      expect(onError).not.toHaveBeenCalled();
    },
  );
});
