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
    expectTypeOf<Omit<DocumentListResponse, "items">>().toEqualTypeOf<
      Omit<Schemas["DocumentListResponse"], "items">
    >();
    expectTypeOf<
      Omit<DocumentDetailResponse, "chunking_diagnostics" | "language">
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
    expectTypeOf<ChatQueryResponse>().toEqualTypeOf<
      Schemas["ChatQueryResponse"]
    >();
    expectTypeOf<ChatCitationResponse>().toEqualTypeOf<
      Schemas["ChatCitationResponse"]
    >();
    expectTypeOf<ChatSessionMessageListResponse>().toEqualTypeOf<
      Schemas["ChatSessionMessageListResponse"]
    >();
  });

  it("evaluation types match generated schema", () => {
    expectTypeOf<EvaluationRunDetailResponse>().toEqualTypeOf<
      Schemas["EvaluationRunDetailResponse"]
    >();
    expectTypeOf<EvaluationQuestionListResponse>().toEqualTypeOf<
      Schemas["EvaluationQuestionListResponse"]
    >();
  });
});
