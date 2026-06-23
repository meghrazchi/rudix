/**
 * AnswerTrustPanel tests for F311 freshness state features.
 *
 * Covers:
 *  - freshness_state badges per citation (stale / expired / deprecated / draft /
 *    unreviewed / current)
 *  - doc_last_updated_at and source_last_synced_at display
 *  - doc_version_label display
 *  - structured warning_reasons list rendered as banners
 *  - all_excluded_fallback warning
 *  - unreviewed / deprecated citation count warnings
 *  - debug panel freshness count stats
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnswerTrustPanel } from "@/components/chat/AnswerTrustPanel";
import type {
  ChatCitationResponse,
  ChatConfidenceExplanationResponse,
} from "@/lib/api/chat";
import type {
  AnswerTrustMetadataResponse,
  CitationTrustRecord,
  ConfidenceTrustRecord,
} from "@/lib/api/trust_metadata";

// ---------------------------------------------------------------------------
// Base fixtures
// ---------------------------------------------------------------------------

const baseExplanation: ChatConfidenceExplanationResponse = {
  top_similarity: 0.9,
  average_similarity: 0.85,
  top_rerank_score: 0.87,
  citation_support_score: 0.78,
  citation_validation_score: 0.92,
  citation_coverage_score: 0.95,
  retrieval_agreement_score: 1.0,
  raw_score: 0.88,
  citation_validation_multiplier: 1.0,
  not_found_penalty_multiplier: 1.0,
  no_context: false,
  not_found_signal: false,
  weights: { similarity: 0.5, citation: 0.5 },
  thresholds: { low: 0.4, high: 0.75 },
};

const baseConfidence: ConfidenceTrustRecord = {
  ...baseExplanation,
  score: 0.87,
  category: "high",
  trust_level: "high",
  freshness_multiplier: 1.0,
  ocr_quality_multiplier: 1.0,
  conflict_multiplier: 1.0,
  graph_evidence_boost: 0.0,
  verification_support_score: null,
  table_quality_multiplier: 1.0,
  extraction_quality_multiplier: 1.0,
  reasons: [],
};

function makeCitation(
  overrides: Partial<CitationTrustRecord> = {},
): CitationTrustRecord {
  return {
    document_id: "doc-1",
    chunk_id: "chunk-1",
    filename: "policy.pdf",
    score: 0.9,
    rerank_score: 0.88,
    page_number: 2,
    source_trust_status: "trusted",
    doc_ocr_quality_status: "high",
    doc_ocr_low_confidence_warning: false,
    doc_stale_warning: false,
    doc_expired_warning: false,
    doc_is_excluded_status: false,
    conflict_status: "preferred",
    is_table_chunk: false,
    table_headers: [],
    doc_unreviewed_warning: false,
    doc_deprecated_warning: false,
    freshness_state: null,
    doc_last_updated_at: null,
    doc_review_owner_id: null,
    table_low_confidence_warning: false,
    doc_extraction_warning: false,
    doc_processing_warning: false,
    ...overrides,
  };
}

const baseFreshness = {
  warning: false,
  stale_count: 0,
  excluded_count: 0,
  boosted_count: 0,
  unreviewed_count: 0,
  deprecated_count: 0,
  all_excluded_fallback: false,
  warning_reasons: [],
};

function makeMetadata(
  citations: CitationTrustRecord[],
  freshnessOverrides: Partial<AnswerTrustMetadataResponse["freshness"]> = {},
): AnswerTrustMetadataResponse {
  return {
    schema_version: "1",
    organization_id: "org-1",
    message_id: "msg-1",
    not_found: false,
    citation_validation_failed: false,
    verification_failed: false,
    confidence: baseConfidence,
    citations,
    retrieval: {
      retrieval_count: 5,
      selected_count: 3,
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
      aggregate_support_score: 0,
      claim_count: 0,
      supported_count: 0,
      partially_supported_count: 0,
      unsupported_count: 0,
      unverifiable_count: 0,
      removed_count: 0,
      reason_codes: [],
      claims: [],
    },
    model: { llm_model: "gpt-4o", fallback_used: false },
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
    freshness: { ...baseFreshness, ...freshnessOverrides },
    evidence_quality: {
      table_low_confidence_count: 0,
      extraction_warning_count: 0,
      processing_warning_count: 0,
      any_incomplete_documents: false,
      warning_reasons: [],
    },
    generated_at: "2026-06-27T10:00:00Z",
  };
}

const noop = vi.fn();

function renderPanel(
  citationOverrides: Partial<CitationTrustRecord> = {},
  freshnessOverrides: Partial<AnswerTrustMetadataResponse["freshness"]> = {},
  panelOverrides: Record<string, unknown> = {},
) {
  const citation = makeCitation(citationOverrides);
  const metadata = makeMetadata([citation], freshnessOverrides);
  return render(
    <AnswerTrustPanel
      messageId="msg-1"
      confidenceScore={0.87}
      confidenceCategory="high"
      confidenceExplanation={baseExplanation}
      citationValidationFailed={false}
      verificationFailed={false}
      sourceFreshnessWarning={freshnessOverrides.warning ?? false}
      sourceFreshnessWarningReason={null}
      policyApplied={false}
      policyOutcome={null}
      policyViolatedRules={[]}
      policyWarningFlags={[]}
      policyDisclaimer={null}
      citations={[citation as unknown as ChatCitationResponse]}
      debug={null}
      trustMetadata={metadata}
      onOpenCitation={noop}
      {...panelOverrides}
    />,
  );
}

// ---------------------------------------------------------------------------
// freshness_state badge rendering
// ---------------------------------------------------------------------------

describe("freshness state badges", () => {
  it("does not render freshness badge for current state", () => {
    renderPanel({ freshness_state: "current" });
    expect(screen.queryByTestId("freshness-state-badge")).toBeNull();
  });

  it("renders Stale badge when freshness_state is stale", () => {
    renderPanel({ freshness_state: "stale", doc_stale_warning: true });
    expect(screen.getByTestId("freshness-state-badge").textContent).toMatch(
      /stale/i,
    );
  });

  it("renders Expired badge when freshness_state is expired", () => {
    renderPanel({ freshness_state: "expired", doc_expired_warning: true });
    expect(screen.getByTestId("freshness-state-badge").textContent).toMatch(
      /expired/i,
    );
  });

  it("renders Deprecated badge when freshness_state is deprecated", () => {
    renderPanel({
      freshness_state: "deprecated",
      doc_deprecated_warning: true,
    });
    expect(screen.getByTestId("freshness-state-badge").textContent).toMatch(
      /deprecated/i,
    );
  });

  it("renders Draft badge when freshness_state is draft", () => {
    renderPanel({ freshness_state: "draft" });
    expect(screen.getByTestId("freshness-state-badge").textContent).toMatch(
      /draft/i,
    );
  });

  it("renders Unreviewed badge when freshness_state is unreviewed", () => {
    renderPanel({
      freshness_state: "unreviewed",
      doc_unreviewed_warning: true,
    });
    expect(screen.getByTestId("freshness-state-badge").textContent).toMatch(
      /unreviewed/i,
    );
  });

  it("does not render badge when freshness_state is unknown", () => {
    renderPanel({ freshness_state: "unknown" });
    expect(screen.queryByTestId("freshness-state-badge")).toBeNull();
  });

  it("falls back to stale badge from doc_stale_warning when freshness_state is null", () => {
    renderPanel({ freshness_state: null, doc_stale_warning: true });
    expect(screen.getByTestId("freshness-state-badge").textContent).toMatch(
      /stale/i,
    );
  });

  it("falls back to expired badge from doc_expired_warning when freshness_state is null", () => {
    renderPanel({ freshness_state: null, doc_expired_warning: true });
    expect(screen.getByTestId("freshness-state-badge").textContent).toMatch(
      /expired/i,
    );
  });
});

// ---------------------------------------------------------------------------
// doc_last_updated_at display
// ---------------------------------------------------------------------------

describe("source last updated display", () => {
  it("shows 'Updated' date when doc_last_updated_at is provided", () => {
    renderPanel({ doc_last_updated_at: "2026-01-15T00:00:00Z" });
    expect(screen.getByText(/updated/i)).toBeTruthy();
  });

  it("does not show updated line when doc_last_updated_at is null", () => {
    renderPanel({ doc_last_updated_at: null, source_last_synced_at: null });
    expect(screen.queryByText(/updated/i)).toBeNull();
  });

  it("shows 'Synced' date when source_last_synced_at is provided", () => {
    renderPanel({ source_last_synced_at: "2026-06-01T00:00:00Z" });
    expect(screen.getByText(/synced/i)).toBeTruthy();
  });

  it("shows both updated and synced when both present", () => {
    renderPanel({
      doc_last_updated_at: "2026-01-01T00:00:00Z",
      source_last_synced_at: "2026-06-01T00:00:00Z",
    });
    expect(screen.getByText(/updated/i)).toBeTruthy();
    expect(screen.getByText(/synced/i)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// doc_version_label display
// ---------------------------------------------------------------------------

describe("version label display", () => {
  it("shows version label when provided", () => {
    renderPanel({ doc_version_label: "2.1" });
    expect(screen.getByText(/v2\.1/)).toBeTruthy();
  });

  it("does not show version when doc_version_label is null", () => {
    renderPanel({ doc_version_label: null });
    expect(screen.queryByText(/^v/)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// structured warning_reasons rendering
// ---------------------------------------------------------------------------

describe("structured freshness warning_reasons", () => {
  it("renders each warning_reason as a separate warning banner", () => {
    renderPanel(
      {},
      {
        warning: true,
        warning_reasons: [
          "2 sources may be outdated",
          "1 source pending review",
        ],
      },
      { sourceFreshnessWarning: true, sourceFreshnessWarningReason: null },
    );
    expect(screen.getByText("2 sources may be outdated")).toBeTruthy();
    expect(screen.getByText("1 source pending review")).toBeTruthy();
  });

  it("falls back to generic warning_reason when warning_reasons is empty", () => {
    renderPanel(
      {},
      { warning: true, warning_reasons: [] },
      {
        sourceFreshnessWarning: true,
        sourceFreshnessWarningReason: "Custom stale reason",
      },
    );
    expect(screen.getByText("Custom stale reason")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// all_excluded_fallback warning
// ---------------------------------------------------------------------------

describe("all_excluded_fallback warning", () => {
  it("shows additional fallback warning when all_excluded_fallback is true", () => {
    renderPanel(
      {},
      { warning: true, all_excluded_fallback: true, warning_reasons: [] },
      { sourceFreshnessWarning: true },
    );
    expect(screen.getByText(/all trusted sources were excluded/i)).toBeTruthy();
  });

  it("does not show fallback warning when all_excluded_fallback is false", () => {
    renderPanel(
      {},
      { warning: true, all_excluded_fallback: false, warning_reasons: [] },
      {
        sourceFreshnessWarning: true,
        sourceFreshnessWarningReason: "Stale sources",
      },
    );
    expect(screen.queryByText(/all trusted sources were excluded/i)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// unreviewed / deprecated citation warnings
// ---------------------------------------------------------------------------

describe("unreviewed and deprecated citation warnings", () => {
  it("shows unreviewed warning when citation has doc_unreviewed_warning true", () => {
    renderPanel({
      doc_unreviewed_warning: true,
      freshness_state: "unreviewed",
    });
    expect(screen.getByText(/pending review/i)).toBeTruthy();
  });

  it("shows deprecated warning when citation has doc_deprecated_warning true", () => {
    renderPanel({
      doc_deprecated_warning: true,
      freshness_state: "deprecated",
    });
    expect(screen.getByText(/deprecated or archived/i)).toBeTruthy();
  });

  it("shows stale/expired warning from existing doc_stale_warning", () => {
    renderPanel({ doc_stale_warning: true });
    expect(screen.getByText(/stale or expired/i)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// data-freshness-state attribute for testing hooks
// ---------------------------------------------------------------------------

describe("freshness state data attribute", () => {
  it("sets data-freshness-state attribute on citation row", () => {
    const { container } = renderPanel({ freshness_state: "stale" });
    const rows = container.querySelectorAll("[data-freshness-state]");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0].getAttribute("data-freshness-state")).toBe("stale");
  });
});
