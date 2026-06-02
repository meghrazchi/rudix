import { apiRequest } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/schema";
import type { ChunkingProfileConfigInput } from "@/lib/schemas/chunking-profiles";

type Schemas = components["schemas"];

export type DocumentFileType = Schemas["DocumentDetailResponse"]["file_type"];
export type DocumentStatus = Schemas["DocumentStatus"];
export type DocumentSortBy = Schemas["DocumentListResponse"]["sort_by"];
export type SortOrder = Schemas["DocumentListResponse"]["sort_order"];
export type DocumentErrorDetails = Schemas["DocumentErrorDetails"];
export type UploadDocumentResponse = Schemas["UploadDocumentResponse"] & {
  duplicate_detected?: boolean;
  duplicate_document_id?: string | null;
};
export type DeleteDocumentResponse = Schemas["DeleteDocumentResponse"];
export type ReindexDocumentResponse = Schemas["ReindexDocumentResponse"];
export type DocumentStatusResponse = Schemas["DocumentStatusResponse"];
export type DocumentChunkTokenDistributionResponse = {
  min_tokens: number;
  max_tokens: number;
  avg_tokens: number;
  total_tokens: number;
};
export type DocumentChunkingAdaptiveSignalsResponse = {
  file_type: string;
  page_count: number;
  total_token_count: number;
  ocr_applied: boolean;
  heading_density?: number | null;
  avg_chars_per_page?: number | null;
  avg_paragraph_tokens?: number | null;
};
export type DocumentChunkingDiagnosticsResponse = {
  strategy?: string | null;
  selected_strategy?: string | null;
  profile_version?: string | null;
  profile_source?: string | null;
  chunk_size_tokens?: number | null;
  chunk_overlap_tokens?: number | null;
  embedding_model?: string | null;
  index_version?: string | null;
  ocr_applied?: boolean | null;
  hierarchical_mode?: boolean;
  parent_chunk_count?: number | null;
  child_chunk_count?: number | null;
  reason_codes: string[];
  adaptive_signals?: DocumentChunkingAdaptiveSignalsResponse | null;
  token_distribution?: DocumentChunkTokenDistributionResponse | null;
};
export type DocumentCollectionSummary = {
  collection_id: string;
  name: string;
};

export type DocumentListItemResponse = Schemas["DocumentListItemResponse"] & {
  source?: string | null;
  language?: string | null;
  retention_class?: string | null;
  notes?: string | null;
  tags?: string[];
  collections?: DocumentCollectionSummary[];
};
export type DocumentListResponse = Omit<
  Schemas["DocumentListResponse"],
  "items"
> & {
  items: DocumentListItemResponse[];
};
export type DocumentLifecycleTimelineStepResponse =
  Schemas["DocumentLifecycleTimelineStepResponse"];
export type DocumentDetailResponse = Omit<
  Schemas["DocumentDetailResponse"],
  "chunking_diagnostics" | "language"
> & {
  language?: string | null;
  chunking_diagnostics?: DocumentChunkingDiagnosticsResponse | null;
};
export type DocumentChunkPreviewResponse =
  Schemas["DocumentChunkPreviewResponse"] & {
    section_path?: string | null;
    language?: string | null;
    chunk_level?: number | null;
    child_count?: number | null;
    source_start_offset?: number | null;
    source_end_offset?: number | null;
  };
export type DocumentChunksResponse = Omit<
  Schemas["DocumentChunksResponse"],
  "items"
> & {
  items: DocumentChunkPreviewResponse[];
};
export type CreateUploadUrlRequest = Schemas["CreateUploadUrlRequest"];
export type CreateUploadUrlResponse = Schemas["CreateUploadUrlResponse"];

export type UploadDocumentMetadata = {
  collection_id?: string | null;
  source?: string | null;
  language?: string | null;
  retention_class?: string | null;
  notes?: string | null;
  tags?: string[];
};

export const UPLOAD_LANGUAGES: ReadonlyArray<{ code: string; label: string }> =
  [
    { code: "en", label: "English" },
    { code: "de", label: "German" },
    { code: "fr", label: "French" },
    { code: "es", label: "Spanish" },
    { code: "pt", label: "Portuguese" },
    { code: "it", label: "Italian" },
    { code: "nl", label: "Dutch" },
    { code: "pl", label: "Polish" },
    { code: "sv", label: "Swedish" },
    { code: "no", label: "Norwegian" },
    { code: "da", label: "Danish" },
    { code: "fi", label: "Finnish" },
    { code: "cs", label: "Czech" },
    { code: "sk", label: "Slovak" },
    { code: "hu", label: "Hungarian" },
    { code: "ro", label: "Romanian" },
    { code: "bg", label: "Bulgarian" },
    { code: "el", label: "Greek" },
    { code: "tr", label: "Turkish" },
    { code: "ar", label: "Arabic" },
    { code: "fa", label: "Persian" },
    { code: "zh", label: "Chinese" },
    { code: "ja", label: "Japanese" },
    { code: "ko", label: "Korean" },
    { code: "ru", label: "Russian" },
    { code: "uk", label: "Ukrainian" },
  ];

export const UPLOAD_RETENTION_CLASSES: ReadonlyArray<{
  value: string;
  label: string;
}> = [
  { value: "standard", label: "Standard" },
  { value: "confidential", label: "Confidential" },
  { value: "legal_hold", label: "Legal Hold" },
  { value: "archive", label: "Archive" },
  { value: "gdpr_restricted", label: "GDPR Restricted" },
];

export type ListDocumentsOptions = {
  limit?: number;
  offset?: number;
  status?: DocumentStatus;
  file_type?: DocumentFileType;
  sort_by?: DocumentSortBy;
  sort_order?: SortOrder;
  filename_query?: string;
};

export type DocumentChunksOptions = {
  limit?: number;
  offset?: number;
  include_full_text?: boolean;
};

export type ReindexDocumentRequest = {
  chunking_profile_id?: string | null;
  chunking_profile_config?: ChunkingProfileConfigInput | null;
};

export async function uploadDocument(
  file: File,
  metadata?: UploadDocumentMetadata,
  signal?: AbortSignal,
): Promise<UploadDocumentResponse> {
  const formData = new FormData();
  formData.set("file", file);
  if (metadata?.collection_id) {
    formData.set("collection_id", metadata.collection_id);
  }
  if (metadata?.source) {
    formData.set("source", metadata.source);
  }
  if (metadata?.language) {
    formData.set("language", metadata.language);
  }
  if (metadata?.retention_class) {
    formData.set("retention_class", metadata.retention_class);
  }
  if (metadata?.notes) {
    formData.set("notes", metadata.notes);
  }
  if (metadata?.tags?.length) {
    formData.set("tags", metadata.tags.join(","));
  }

  return apiRequest<UploadDocumentResponse>("/documents/upload", {
    method: "POST",
    body: formData,
    signal,
  });
}

export async function createUploadUrl(
  payload: CreateUploadUrlRequest,
): Promise<CreateUploadUrlResponse> {
  return apiRequest<CreateUploadUrlResponse>("/documents/upload-url", {
    method: "POST",
    json: payload,
  });
}

export async function listDocuments(
  options: ListDocumentsOptions = {},
): Promise<DocumentListResponse> {
  return apiRequest<DocumentListResponse>("/documents", {
    query: {
      limit: options.limit,
      offset: options.offset,
      status: options.status,
      file_type: options.file_type,
      sort_by: options.sort_by,
      sort_order: options.sort_order,
      filename_query: options.filename_query || undefined,
    },
  });
}

export async function getDocument(
  documentId: string,
): Promise<DocumentDetailResponse> {
  return apiRequest<DocumentDetailResponse>(
    `/documents/${encodeURIComponent(documentId)}`,
  );
}

export async function getDocumentStatus(
  documentId: string,
): Promise<DocumentStatusResponse> {
  return apiRequest<DocumentStatusResponse>(
    `/documents/${encodeURIComponent(documentId)}/status`,
  );
}

export async function getDocumentChunks(
  documentId: string,
  options: DocumentChunksOptions = {},
): Promise<DocumentChunksResponse> {
  return apiRequest<DocumentChunksResponse>(
    `/documents/${encodeURIComponent(documentId)}/chunks`,
    {
      query: {
        limit: options.limit,
        offset: options.offset,
        include_full_text: options.include_full_text,
      },
    },
  );
}

export async function deleteDocument(
  documentId: string,
): Promise<DeleteDocumentResponse> {
  return apiRequest<DeleteDocumentResponse>(
    `/documents/${encodeURIComponent(documentId)}`,
    {
      method: "DELETE",
    },
  );
}

export async function reindexDocument(
  documentId: string,
  payload?: ReindexDocumentRequest,
): Promise<ReindexDocumentResponse> {
  return apiRequest<ReindexDocumentResponse>(
    `/documents/${encodeURIComponent(documentId)}/reindex`,
    {
      method: "POST",
      json: payload,
    },
  );
}

export async function downloadDocumentFile(documentId: string): Promise<Blob> {
  return apiRequest<Blob>(
    `/documents/${encodeURIComponent(documentId)}/download`,
    {
      responseType: "blob",
    },
  );
}
