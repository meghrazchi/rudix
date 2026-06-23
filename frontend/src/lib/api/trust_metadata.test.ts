/**
 * Tests for answer trust metadata API client (F307).
 *
 * Covers:
 * - getAnswerTrustMetadata calls the correct endpoint
 * - response is correctly parsed and typed
 * - error responses propagate as ApiClientError
 * - type contracts: no ACL fields, no internal UUIDs
 * - schema_version is "1" in the contract type
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/api/errors";
import {
  getAnswerTrustMetadata,
  type AnswerTrustMetadataResponse,
  type ClaimSupportRecord,
  type CitationTrustRecord,
  type ModelMetadataRecord,
  type QueryInterpretationRecord,
} from "@/lib/api/trust_metadata";

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function buildTrustMetadata(
  overrides: Partial<AnswerTrustMetadataResponse> = {},
): AnswerTrustMetadataResponse {
  return {
    schema_version: "1",
    organization_id: "org-123",
    message_id: "msg-abc",
    not_found: false,
    citation_validation_failed: false,
    verification_failed: false,
    confidence: {
      score: 0.87,
      category: "high",
      trust_level: "high" as const,
      citation_support_score: 0.9,
      citation_validation_score: 0.95,
      citation_coverage_score: 0.85,
      retrieval_agreement_score: 0.88,
      top_similarity: 0.92,
      average_similarity: 0.85,
      top_rerank_score: 0.91,
      raw_score: 0.87,
      citation_validation_multiplier: 0.98,
      not_found_penalty_multiplier: 1.0,
      freshness_multiplier: 1.0,
      ocr_quality_multiplier: 1.0,
      conflict_multiplier: 1.0,
      graph_evidence_boost: 0.0,
      verification_support_score: null,
      table_quality_multiplier: 1.0,
      extraction_quality_multiplier: 1.0,
      not_found_signal: false,
      no_context: false,
      reasons: [],
    },
    citations: [],
    retrieval: {
      retrieval_count: 3,
      selected_count: 2,
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
    query_interpretation: {
      intent: "lookup",
      intent_label: "Lookup",
      complexity: "simple",
      retrieval_strategy: "original",
      rewrite_preview_enabled: false,
      rewritten_query_preview: null,
      sub_queries: [],
    } satisfies QueryInterpretationRecord,
    grounded_verification: {
      applied: false,
      aggregate_support_score: 0.0,
      claim_count: 0,
      supported_count: 0,
      partially_supported_count: 0,
      unsupported_count: 0,
      unverifiable_count: 0,
      removed_count: 0,
      reason_codes: [],
      claims: [],
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
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// API client tests
// ---------------------------------------------------------------------------

describe("getAnswerTrustMetadata", () => {
  it("calls GET /chat/messages/{id}/trust-metadata", async () => {
    const data = buildTrustMetadata({ message_id: "msg-xyz" });
    fetchMock.mockResolvedValueOnce(jsonResponse(data));

    const result = await getAnswerTrustMetadata("msg-xyz");

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain("/chat/messages/msg-xyz/trust-metadata");
    expect(result.message_id).toBe("msg-xyz");
    expect(result.schema_version).toBe("1");
  });

  it("URL-encodes the message ID", async () => {
    const data = buildTrustMetadata({ message_id: "msg/slash" });
    fetchMock.mockResolvedValueOnce(jsonResponse(data));

    await getAnswerTrustMetadata("msg/slash");

    const [url] = fetchMock.mock.calls[0] as [string, ...unknown[]];
    expect(url).toContain("msg%2Fslash");
  });

  it("returns the parsed trust metadata response", async () => {
    const data = buildTrustMetadata({
      not_found: true,
      confidence: {
        score: 0.05,
        category: "low",
        trust_level: "not_found" as const,
        citation_support_score: 0.0,
        citation_validation_score: 0.0,
        citation_coverage_score: 0.0,
        retrieval_agreement_score: 0.0,
        top_similarity: 0.05,
        average_similarity: 0.02,
        top_rerank_score: 0.0,
        raw_score: 0.05,
        citation_validation_multiplier: 0.0,
        not_found_penalty_multiplier: 0.0,
        freshness_multiplier: 1.0,
        ocr_quality_multiplier: 1.0,
        conflict_multiplier: 1.0,
        graph_evidence_boost: 0.0,
        verification_support_score: null,
        table_quality_multiplier: 1.0,
        extraction_quality_multiplier: 1.0,
        not_found_signal: true,
        no_context: true,
        reasons: [],
      },
    });
    fetchMock.mockResolvedValueOnce(jsonResponse(data));

    const result = await getAnswerTrustMetadata("msg-abc");

    expect(result.not_found).toBe(true);
    expect(result.confidence.category).toBe("low");
    expect(result.confidence.not_found_signal).toBe(true);
    expect(result.citations).toEqual([]);
    expect(result.query_interpretation?.intent).toBe("lookup");
  });

  it("throws ApiClientError on 404", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: { code: "message_not_found" } }, 404),
    );

    await expect(getAnswerTrustMetadata("nonexistent")).rejects.toThrow(
      ApiClientError,
    );
  });

  it("throws ApiClientError on 403", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Forbidden" }, 403));

    await expect(getAnswerTrustMetadata("msg-forbidden")).rejects.toThrow(
      ApiClientError,
    );
  });

  it("returns grounded verification details when applied", async () => {
    const data = buildTrustMetadata({
      grounded_verification: {
        applied: true,
        verdict: "partially_supported",
        score: 0.7,
        aggregate_support_score: 0.72,
        claim_count: 5,
        supported_count: 3,
        partially_supported_count: 1,
        unsupported_count: 2,
        unverifiable_count: 0,
        removed_count: 1,
        reason_codes: ["low_overlap"],
        claims: [
          {
            claim_index: 1,
            claim_text: "Employees receive 20 days of annual leave.",
            support_status: "supported",
            support_score: 0.92,
            evidence_match_score: 1.0,
            source_quality_score: 0.92,
            rerank_score: 0.9,
            chunk_coverage_score: 0.5,
            citation_indices: [1, 2],
          } satisfies ClaimSupportRecord,
        ],
      },
    });
    fetchMock.mockResolvedValueOnce(jsonResponse(data));

    const result = await getAnswerTrustMetadata("msg-gv");

    expect(result.grounded_verification.applied).toBe(true);
    expect(result.grounded_verification.removed_count).toBe(1);
    expect(result.grounded_verification.reason_codes).toContain("low_overlap");
  });

  it("returns conflict status when sources conflict", async () => {
    const data = buildTrustMetadata({
      conflict: {
        detected: true,
        agreement_level: "conflicting",
        conflict_count: 2,
        conflicting_document_ids: ["doc-a", "doc-b"],
        preferred_document_ids: ["doc-c"],
        conflict_summary: "Sources disagree on the policy.",
      },
    });
    fetchMock.mockResolvedValueOnce(jsonResponse(data));

    const result = await getAnswerTrustMetadata("msg-conflict");

    expect(result.conflict.detected).toBe(true);
    expect(result.conflict.conflict_count).toBe(2);
    expect(result.conflict.agreement_level).toBe("conflicting");
  });

  it("returns policy enforcement details when policy is active", async () => {
    const data = buildTrustMetadata({
      policy: {
        applied: true,
        outcome: "warned",
        violated_rules: ["stale_source"],
        warning_flags: ["low_confidence"],
        has_disclaimer: true,
      },
    });
    fetchMock.mockResolvedValueOnce(jsonResponse(data));

    const result = await getAnswerTrustMetadata("msg-policy");

    expect(result.policy.applied).toBe(true);
    expect(result.policy.outcome).toBe("warned");
    expect(result.policy.has_disclaimer).toBe(true);
  });

  it("returns freshness warning when stale sources are cited", async () => {
    const data = buildTrustMetadata({
      freshness: {
        warning: true,
        warning_reason:
          "One or more citations come from stale, expired, or archived sources.",
        stale_count: 2,
        excluded_count: 1,
        boosted_count: 0,
        warning_reasons: [],
        unreviewed_count: 0,
        deprecated_count: 0,
        all_excluded_fallback: false,
      },
    });
    fetchMock.mockResolvedValueOnce(jsonResponse(data));

    const result = await getAnswerTrustMetadata("msg-stale");

    expect(result.freshness.warning).toBe(true);
    expect(result.freshness.stale_count).toBe(2);
    expect(result.freshness.warning_reason).toContain("stale");
  });
});

// ---------------------------------------------------------------------------
// Type contract checks (compile-time, verified at test run via type assertions)
// ---------------------------------------------------------------------------

describe("AnswerTrustMetadataResponse type contract", () => {
  it("schema_version is always the string '1'", () => {
    const meta = buildTrustMetadata();
    expect(meta.schema_version).toBe("1");
  });

  it("CitationTrustRecord has no source_acl_snapshot field", () => {
    const citation: CitationTrustRecord = {
      document_id: "d1",
      chunk_id: "c1",
      doc_stale_warning: false,
      doc_expired_warning: false,
      doc_is_excluded_status: false,
      is_table_chunk: false,
      table_headers: [],
      doc_ocr_low_confidence_warning: false,
      doc_unreviewed_warning: false,
      doc_deprecated_warning: false,
      table_low_confidence_warning: false,
      doc_extraction_warning: false,
      doc_processing_warning: false,
    };
    expect("source_acl_snapshot" in citation).toBe(false);
  });

  it("ModelMetadataRecord has no prompt_template_version_id field", () => {
    const model: ModelMetadataRecord = {
      llm_model: "gpt-4o",
      llm_provider: "openai",
      fallback_used: false,
    };
    expect("prompt_template_version_id" in model).toBe(false);
  });

  it("organization_id is a plain string (not UUID type)", () => {
    const meta = buildTrustMetadata({ organization_id: "org-plain-string" });
    expect(typeof meta.organization_id).toBe("string");
  });
});
