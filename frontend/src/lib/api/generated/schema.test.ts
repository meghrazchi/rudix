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
  ChatCitationResponse,
  ChatSessionMessageListResponse,
} from "@/lib/api/chat";
import type {
  EvaluationRunDetailResponse,
  EvaluationQuestionListResponse,
} from "@/lib/api/evaluations";

type Schemas = components["schemas"];

// Verify that the re-exported types from API modules are identical to the
// generated schema types. If a Pydantic model changes and openapi.json is
// regenerated, these assertions will catch any divergence at typecheck time.

describe("generated schema types", () => {
  it("document types match generated schema", () => {
    // DocumentListResponse augments the schema items with optional frontend fields
    // (collections, tags, source, language, etc.); verify only the envelope shape.
    expectTypeOf<
      Omit<DocumentListResponse, "items" | "freshness" | "quality_state">
    >().toEqualTypeOf<Omit<Schemas["DocumentListResponse"], "items">>();
    expectTypeOf<
      Omit<
        DocumentDetailResponse,
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
        | "superseded_by_document_id"
      >
    >().toEqualTypeOf<Schemas["DocumentDetailResponse"]>();
    expectTypeOf<Omit<DocumentChunksResponse, "items">>().toEqualTypeOf<
      Omit<Schemas["DocumentChunksResponse"], "items">
    >();
    expectTypeOf<
      Omit<
        DocumentChunksResponse["items"][number],
        | "section_path"
        | "language"
        | "chunk_level"
        | "child_count"
        | "source_start_offset"
        | "source_end_offset"
      >
    >().toEqualTypeOf<Schemas["DocumentChunkPreviewResponse"]>();
    expectTypeOf<DocumentStatus>().toEqualTypeOf<Schemas["DocumentStatus"]>();
  });

  it("chat types match generated schema", () => {
    expectTypeOf<
      Schemas["ChatQueryResponse"]
    >().toMatchTypeOf<ChatQueryResponse>();
    expectTypeOf<
      Schemas["ChatCitationResponse"]
    >().toMatchTypeOf<ChatCitationResponse>();
    expectTypeOf<
      Schemas["ChatSessionMessageListResponse"]
    >().toMatchTypeOf<ChatSessionMessageListResponse>();
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
});
