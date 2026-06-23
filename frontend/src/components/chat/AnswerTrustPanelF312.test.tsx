/**
 * F312 tests: source conflict detection and multi-source agreement scoring
 * rendered in AnswerTrustPanel.
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
} from "@/lib/api/trust_metadata";

const baseExplanation: ChatConfidenceExplanationResponse = {
  top_similarity: 0.9,
  average_similarity: 0.85,
  top_rerank_score: 0.88,
  citation_support_score: 0.75,
  citation_validation_score: 0.9,
  citation_coverage_score: 0.95,
  retrieval_agreement_score: 1.0,
  raw_score: 0.87,
  citation_validation_multiplier: 1.0,
  not_found_penalty_multiplier: 1.0,
  no_context: false,
  not_found_signal: false,
  weights: { similarity: 0.5, citation: 0.5 },
  thresholds: { low: 0.4, high: 0.75 },
};

const baseDebug: ChatDebugResponse = {
  latencies_ms: {},
  retrieval_count: 4,
  selected_count: 2,
  rerank_applied: false,
};

const baseCitationA: ChatCitationResponse = {
  document_id: "doc-a",
  chunk_id: "chunk-a",
  filename: "policy-a.pdf",
  score: 0.9,
  conflict_status: "preferred",
  doc_stale_warning: false,
  doc_expired_warning: false,
  doc_ocr_low_confidence_warning: false,
  is_table_chunk: false,
  table_headers: [],
} as unknown as ChatCitationResponse;

const baseCitationB: ChatCitationResponse = {
  document_id: "doc-b",
  chunk_id: "chunk-b",
  filename: "policy-b.pdf",
  score: 0.85,
  conflict_status: "conflicting",
  doc_stale_warning: false,
  doc_expired_warning: false,
  doc_ocr_low_confidence_warning: false,
  is_table_chunk: false,
  table_headers: [],
} as unknown as ChatCitationResponse;

const baseConfidence: ConfidenceTrustRecord = {
  ...baseExplanation,
  score: 0.72,
  category: "medium" as const,
  trust_level: "warning" as const,
  freshness_multiplier: 1.0,
  ocr_quality_multiplier: 1.0,
  conflict_multiplier: 0.8,
  graph_evidence_boost: 0.0,
  verification_support_score: null,
  table_quality_multiplier: 1.0,
  extraction_quality_multiplier: 1.0,
  reasons: [],
};

const baseTrustCitationA: CitationTrustRecord = {
  ...baseCitationA,
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

const baseTrustCitationB: CitationTrustRecord = {
  ...baseCitationB,
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

function makeTrustMetadata(
  overrides: Partial<AnswerTrustMetadataResponse> = {},
): AnswerTrustMetadataResponse {
  return {
    schema_version: "1",
    organization_id: "org-1",
    message_id: "msg-f312",
    not_found: false,
    citation_validation_failed: false,
    verification_failed: false,
    confidence: baseConfidence,
    citations: [baseTrustCitationA, baseTrustCitationB],
    retrieval: {
      retrieval_count: 4,
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
      detected: true,
      agreement_level: "conflicting",
      conflict_count: 1,
      conflicting_document_ids: ["doc-a", "doc-b"],
      preferred_document_ids: ["doc-a"],
      conflict_summary: "Two policy documents disagree on the leave allowance.",
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
    evidence_quality: {
      table_low_confidence_count: 0,
      extraction_warning_count: 0,
      processing_warning_count: 0,
      any_incomplete_documents: false,
      warning_reasons: [],
    },
    generated_at: "2026-06-21T10:00:00Z",
    ...overrides,
  };
}

function renderPanel(
  overrides: Partial<Parameters<typeof AnswerTrustPanel>[0]> = {},
) {
  const props = {
    messageId: "msg-f312",
    confidenceScore: 0.72,
    confidenceCategory: "medium" as const,
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
    citations: [baseCitationA, baseCitationB],
    debug: baseDebug,
    onOpenCitation: vi.fn(),
    trustMetadata: makeTrustMetadata(),
    ...overrides,
  };
  return render(<AnswerTrustPanel {...props} />);
}

describe("AnswerTrustPanel — F312 Source Conflict", () => {
  it("renders a dedicated Source Conflict section when conflict is detected", () => {
    renderPanel();
    expect(screen.getByTestId("source-conflict-section")).toBeInTheDocument();
    expect(screen.getByText("Source Conflict")).toBeInTheDocument();
  });

  it("shows the agreement level badge as Conflicting sources", () => {
    renderPanel();
    expect(screen.getByText("Conflicting sources")).toBeInTheDocument();
  });

  it("shows the conflict summary text", () => {
    renderPanel();
    expect(
      screen.getByText("Two policy documents disagree on the leave allowance."),
    ).toBeInTheDocument();
  });

  it("shows the conflict pair count when > 0", () => {
    renderPanel();
    expect(screen.getByText("1 conflict pair")).toBeInTheDocument();
  });

  it("shows the conflicting sources count", () => {
    renderPanel();
    expect(screen.getByText("Sources in conflict")).toBeInTheDocument();
    expect(screen.getAllByText("2").length).toBeGreaterThanOrEqual(1);
  });

  it("shows the preferred sources count when preferred_document_ids is not empty", () => {
    renderPanel();
    expect(screen.getByText("Preferred source count")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("shows unresolvable message when no preferred source exists", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        conflict: {
          detected: true,
          agreement_level: "conflicting",
          conflict_count: 1,
          conflicting_document_ids: ["doc-a", "doc-b"],
          preferred_document_ids: [],
          conflict_summary: "Cannot determine preferred source.",
        },
      }),
    });
    expect(
      screen.getByText(/No preferred source could be determined/i),
    ).toBeInTheDocument();
  });

  it("adds a conflict warning to the warnings list", () => {
    renderPanel();
    expect(
      screen.getByText(
        /Source conflict: Two policy documents disagree on the leave allowance\./i,
      ),
    ).toBeInTheDocument();
  });

  it("adds a generic conflict warning when summary is empty", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        conflict: {
          detected: true,
          agreement_level: "conflicting",
          conflict_count: 1,
          conflicting_document_ids: ["doc-a", "doc-b"],
          preferred_document_ids: ["doc-a"],
        },
      }),
    });
    expect(
      screen.getByText(/Sources disagree on one or more claims/i),
    ).toBeInTheDocument();
  });

  it("shows Partial agreement badge for partial conflict", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        conflict: {
          detected: false,
          agreement_level: "partial",
          conflict_count: 0,
          conflicting_document_ids: [],
          preferred_document_ids: [],
        },
      }),
    });
    expect(screen.getByText("Partial agreement")).toBeInTheDocument();
  });

  it("adds partial agreement warning to warnings", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        conflict: {
          detected: false,
          agreement_level: "partial",
          conflict_count: 0,
          conflicting_document_ids: [],
          preferred_document_ids: [],
        },
      }),
    });
    expect(screen.getByText(/Sources partially disagree/i)).toBeInTheDocument();
  });

  it("does NOT render the Source Conflict section when agreement is full", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        conflict: {
          detected: false,
          agreement_level: "full",
          conflict_count: 0,
          conflicting_document_ids: [],
          preferred_document_ids: [],
        },
      }),
    });
    expect(
      screen.queryByTestId("source-conflict-section"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Source Conflict")).not.toBeInTheDocument();
  });

  it("does NOT add a conflict warning when agreement is full", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        conflict: {
          detected: false,
          agreement_level: "full",
          conflict_count: 0,
          conflicting_document_ids: [],
          preferred_document_ids: [],
        },
      }),
    });
    expect(screen.queryByText(/Source conflict:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sources disagree/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Sources partially disagree/i),
    ).not.toBeInTheDocument();
  });

  it("shows Preferred badge for preferred citations", () => {
    renderPanel();
    expect(screen.getByText("Preferred")).toBeInTheDocument();
  });

  it("shows Conflicting badge for conflicting citations", () => {
    renderPanel();
    expect(screen.getByText("Conflicting")).toBeInTheDocument();
  });

  it("shows the conflict_multiplier row in confidence stats when below 1", () => {
    renderPanel();
    expect(screen.getByText("Conflict factor")).toBeInTheDocument();
    expect(screen.getByText("80.0%")).toBeInTheDocument();
  });

  it("does not show conflict_multiplier row when it is 1.0", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        confidence: { ...baseConfidence, conflict_multiplier: 1.0 },
      }),
    });
    expect(screen.queryByText("Conflict factor")).not.toBeInTheDocument();
  });

  it("renders multiple conflict pairs count label correctly (plural)", () => {
    renderPanel({
      trustMetadata: makeTrustMetadata({
        conflict: {
          detected: true,
          agreement_level: "conflicting",
          conflict_count: 3,
          conflicting_document_ids: ["doc-a", "doc-b", "doc-c"],
          preferred_document_ids: ["doc-a"],
          conflict_summary: "Multiple conflicts.",
        },
      }),
    });
    expect(screen.getByText("3 conflict pairs")).toBeInTheDocument();
  });
});
