import { describe, it, expectTypeOf } from "vitest";

import type { components } from "@/lib/api/generated/schema";
import type {
  DocumentListResponse,
  DocumentDetailResponse,
  DocumentStatus,
  DocumentChunksResponse,
} from "@/lib/api/documents";
import type {
  ChatQueryResponse,
  ChatQueryOverrides,
  ChatCitationResponse,
  ChatCitationOverrides,
  ChatSessionMessageListResponse,
} from "@/lib/api/chat";
import type {
  EvaluationRunDetailResponse,
  EvaluationQuestionListResponse,
} from "@/lib/api/evaluations";

import type { Served } from "@/lib/api/schema-helpers";
import type { ApiKey, ApiKeyListResponse } from "@/lib/api/api-keys";
import type { Webhook, WebhookDeliveryListResponse } from "@/lib/api/webhooks";
import type { TeamMember } from "@/lib/api/team";
import type {
  CitationTrustRecord,
  RetrievalDiagnosticsRecord,
  SourceFreshnessRecord,
  ClaimSupportRecord,
} from "@/lib/api/trust_metadata";
import type { KnowledgeGapResponse } from "@/lib/api/query-analytics";
import type { OrgQuotaPolicyResponse } from "@/lib/api/quotas";
import type { QuotaType } from "@/lib/api/quotas";
import type { QualityGateThresholds } from "@/lib/api/quality-gates";

type Schemas = components["schemas"];

// Verify that the re-exported types from API modules are identical to the
// generated schema types. If a Pydantic model changes and openapi.json is
// regenerated, these assertions will catch any divergence at typecheck time.
// Fields the frontend declares itself (overlays in the API modules) are
// omitted on both sides; every other field must match the generated schema.

describe("generated schema types", () => {
  it("document types match generated schema", () => {
    // DocumentListResponse augments the schema items with optional frontend fields
    // (collections, tags, source, language, etc.); verify only the envelope shape.
    expectTypeOf<
      Omit<DocumentListResponse, "items" | "freshness" | "quality_state">
    >().toEqualTypeOf<
      Omit<Schemas["DocumentListResponse"], "items" | "freshness" | "quality_state">
    >();
    type DetailOverrideKeys =
        | "chunking_diagnostics"
        | "language"
        | "graph_extraction_status"
        | "language_confidence"
        | "language_source"
        | "ocr_languages_override"
        | "ocr_quality_snapshot"
        | "extraction_snapshot"
        | "embedding_provider_type"
        | "embedding_vector_dimension"
        | "uploaded_by_user_id"
        | "uploaded_by_user_email"
        | "uploaded_by_user_display_name"
        | "source_provider"
        | "source_provider_label"
        | "source_title"
        | "source_key"
        | "source_url"
        | "source_link_allowed"
        | "source_last_synced_at"
        | "source_sync_version"
        | "source_visibility"
        | "source_trust_status"
        | "document_title"
        | "document_type"
        | "document_owner_id"
        | "document_owner_email"
        | "document_owner_display_name"
        | "document_version_label"
        | "document_last_updated_at"
        | "document_last_indexed_at"
        | "review_status"
        | "review_owner_id"
        | "review_due_date"
        | "expiry_date"
        | "trust_level"
        | "quality_state"
        | "quality_notes"
        | "trusted_by_id"
        | "trust_status"
        | "version_label"
        | "review_date"
        | "effective_date"
        | "trusted_at"
        | "stale_after_days"
        | "superseded_by_document_id";
    expectTypeOf<
      Omit<DocumentDetailResponse, DetailOverrideKeys>
    >().toEqualTypeOf<Omit<Schemas["DocumentDetailResponse"], DetailOverrideKeys>>();
    expectTypeOf<Omit<DocumentChunksResponse, "items">>().toEqualTypeOf<
      Omit<Schemas["DocumentChunksResponse"], "items">
    >();
    type ChunkOverrideKeys =
      | "section_path"
      | "language"
      | "chunk_level"
      | "child_count"
      | "source_start_offset"
      | "source_end_offset";
    expectTypeOf<
      Omit<DocumentChunksResponse["items"][number], ChunkOverrideKeys>
    >().toEqualTypeOf<
      Omit<Schemas["DocumentChunkPreviewResponse"], ChunkOverrideKeys>
    >();
    expectTypeOf<DocumentStatus>().toEqualTypeOf<Schemas["DocumentStatus"]>();
  });

  it("chat types match generated schema", () => {
    type QueryOverrideKeys =
      | keyof ChatQueryOverrides
      | "citation_validation_failed";
    expectTypeOf<
      Omit<Schemas["ChatQueryResponse"], QueryOverrideKeys>
    >().toMatchTypeOf<Omit<ChatQueryResponse, QueryOverrideKeys>>();
    expectTypeOf<
      Omit<Schemas["ChatCitationResponse"], keyof ChatCitationOverrides>
    >().toMatchTypeOf<Omit<ChatCitationResponse, keyof ChatCitationOverrides>>();
    type MessageOverrideKeys = "citations" | "trust_metadata";
    expectTypeOf<
      Omit<
        Schemas["ChatSessionMessageListResponse"]["items"][number],
        MessageOverrideKeys
      >
    >().toMatchTypeOf<
      Omit<ChatSessionMessageListResponse["items"][number], MessageOverrideKeys>
    >();
  });

  it("evaluation types match generated schema", () => {
    expectTypeOf<EvaluationRunDetailResponse>().toEqualTypeOf<
      Schemas["EvaluationRunDetailResponse"]
    >();
    expectTypeOf<
      Omit<
        EvaluationQuestionListResponse["items"][number],
        | "tags"
        | "difficulty"
        | "owner_id"
        | "question_language"
        | "expected_answer_language"
        | "source_language"
        | "translation_notes"
      >
    >().toEqualTypeOf<
      Omit<
        Schemas["EvaluationQuestionResponse"],
        | "tags"
        | "difficulty"
        | "owner_id"
        | "question_language"
        | "expected_answer_language"
        | "source_language"
        | "translation_notes"
      >
    >();
    expectTypeOf<Omit<EvaluationQuestionListResponse, "items">>().toEqualTypeOf<
      Omit<Schemas["EvaluationQuestionListResponse"], "items">
    >();
  });

  it("Served makes server-defaulted response fields required", () => {
    type Served1 = Served<{ a?: string; b?: { c?: number | null }[] }>;
    expectTypeOf<Served1>().toEqualTypeOf<{
      a: string;
      b: { c: number | null }[];
    }>();
  });

  it("response types keep the generated fields apart from declared overlays", () => {
    expectTypeOf<Omit<ApiKey, "status">>().toEqualTypeOf<
      Omit<Served<Schemas["ApiKeyResponse"]>, "status">
    >();
    expectTypeOf<ApiKey["status"]>().toEqualTypeOf<"active" | "revoked">();
    expectTypeOf<ApiKeyListResponse["items"][number]>().toEqualTypeOf<ApiKey>();
    expectTypeOf<Webhook["status"]>().toEqualTypeOf<"active" | "disabled">();
    expectTypeOf<WebhookDeliveryListResponse["next_cursor"]>().toEqualTypeOf<
      string | null
    >();
    expectTypeOf<Omit<TeamMember, "role" | "status">>().toEqualTypeOf<
      Omit<Served<Schemas["TeamMemberResponse"]>, "role" | "status">
    >();
    expectTypeOf<Omit<KnowledgeGapResponse, "gap_type" | "gap_source" | "status" | "converted_to">>()
      .toEqualTypeOf<
        Omit<
          Served<Schemas["KnowledgeGapResponse"]>,
          "gap_type" | "gap_source" | "status" | "converted_to"
        >
      >();
    expectTypeOf<OrgQuotaPolicyResponse["limits"]>().toEqualTypeOf<
      Partial<Record<QuotaType, Served<Schemas["QuotaLimitConfig"]>>>
    >();
  });

  it("request types come straight from the generated schema", () => {
    expectTypeOf<QualityGateThresholds>().toEqualTypeOf<
      Schemas["QualityGateThresholds"]
    >();
  });

  it("trust record fields older snapshots lack stay optional", () => {
    expectTypeOf<CitationTrustRecord["doc_draft_warning"]>().toEqualTypeOf<
      boolean | undefined
    >();
    expectTypeOf<SourceFreshnessRecord["draft_count"]>().toEqualTypeOf<
      number | undefined
    >();
    expectTypeOf<
      RetrievalDiagnosticsRecord["retrieval_candidate_count"]
    >().toEqualTypeOf<number | undefined>();
    expectTypeOf<ClaimSupportRecord["citation_indices"]>().toEqualTypeOf<
      number[]
    >();
  });
});
