/**
 * F315 tests: evidence quality warnings (OCR, table extraction,
 * document lifecycle) rendered in AnswerTrustPanel.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { AnswerTrustPanel } from "@/components/chat/AnswerTrustPanel";
import type {
  ChatCitationResponse,
  ChatConfidenceExplanationResponse,
  ChatDebugResponse,
} from "@/lib/api/chat";
import type {
  AnswerTrustMetadataResponse,
  CitationTrustRecord,
  ConfidenceTrustRecord,
  EvidenceQualityRecord,
} from "@/lib/api/trust_metadata";

// ---------------------------------------------------------------------------
// Base fixtures
// ---------------------------------------------------------------------------

const baseExplanation: ChatConfidenceExplanationResponse = {
  top_similarity: 0.88,
  average_similarity: 0.84,
  top_rerank_score: 0.85,
  citation_support_score: 0.8,
  citation_validation_score: 0.9,
  citation_coverage_score: 0.95,
  retrieval_agreement_score: 1.0,
  raw_score: 0.84,
  citation_validation_multiplier: 1.0,
  not_found_penalty_multiplier: 1.0,
  no_context: false,
  not_found_signal: false,
  weights: { similarity: 0.5, citation: 0.5 },
  thresholds: { low: 0.4, high: 0.75 },
};

const baseDebug: ChatDebugResponse = {
  latencies_ms: {},
  retrieval_count: 3,
  selected_count: 2,
  rerank_applied: false,
};

const baseCitation: ChatCitationResponse = {
  document_id: "doc-a",
  chunk_id: "chunk-a",
  filename: "report.pdf",
  score: 0.9,
  doc_stale_warning: false,
  doc_expired_warning: false,
  doc_ocr_low_confidence_warning: false,
  is_table_chunk: false,
  table_headers: [],
  table_low_confidence_warning: false,
  doc_extraction_warning: false,
  doc_processing_warning: false,
} as unknown as ChatCitationResponse;

const baseConfidence: ConfidenceTrustRecord = {
  ...baseExplanation,
  score: 0.84,
  category: "high" as const,
  trust_level: "high" as const,
  freshness_multiplier: 1.0,
  ocr_quality_multiplier: 1.0,
  conflict_multiplier: 1.0,
  table_quality_multiplier: 1.0,
  extraction_quality_multiplier: 1.0,
  graph_evidence_boost: 0.0,
  verification_support_score: null,
  reasons: [],
};

const baseEvidenceQuality: EvidenceQualityRecord = {
  table_low_confidence_count: 0,
  extraction_warning_count: 0,
  processing_warning_count: 0,
  any_incomplete_documents: false,
  warning_reasons: [],
};

const baseTrustCitation: CitationTrustRecord = {
  ...baseCitation,
  doc_is_excluded_status: false,
  doc_stale_warning: false,
  doc_expired_warning: false,
  doc_ocr_low_confidence_warning: false,
  is_table_chunk: false,
  table_headers: [],
  doc_unreviewed_warning: false,
  doc_deprecated_warning: false,
  table_low_confidence_warning: false,
  doc_extraction_warning: false,
  doc_processing_warning: false,
};

function makeEvidenceQuality(
  overrides: Partial<EvidenceQualityRecord> = {},
): EvidenceQualityRecord {
  return { ...baseEvidenceQuality, ...overrides };
}

function makeTrustMetadata(
  overrides: Partial<AnswerTrustMetadataResponse> = {},
): AnswerTrustMetadataResponse {
  return {
    schema_version: "1",
    organization_id: "org-1",
    message_id: "msg-f315",
    not_found: false,
    citation_validation_failed: false,
    verification_failed: false,
    confidence: baseConfidence,
    citations: [baseTrustCitation],
    retrieval: {
      retrieval_count: 3,
      selected_count: 2,
      rerank_applied: false,
      hybrid_retrieval_enabled: false,
      hybrid_vector_hit_count: 0,
      hybrid_keyword_hit_count: 0,
      query_rewriting_applied: false,
      query_decomposed: false,
      sub_query_count: 0,
      parent_context_expanded_count: 0,
      graph_context_used: false,
      graph_context_unavailable: false,
      graph_chunk_count: 0,
      freshness_excluded_count: 0,
      freshness_boosted_count: 0,
    },
    grounded_verification: {
      applied: false,
      claim_count: 0,
      supported_count: 0,
      partially_supported_count: 0,
      unsupported_count: 0,
      unverifiable_count: 0,
      removed_count: 0,
      aggregate_support_score: 0,
      reason_codes: [],
      claims: [],
    },
    model: {
      llm_model: "gpt-4o",
      llm_provider: "openai",
      fallback_used: false,
    },
    conflict: {
      detected: false,
      agreement_level: "full",
      conflict_count: 0,
      conflicting_document_ids: [],
      preferred_document_ids: [],
    },
    policy: {
      applied: false,
      violated_rules: [],
      warning_flags: [],
      has_disclaimer: false,
    },
    freshness: {
      warning: false,
      stale_count: 0,
      excluded_count: 0,
      boosted_count: 0,
      warning_reasons: [],
      unreviewed_count: 0,
      deprecated_count: 0,
      all_excluded_fallback: false,
    },
    evidence_quality: baseEvidenceQuality,
    generated_at: "2026-06-23T10:00:00Z",
    ...overrides,
  } as AnswerTrustMetadataResponse;
}

function renderPanel(
  overrides: Partial<Parameters<typeof AnswerTrustPanel>[0]> = {},
) {
  const props = {
    messageId: "msg-f315",
    confidenceScore: 0.84,
    confidenceCategory: "high" as const,
    confidenceExplanation: baseExplanation,
    citationValidationFailed: false,
    verificationFailed: false,
    sourceFreshnessWarning: false,
    sourceFreshnessWarningReason: null,
    policyApplied: false,
    policyOutcome: null,
    policyViolatedRules: [],
    policyWarningFlags: [],
    policyDisclaimer: null,
    citations: [baseCitation],
    debug: baseDebug,
    onOpenCitation: vi.fn(),
    trustMetadata: makeTrustMetadata(),
    ...overrides,
  };
  return render(<AnswerTrustPanel {...props} />);
}

// ---------------------------------------------------------------------------
// EvidenceQualityRecord type contract
// ---------------------------------------------------------------------------

describe("EvidenceQualityRecord type", () => {
  it("all-zero record is clean", () => {
    const rec = makeEvidenceQuality();
    expect(rec.table_low_confidence_count).toBe(0);
    expect(rec.extraction_warning_count).toBe(0);
    expect(rec.processing_warning_count).toBe(0);
    expect(rec.any_incomplete_documents).toBe(false);
    expect(rec.warning_reasons).toHaveLength(0);
  });

  it("processing warning sets any_incomplete_documents", () => {
    const rec = makeEvidenceQuality({
      processing_warning_count: 1,
      any_incomplete_documents: true,
      warning_reasons: [
        "1 source document has incomplete or failed processing.",
      ],
    });
    expect(rec.any_incomplete_documents).toBe(true);
    expect(rec.warning_reasons).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// CitationTrustRecord — F315 fields
// ---------------------------------------------------------------------------

describe("CitationTrustRecord F315 fields", () => {
  it("defaults to no table or extraction warnings", () => {
    const rec: CitationTrustRecord = {
      ...baseTrustCitation,
    };
    expect(rec.table_low_confidence_warning).toBe(false);
    expect(rec.table_extraction_confidence).toBeUndefined();
    expect(rec.doc_extraction_warning).toBe(false);
    expect(rec.doc_extraction_quality).toBeUndefined();
    expect(rec.doc_processing_warning).toBe(false);
  });

  it("can hold table low confidence data", () => {
    const rec: CitationTrustRecord = {
      ...baseTrustCitation,
      is_table_chunk: true,
      table_extraction_confidence: 0.25,
      table_low_confidence_warning: true,
    };
    expect(rec.table_extraction_confidence).toBe(0.25);
    expect(rec.table_low_confidence_warning).toBe(true);
  });

  it("can hold extraction quality data", () => {
    const rec: CitationTrustRecord = {
      ...baseTrustCitation,
      doc_extraction_quality: "corrupted",
      doc_extraction_warning: true,
    };
    expect(rec.doc_extraction_quality).toBe("corrupted");
    expect(rec.doc_extraction_warning).toBe(true);
  });

  it("can hold processing warning", () => {
    const rec: CitationTrustRecord = {
      ...baseTrustCitation,
      doc_processing_warning: true,
    };
    expect(rec.doc_processing_warning).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// ConfidenceTrustRecord — F315 multiplier fields
// ---------------------------------------------------------------------------

describe("ConfidenceTrustRecord F315 multiplier fields", () => {
  it("defaults to 1.0 for both new multipliers", () => {
    expect(baseConfidence.table_quality_multiplier).toBe(1.0);
    expect(baseConfidence.extraction_quality_multiplier).toBe(1.0);
  });

  it("accepts degraded multipliers", () => {
    const degraded: ConfidenceTrustRecord = {
      ...baseConfidence,
      score: 0.55,
      category: "medium",
      trust_level: "warning",
      table_quality_multiplier: 0.85,
      extraction_quality_multiplier: 0.85,
    };
    expect(degraded.table_quality_multiplier).toBe(0.85);
    expect(degraded.extraction_quality_multiplier).toBe(0.85);
  });
});

// ---------------------------------------------------------------------------
// Table low confidence badge in citation card
// ---------------------------------------------------------------------------

describe("table low confidence badge", () => {
  const tableCitation: ChatCitationResponse = {
    ...baseCitation,
    is_table_chunk: true,
    table_headers: ["Col A", "Col B"],
    table_extraction_confidence: 0.25,
    table_low_confidence_warning: true,
  } as unknown as ChatCitationResponse;

  const tableTrustCitation: CitationTrustRecord = {
    ...baseTrustCitation,
    is_table_chunk: true,
    table_headers: ["Col A", "Col B"],
    table_extraction_confidence: 0.25,
    table_low_confidence_warning: true,
  };

  it("renders table-low-confidence-badge when warning is true", () => {
    renderPanel({
      citations: [tableCitation],
      trustMetadata: makeTrustMetadata({
        citations: [tableTrustCitation],
      }),
    });
    const badge = screen.queryByTestId("table-low-confidence-badge");
    expect(badge).not.toBeNull();
  });

  it("does not render table badge when confidence is high", () => {
    const cleanTableCitation: ChatCitationResponse = {
      ...baseCitation,
      is_table_chunk: true,
      table_headers: ["Col A"],
      table_extraction_confidence: 0.95,
      table_low_confidence_warning: false,
    } as unknown as ChatCitationResponse;
    const cleanTrustCitation: CitationTrustRecord = {
      ...baseTrustCitation,
      is_table_chunk: true,
      table_headers: ["Col A"],
      table_extraction_confidence: 0.95,
      table_low_confidence_warning: false,
    };
    renderPanel({
      citations: [cleanTableCitation],
      trustMetadata: makeTrustMetadata({ citations: [cleanTrustCitation] }),
    });
    expect(screen.queryByTestId("table-low-confidence-badge")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Extraction quality badge in citation card
// ---------------------------------------------------------------------------

describe("extraction quality badge", () => {
  it("renders extraction-warning-badge for corrupted profile", () => {
    const citation: ChatCitationResponse = {
      ...baseCitation,
      doc_extraction_quality: "corrupted",
      doc_extraction_warning: true,
    } as unknown as ChatCitationResponse;
    const trustCitation: CitationTrustRecord = {
      ...baseTrustCitation,
      doc_extraction_quality: "corrupted",
      doc_extraction_warning: true,
    };
    renderPanel({
      citations: [citation],
      trustMetadata: makeTrustMetadata({ citations: [trustCitation] }),
    });
    expect(screen.queryByTestId("extraction-warning-badge")).not.toBeNull();
  });

  it("renders extraction-warning-badge for unsupported profile", () => {
    const citation: ChatCitationResponse = {
      ...baseCitation,
      doc_extraction_quality: "unsupported",
      doc_extraction_warning: true,
    } as unknown as ChatCitationResponse;
    const trustCitation: CitationTrustRecord = {
      ...baseTrustCitation,
      doc_extraction_quality: "unsupported",
      doc_extraction_warning: true,
    };
    renderPanel({
      citations: [citation],
      trustMetadata: makeTrustMetadata({ citations: [trustCitation] }),
    });
    expect(screen.queryByTestId("extraction-warning-badge")).not.toBeNull();
  });

  it("does not render extraction badge when no warning", () => {
    renderPanel();
    expect(screen.queryByTestId("extraction-warning-badge")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Processing incomplete badge in citation card
// ---------------------------------------------------------------------------

describe("processing warning badge", () => {
  it("renders processing-warning-badge when doc_processing_warning is true", () => {
    const citation: ChatCitationResponse = {
      ...baseCitation,
      doc_processing_warning: true,
    } as unknown as ChatCitationResponse;
    const trustCitation: CitationTrustRecord = {
      ...baseTrustCitation,
      doc_processing_warning: true,
    };
    renderPanel({
      citations: [citation],
      trustMetadata: makeTrustMetadata({ citations: [trustCitation] }),
    });
    expect(screen.queryByTestId("processing-warning-badge")).not.toBeNull();
  });

  it("does not render processing badge for clean citation", () => {
    renderPanel();
    expect(screen.queryByTestId("processing-warning-badge")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// evidence_quality warning block in trust panel
// ---------------------------------------------------------------------------

describe("evidence_quality warning reasons", () => {
  it("shows table low confidence warning reason from evidence_quality record", () => {
    const warningReason =
      "1 cited table chunk has low extraction confidence — table data may be inaccurate.";
    renderPanel({
      trustMetadata: makeTrustMetadata({
        evidence_quality: makeEvidenceQuality({
          table_low_confidence_count: 1,
          warning_reasons: [warningReason],
        }),
        confidence: {
          ...baseConfidence,
          trust_level: "warning",
          table_quality_multiplier: 0.85,
        },
      }),
    });
    expect(screen.queryByText(warningReason)).not.toBeNull();
  });

  it("shows extraction quality warning reason from evidence_quality record", () => {
    const warningReason =
      "1 source document has poor extraction quality — text coverage may be incomplete.";
    renderPanel({
      trustMetadata: makeTrustMetadata({
        evidence_quality: makeEvidenceQuality({
          extraction_warning_count: 1,
          warning_reasons: [warningReason],
        }),
        confidence: {
          ...baseConfidence,
          trust_level: "warning",
          extraction_quality_multiplier: 0.85,
        },
      }),
    });
    expect(screen.queryByText(warningReason)).not.toBeNull();
  });

  it("shows processing incomplete warning reason from evidence_quality record", () => {
    const warningReason =
      "1 source document has incomplete or failed processing — content may be missing.";
    renderPanel({
      trustMetadata: makeTrustMetadata({
        evidence_quality: makeEvidenceQuality({
          processing_warning_count: 1,
          any_incomplete_documents: true,
          warning_reasons: [warningReason],
        }),
        confidence: {
          ...baseConfidence,
          trust_level: "warning",
        },
      }),
    });
    expect(screen.queryByText(warningReason)).not.toBeNull();
  });

  it("renders no evidence_quality warnings when record is clean", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        evidence_quality: makeEvidenceQuality(),
      }),
    });
    expect(screen.queryByText(/low extraction confidence/i)).toBeNull();
    expect(screen.queryByText(/poor extraction quality/i)).toBeNull();
    expect(screen.queryByText(/incomplete or failed processing/i)).toBeNull();
  });

  it("renders multiple warning reasons when multiple quality issues exist", () => {
    const tableReason =
      "2 cited table chunks have low extraction confidence — table data may be inaccurate.";
    const extractionReason =
      "1 source document has poor extraction quality — text coverage may be incomplete.";
    renderPanel({
      trustMetadata: makeTrustMetadata({
        evidence_quality: makeEvidenceQuality({
          table_low_confidence_count: 2,
          extraction_warning_count: 1,
          warning_reasons: [tableReason, extractionReason],
        }),
        confidence: {
          ...baseConfidence,
          trust_level: "warning",
          table_quality_multiplier: 0.85,
          extraction_quality_multiplier: 0.85,
        },
      }),
    });
    expect(screen.queryByText(tableReason)).not.toBeNull();
    expect(screen.queryByText(extractionReason)).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Confidence stats — table and extraction quality factors
// ---------------------------------------------------------------------------

describe("confidence stats for new F315 multipliers", () => {
  it("shows table quality factor when below 1.0", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        confidence: {
          ...baseConfidence,
          score: 0.71,
          category: "medium",
          trust_level: "warning",
          table_quality_multiplier: 0.85,
        },
      }),
    });
    expect(screen.queryByText(/table quality factor/i)).not.toBeNull();
  });

  it("shows extraction quality factor when below 1.0", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        confidence: {
          ...baseConfidence,
          score: 0.71,
          category: "medium",
          trust_level: "warning",
          extraction_quality_multiplier: 0.85,
        },
      }),
    });
    expect(screen.queryByText(/extraction quality factor/i)).not.toBeNull();
  });

  it("hides table quality factor when at 1.0", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        confidence: { ...baseConfidence, table_quality_multiplier: 1.0 },
      }),
    });
    expect(screen.queryByText(/table quality factor/i)).toBeNull();
  });

  it("hides extraction quality factor when at 1.0", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        confidence: { ...baseConfidence, extraction_quality_multiplier: 1.0 },
      }),
    });
    expect(screen.queryByText(/extraction quality factor/i)).toBeNull();
  });
});
