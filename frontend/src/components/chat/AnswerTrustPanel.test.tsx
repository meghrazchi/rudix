import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { AnswerTrustPanel } from "@/components/chat/AnswerTrustPanel";
import { trackFeatureEvent } from "@/lib/analytics";
import type {
  ChatCitationResponse,
  ChatConfidenceExplanationResponse,
  ChatDebugResponse,
} from "@/lib/api/chat";
import type {
  AnswerTrustMetadataResponse,
  CitationTrustRecord,
  ConfidenceTrustRecord,
  QueryInterpretationRecord,
} from "@/lib/api/trust_metadata";

vi.mock("@/lib/analytics", () => ({
  trackFeatureEvent: vi.fn().mockResolvedValue(undefined),
}));

const baseExplanation: ChatConfidenceExplanationResponse = {
  top_similarity: 0.921,
  average_similarity: 0.845,
  top_rerank_score: 0.887,
  citation_support_score: 0.76,
  citation_validation_score: 0.9,
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

const baseDebug: ChatDebugResponse = {
  latencies_ms: { retrieval: 120, llm: 800 },
  retrieval_count: 8,
  selected_count: 4,
  rerank_applied: true,
  llm_model: "gpt-4o",
  llm_provider: "openai",
  embedding_model: "text-embedding-3-large",
  rerank_model: "cohere-rerank-v3",
};

const baseCitation: ChatCitationResponse = {
  document_id: "doc-1",
  chunk_id: "chunk-1",
  filename: "policy.pdf",
  score: 0.921,
  rerank_score: 0.887,
  page_number: 3,
  source_trust_status: "trusted",
  doc_ocr_quality_status: "high",
  doc_ocr_low_confidence_warning: false,
  doc_stale_warning: false,
  doc_expired_warning: false,
  conflict_status: "preferred",
  is_table_chunk: false,
  table_headers: [],
} as unknown as ChatCitationResponse;

const baseTrustCitation: CitationTrustRecord = {
  ...baseCitation,
  doc_stale_warning: false,
  doc_expired_warning: false,
  doc_is_excluded_status: false,
  doc_ocr_low_confidence_warning: false,
  doc_unreviewed_warning: false,
  doc_deprecated_warning: false,
  is_table_chunk: false,
  table_headers: [],
  table_low_confidence_warning: false,
  doc_extraction_warning: false,
  doc_processing_warning: false,
};

const baseTrustConfidence: ConfidenceTrustRecord = {
  ...baseExplanation,
  score: 0.87,
  category: "high" as const,
  trust_level: "high" as const,
  freshness_multiplier: 1.0,
  ocr_quality_multiplier: 1.0,
  conflict_multiplier: 1.0,
  graph_evidence_boost: 0.0,
  verification_support_score: null,
  table_quality_multiplier: 1.0,
  extraction_quality_multiplier: 1.0,
  reasons: [],
};

const baseTrustMetadata: AnswerTrustMetadataResponse = {
  schema_version: "1",
  organization_id: "org-1",
  message_id: "msg-1",
  not_found: false,
  citation_validation_failed: false,
  verification_failed: false,
  confidence: baseTrustConfidence,
  citations: [baseTrustCitation],
  retrieval: {
    retrieval_count: 8,
    selected_count: 4,
    rerank_applied: true,
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
    applied: true,
    verdict: "partially_supported",
    score: 0.5,
    aggregate_support_score: 0.72,
    claim_count: 2,
    supported_count: 1,
    partially_supported_count: 0,
    unsupported_count: 1,
    unverifiable_count: 0,
    removed_count: 1,
    reason_codes: ["no_source"],
    claims: [
      {
        claim_index: 1,
        claim_text: "Employees receive 20 days of annual leave.",
        support_status: "supported",
        support_score: 0.92,
        evidence_match_score: 1.0,
        source_quality_score: 0.9,
        rerank_score: 0.88,
        chunk_coverage_score: 0.5,
        citation_indices: [1],
      },
      {
        claim_index: 2,
        claim_text: "Parking is free.",
        support_status: "unsupported",
        support_score: 0.12,
        evidence_match_score: 0.0,
        source_quality_score: 0.2,
        rerank_score: 0.15,
        chunk_coverage_score: 0.0,
        citation_indices: [],
      },
    ],
  },
  model: {
    llm_model: "gpt-4o",
    llm_provider: "openai",
    fallback_used: false,
    prompt_template_key: "answer_generation",
    prompt_template_version: 3,
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
  evidence_quality: {
    table_low_confidence_count: 0,
    extraction_warning_count: 0,
    processing_warning_count: 0,
    any_incomplete_documents: false,
    warning_reasons: [],
  },
  generated_at: "2026-06-26T10:00:00Z",
};

const noopOpen = vi.fn();

function renderPanel(
  overrides: Partial<Parameters<typeof AnswerTrustPanel>[0]> = {},
) {
  const props = {
    messageId: "msg-1",
    confidenceScore: 0.87,
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
    onOpenCitation: noopOpen,
    ...overrides,
  };
  const trustMetadata =
    overrides.trustMetadata ??
    ({
      ...baseTrustMetadata,
      citations: props.citations.map((citation) => ({
        ...citation,
        doc_stale_warning: citation.doc_stale_warning ?? false,
        doc_expired_warning: citation.doc_expired_warning ?? false,
        doc_is_excluded_status: citation.doc_is_excluded_status ?? false,
        doc_ocr_low_confidence_warning:
          citation.doc_ocr_low_confidence_warning ?? false,
        doc_unreviewed_warning: false,
        doc_deprecated_warning: false,
        is_table_chunk: citation.is_table_chunk ?? false,
        table_headers: citation.table_headers ?? [],
        table_low_confidence_warning: false,
        doc_extraction_warning: false,
        doc_processing_warning: false,
      })),
      grounded_verification: {
        ...baseTrustMetadata.grounded_verification,
        claims: baseTrustMetadata.grounded_verification.claims.map((claim) => {
          const citationIndices = claim.citation_indices.filter(
            (index) => index <= props.citations.length,
          );
          return { ...claim, citation_indices: citationIndices };
        }),
      },
    } satisfies AnswerTrustMetadataResponse);
  return render(<AnswerTrustPanel {...props} trustMetadata={trustMetadata} />);
}

describe("AnswerTrustPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the trust panel with testid", () => {
    renderPanel();
    expect(screen.getByTestId("trust-panel-msg-1")).toBeInTheDocument();
  });

  it("shows 'Answer Explanation' header", () => {
    renderPanel();
    expect(screen.getByText("Answer Explanation")).toBeInTheDocument();
  });

  it("displays the confidence score as a percentage", () => {
    renderPanel();
    expect(screen.getByText("87.0%")).toBeInTheDocument();
  });

  it("shows the trust level badge when trust_level is present", () => {
    renderPanel();
    expect(screen.getByTestId("trust-level-badge")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
  });

  it("renders a readable source-selection summary in basic mode", () => {
    renderPanel({
      trustMetadata: {
        ...baseTrustMetadata,
        retrieval: {
          ...baseTrustMetadata.retrieval,
          retrieval_candidate_count: 8,
          retrieval_count: 8,
          selected_count: 4,
          top_k: 4,
          search_mode: "hybrid",
          source_scope_mode: "collections",
          source_scope_label: "Selected collection · Finance",
          retrieval_profile_name: "Finance QA",
          retrieval_profile_scope: "selected collection",
          retrieval_profile_source: "org_default",
          retrieval_filters: ["scope_mode=collections", "collections=1"],
          rerank_applied: true,
          rerank_provider: "openai",
          rerank_model: "cohere-rerank-v3",
          rerank_score_min: 0.71,
          rerank_score_max: 0.93,
          rerank_fallback_used: false,
          rerank_fallback_reason: null,
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
          request_id: "req-123",
          trace_request_id: "trace-123",
        },
      } satisfies AnswerTrustMetadataResponse,
    });

    expect(screen.getByText("Source selection")).toBeInTheDocument();
    expect(
      screen.getByText(/Scope: Selected collection · Finance/),
    ).toBeInTheDocument();
    expect(screen.getByText(/4 chunks selected/)).toBeInTheDocument();
    expect(screen.getByText(/Request req-123/)).toBeInTheDocument();
  });

  it("reveals expert retrieval diagnostics when allowed", () => {
    renderPanel({ showInterpretationDetails: true });

    expect(
      screen.queryByText(/retrieval diagnostics/i),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Expert" }));

    expect(screen.getByText(/retrieval diagnostics/i)).toBeInTheDocument();
  });

  it("tracks retrieval diagnostics usage for telemetry", async () => {
    renderPanel();

    await waitFor(() => {
      expect(trackFeatureEvent).toHaveBeenCalledWith(
        "feature.chat.retrieval_diagnostics_viewed",
        expect.objectContaining({
          featureArea: "chat",
          pageKey: "chat",
          route: "/chat",
          source: "trust_panel",
          status: "basic",
        }),
      );
    });
  });

  it("shows claim support summary and mapped citations", () => {
    renderPanel();
    expect(screen.getByText(/claim support/i)).toBeInTheDocument();
    expect(
      screen.getByText(/1\/2 claim\(s\) are not supported by citations/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Employees receive 20 days of annual leave."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /preview source 1 for claim 1/i }),
    ).toBeInTheDocument();
  });

  it("renders a confidence progress bar with correct aria attributes", () => {
    renderPanel();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "87");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });

  it("shows component score rows when explanation is provided", () => {
    renderPanel();
    expect(screen.getByText("Top similarity")).toBeInTheDocument();
    expect(screen.getByText("0.921")).toBeInTheDocument();
    expect(screen.getByText("Citation coverage")).toBeInTheDocument();
    expect(screen.getByText("95.0%")).toBeInTheDocument();
  });

  it("does not show explanation scores when confidenceExplanation is null", () => {
    renderPanel({ confidenceExplanation: null });
    expect(screen.queryByText("Top similarity")).not.toBeInTheDocument();
  });

  it("renders the Sources section with citation filename", () => {
    renderPanel();
    expect(screen.getByText("Sources (1)")).toBeInTheDocument();
    expect(screen.getByText("policy.pdf")).toBeInTheDocument();
  });

  it("shows citation page reference", () => {
    renderPanel();
    expect(screen.getByText("p. 3")).toBeInTheDocument();
  });

  it("shows Trusted badge for trusted citation", () => {
    renderPanel();
    expect(screen.getByText("Trusted")).toBeInTheDocument();
  });

  it("shows Preferred conflict badge", () => {
    renderPanel();
    expect(screen.getByText("Preferred")).toBeInTheDocument();
  });

  it("shows Stale badge for stale/expired citation", () => {
    const staleCitation = {
      ...baseCitation,
      doc_stale_warning: true,
      doc_expired_warning: false,
    } as unknown as ChatCitationResponse;
    renderPanel({ citations: [staleCitation] });
    expect(screen.getByText(/^Stale$/)).toBeInTheDocument();
  });

  it("shows Expired badge for expired citation", () => {
    const expiredCitation = {
      ...baseCitation,
      doc_expired_warning: true,
      doc_stale_warning: false,
    } as unknown as ChatCitationResponse;
    renderPanel({ citations: [expiredCitation] });
    expect(screen.getByText(/^Expired$/)).toBeInTheDocument();
  });

  it("shows OCR low confidence badge when warned", () => {
    const ocrCitation = {
      ...baseCitation,
      doc_ocr_quality_status: "low",
      doc_ocr_low_confidence_warning: true,
    } as unknown as ChatCitationResponse;
    renderPanel({ citations: [ocrCitation] });
    expect(screen.getByText(/OCR low confidence/i)).toBeInTheDocument();
  });

  it("calls onOpenCitation when citation preview button is clicked", () => {
    const handler = vi.fn();
    renderPanel({ onOpenCitation: handler });
    fireEvent.click(
      screen.getByRole("button", { name: /preview policy\.pdf/i }),
    );
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({
        document_id: baseCitation.document_id,
        chunk_id: baseCitation.chunk_id,
        filename: baseCitation.filename,
        page_number: baseCitation.page_number,
      }),
    );
  });

  it("shows expert retrieval diagnostics after switching modes", () => {
    renderPanel({
      showInterpretationDetails: true,
      trustMetadata: {
        ...baseTrustMetadata,
        retrieval: {
          ...baseTrustMetadata.retrieval,
          rerank_model: "cohere-rerank-v3",
          rerank_provider: "openai",
        },
      } satisfies AnswerTrustMetadataResponse,
    });
    fireEvent.click(screen.getByRole("tab", { name: "Expert" }));
    expect(screen.getByText("Retrieval Diagnostics")).toBeInTheDocument();
    expect(screen.getByText("Candidates")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("Selected chunks")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("Reranker")).toBeInTheDocument();
    expect(screen.getByText("cohere-rerank-v3")).toBeInTheDocument();
  });

  it("shows hybrid retrieval stats when enabled", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      hybrid_retrieval_enabled: true,
      hybrid_vector_hit_count: 5,
      hybrid_keyword_hit_count: 3,
    };
    renderPanel({
      debug,
      showInterpretationDetails: true,
      trustMetadata: {
        ...baseTrustMetadata,
        retrieval: {
          ...baseTrustMetadata.retrieval,
          hybrid_retrieval_enabled: true,
          hybrid_vector_hit_count: 5,
          hybrid_keyword_hit_count: 3,
        },
      } satisfies AnswerTrustMetadataResponse,
    });
    fireEvent.click(screen.getByRole("tab", { name: "Expert" }));
    expect(screen.getByText("Vector hits")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Keyword hits")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("renders the Model section with provider and model", () => {
    renderPanel();
    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByText("Provider")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("LLM model")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("text-embedding-3-large")).toBeInTheDocument();
  });

  it("shows fallback info when fallback was used", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      fallback_used: true,
      fallback_from: "gpt-4-turbo",
      fallback_to: "gpt-3.5-turbo",
      fallback_reason: "rate_limit",
    };
    renderPanel({ debug });
    expect(screen.getByText("Fallback from")).toBeInTheDocument();
    expect(screen.getByText("gpt-4-turbo")).toBeInTheDocument();
    expect(screen.getByText("Fallback to")).toBeInTheDocument();
    expect(screen.getByText("gpt-3.5-turbo")).toBeInTheDocument();
  });

  it("renders Knowledge Graph section when graph was used", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      graph_context_enabled: true,
      graph_context_used: true,
      graph_seed_entity_count: 3,
      graph_related_entity_count: 12,
      graph_chunk_count: 5,
      graph_max_hops_used: 2,
      graph_relation_types_used: ["RELATES_TO", "CITES"],
    };
    renderPanel({ debug });
    expect(screen.getByText("Knowledge Graph")).toBeInTheDocument();
    expect(screen.getByText("Seed entities")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("RELATES_TO, CITES")).toBeInTheDocument();
  });

  it("shows graph unavailable message when graph could not be used", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      graph_context_enabled: true,
      graph_context_used: false,
      graph_context_unavailable: true,
      graph_context_reason: "Graph index not ready.",
    };
    renderPanel({ debug });
    expect(screen.getByText("Knowledge Graph")).toBeInTheDocument();
    expect(screen.getByText("Graph index not ready.")).toBeInTheDocument();
  });

  it("does not render Knowledge Graph section when not enabled", () => {
    renderPanel({ debug: { ...baseDebug, graph_context_enabled: false } });
    expect(screen.queryByText("Knowledge Graph")).not.toBeInTheDocument();
  });

  it("renders Verification section when applied", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      grounded_verification_applied: true,
      grounded_verification_verdict: "grounded",
      grounded_verification_score: 0.94,
      grounded_verification_claim_count: 8,
      grounded_verification_supported_count: 8,
      grounded_verification_unsupported_count: 0,
      grounded_verification_removed_count: 0,
    };
    renderPanel({ debug });
    expect(screen.getByText("Verification")).toBeInTheDocument();
    expect(screen.getByText("Verdict")).toBeInTheDocument();
    expect(screen.getByText("grounded")).toBeInTheDocument();
    expect(screen.getByText("Claims checked")).toBeInTheDocument();
  });

  it("does not render Verification section when not applied", () => {
    renderPanel({
      debug: { ...baseDebug, grounded_verification_applied: false },
      trustMetadata: {
        ...baseTrustMetadata,
        grounded_verification: {
          ...baseTrustMetadata.grounded_verification,
          applied: false,
        },
      },
    });
    expect(screen.queryByText("Verification")).not.toBeInTheDocument();
  });

  it("renders Policy section when policy was applied", () => {
    renderPanel({
      policyApplied: true,
      policyOutcome: "warned",
      policyViolatedRules: ["no-external-links"],
      policyWarningFlags: ["citation_count_low"],
      policyDisclaimer: null,
    });
    expect(screen.getByText("Policy")).toBeInTheDocument();
    expect(screen.getByText("warned")).toBeInTheDocument();
    expect(screen.getByText("no-external-links")).toBeInTheDocument();
    expect(screen.getByText("citation_count_low")).toBeInTheDocument();
  });

  it("does not render Policy section when policy was not applied", () => {
    renderPanel({ policyApplied: false });
    expect(screen.queryByText("Policy")).not.toBeInTheDocument();
  });

  it("shows low confidence warning banner", () => {
    renderPanel({ confidenceCategory: "low" });
    expect(
      screen.getByText(/Low confidence — validate this answer/i),
    ).toBeInTheDocument();
  });

  it("shows citation validation failed warning", () => {
    renderPanel({ citationValidationFailed: true });
    expect(screen.getByText(/Citation validation failed/i)).toBeInTheDocument();
  });

  it("shows source freshness warning when set", () => {
    renderPanel({
      sourceFreshnessWarning: true,
      sourceFreshnessWarningReason: "Source is 6 months old.",
    });
    expect(screen.getByText("Source is 6 months old.")).toBeInTheDocument();
  });

  it("shows stale citation warning banner", () => {
    const staleCitation = {
      ...baseCitation,
      doc_stale_warning: true,
    } as unknown as ChatCitationResponse;
    renderPanel({ citations: [staleCitation] });
    expect(
      screen.getByText(/One or more cited sources are stale or expired/i),
    ).toBeInTheDocument();
  });

  it("shows OCR warning banner for low-confidence source", () => {
    const ocrCitation = {
      ...baseCitation,
      doc_ocr_low_confidence_warning: true,
    } as unknown as ChatCitationResponse;
    renderPanel({ citations: [ocrCitation] });
    expect(screen.getByText(/low OCR confidence/i)).toBeInTheDocument();
  });

  it("shows removed claims warning banner", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      grounded_verification_applied: true,
      grounded_verification_removed_count: 2,
    };
    renderPanel({ debug });
    expect(
      screen.getByText(/2 unsupported claim\(s\) were removed/i),
    ).toBeInTheDocument();
  });

  it("shows policy disclaimer as a warning banner", () => {
    renderPanel({
      policyApplied: true,
      policyDisclaimer: "This answer is provided for informational purposes.",
    });
    expect(
      screen.getByText("This answer is provided for informational purposes."),
    ).toBeInTheDocument();
  });

  it("shows parent context expansion stats when enabled", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      parent_context_expansion_enabled: true,
      parent_context_expanded_count: 3,
      parent_context_tokens_used: 1240,
    };
    renderPanel({
      debug,
      showInterpretationDetails: true,
      trustMetadata: {
        ...baseTrustMetadata,
        retrieval: {
          ...baseTrustMetadata.retrieval,
          rerank_model: "cohere-rerank-v3",
          rerank_provider: "openai",
        },
      } satisfies AnswerTrustMetadataResponse,
    });
    fireEvent.click(screen.getByRole("tab", { name: "Expert" }));
    expect(screen.getByText("Parent expansion")).toBeInTheDocument();
    expect(screen.getByText("3 chunks")).toBeInTheDocument();
    expect(screen.getByText("Parent tokens")).toBeInTheDocument();
    expect(screen.getByText("1240")).toBeInTheDocument();
  });

  it("does not expose raw rewrite preview in retrieval stats", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      query_rewriting_applied: true,
      rewritten_query: "What is the leave policy?",
    };
    renderPanel({ debug });
    expect(screen.queryByText("Rewritten query")).not.toBeInTheDocument();
    expect(
      screen.queryByText("What is the leave policy?"),
    ).not.toBeInTheDocument();
  });

  it("shows safe query interpretation when advanced diagnostics are enabled", () => {
    const queryInterpretation: QueryInterpretationRecord = {
      intent: "policy",
      intent_label: "Policy",
      complexity: "complex",
      retrieval_strategy: "rewrite",
      rewrite_preview_enabled: true,
      rewritten_query_preview: "What is the leave policy for contractors?",
      sub_queries: [],
    };
    renderPanel({
      showInterpretationDetails: true,
      trustMetadata: {
        ...baseTrustMetadata,
        query_interpretation: queryInterpretation,
      },
    });
    expect(screen.getByText("Query Interpretation")).toBeInTheDocument();
    expect(screen.getByText("Policy")).toBeInTheDocument();
    expect(screen.getByText("rewrite")).toBeInTheDocument();
    expect(
      screen.getByText("What is the leave policy for contractors?"),
    ).toBeInTheDocument();
  });

  it("hides the rewrite preview when disabled by policy", () => {
    const queryInterpretation: QueryInterpretationRecord = {
      intent: "lookup",
      intent_label: "Lookup",
      complexity: "simple",
      retrieval_strategy: "original",
      rewrite_preview_enabled: false,
      rewritten_query_preview: null,
      sub_queries: [],
    };
    renderPanel({
      showInterpretationDetails: true,
      trustMetadata: {
        ...baseTrustMetadata,
        query_interpretation: queryInterpretation,
      },
    });
    expect(
      screen.getByText("Rewrite preview is disabled by organization policy."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Rewrite preview")).not.toBeInTheDocument();
  });

  it("shows prompt template when present", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      prompt_template_key: "rag_default",
      prompt_template_version: 4,
    };
    renderPanel({ debug });
    expect(screen.getByText("Prompt template")).toBeInTheDocument();
    expect(screen.getByText("rag_default v4")).toBeInTheDocument();
  });

  it("does not expose raw citation text snippets in the panel", () => {
    const citationWithSnippet = {
      ...baseCitation,
      text_snippet: "CONFIDENTIAL: Internal policy section 4.2...",
    } as unknown as ChatCitationResponse;
    renderPanel({ citations: [citationWithSnippet] });
    expect(
      screen.queryByText("CONFIDENTIAL: Internal policy section 4.2..."),
    ).not.toBeInTheDocument();
  });

  it("shows score and rerank score metadata for citations", () => {
    renderPanel();
    expect(screen.getByText(/Score 0.921/)).toBeInTheDocument();
    expect(screen.getByText(/Rerank 0.887/)).toBeInTheDocument();
  });

  it("shows Table badge for table chunks", () => {
    const tableCitation = {
      ...baseCitation,
      is_table_chunk: true,
      score: 0.8,
    } as unknown as ChatCitationResponse;
    renderPanel({ citations: [tableCitation] });
    expect(screen.getByText(/table/i)).toBeInTheDocument();
  });

  it("renders without citations gracefully", () => {
    renderPanel({ citations: [] });
    expect(screen.queryByText(/Sources/)).not.toBeInTheDocument();
  });

  it("renders without debug gracefully", () => {
    renderPanel({ debug: null });
    expect(screen.queryByText("Retrieval")).not.toBeInTheDocument();
    expect(screen.queryByText("Model")).not.toBeInTheDocument();
  });
});
