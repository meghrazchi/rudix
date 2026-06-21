import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { AnswerTrustPanel } from "@/components/chat/AnswerTrustPanel";
import type {
  ChatCitationResponse,
  ChatConfidenceExplanationResponse,
  ChatDebugResponse,
} from "@/lib/api/chat";

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
  return render(<AnswerTrustPanel {...props} />);
}

describe("AnswerTrustPanel", () => {
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

  it("shows the confidence category badge", () => {
    renderPanel();
    expect(screen.getByText("high")).toBeInTheDocument();
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
    expect(screen.getByText("Stale")).toBeInTheDocument();
  });

  it("shows Expired badge for expired citation", () => {
    const expiredCitation = {
      ...baseCitation,
      doc_expired_warning: true,
      doc_stale_warning: false,
    } as unknown as ChatCitationResponse;
    renderPanel({ citations: [expiredCitation] });
    expect(screen.getByText("Expired")).toBeInTheDocument();
  });

  it("shows OCR low confidence badge when warned", () => {
    const ocrCitation = {
      ...baseCitation,
      doc_ocr_quality_status: "low",
      doc_ocr_low_confidence_warning: true,
    } as unknown as ChatCitationResponse;
    renderPanel({ citations: [ocrCitation] });
    expect(screen.getByText("OCR low confidence")).toBeInTheDocument();
  });

  it("calls onOpenCitation when citation preview button is clicked", () => {
    const handler = vi.fn();
    renderPanel({ onOpenCitation: handler });
    fireEvent.click(screen.getByRole("button", { name: /preview policy\.pdf/i }));
    expect(handler).toHaveBeenCalledWith(baseCitation);
  });

  it("renders the Retrieval section with chunk counts", () => {
    renderPanel();
    expect(screen.getByText("Retrieval")).toBeInTheDocument();
    expect(screen.getByText("Retrieved chunks")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("Selected chunks")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("shows reranker model in Retrieval section", () => {
    renderPanel();
    expect(screen.getByText("cohere-rerank-v3")).toBeInTheDocument();
  });

  it("shows hybrid retrieval stats when enabled", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      hybrid_retrieval_enabled: true,
      hybrid_vector_hit_count: 5,
      hybrid_keyword_hit_count: 3,
    };
    renderPanel({ debug });
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
    renderPanel({ debug: { ...baseDebug, grounded_verification_applied: false } });
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
    expect(
      screen.getByText(/Citation validation failed/i),
    ).toBeInTheDocument();
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
    expect(
      screen.getByText(/low OCR confidence/i),
    ).toBeInTheDocument();
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
    renderPanel({ debug });
    expect(screen.getByText("Parent expansion")).toBeInTheDocument();
    expect(screen.getByText("3 chunks")).toBeInTheDocument();
    expect(screen.getByText("Parent tokens")).toBeInTheDocument();
    expect(screen.getByText("1240")).toBeInTheDocument();
  });

  it("shows query rewriting stats when applied", () => {
    const debug: ChatDebugResponse = {
      ...baseDebug,
      query_rewriting_applied: true,
      rewritten_query: "What is the leave policy?",
    };
    renderPanel({ debug });
    expect(screen.getByText("Rewritten query")).toBeInTheDocument();
    expect(screen.getByText("What is the leave policy?")).toBeInTheDocument();
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
    expect(screen.getByText(/Table/)).toBeInTheDocument();
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
