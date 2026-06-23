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
export type BulkDeleteDocumentResult = {
  document_id: string;
  status:
    | "delete_requested"
    | "deleting"
    | "deleted"
    | "retained_by_policy"
    | "not_found"
    | "error";
  hold_reason?: string | null;
  error?: string | null;
};
export type BulkDeleteDocumentsResponse = {
  accepted: number;
  retained: number;
  errors: number;
  results: BulkDeleteDocumentResult[];
};
export type AdminDocumentDeletionItem = {
  document_id: string;
  filename: string;
  file_type: string;
  status: DocumentStatus;
  organization_id: string;
  deletion_requested_at?: string | null;
  deletion_hold_reason?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};
export type AdminDocumentDeletionListResponse = {
  items: AdminDocumentDeletionItem[];
  total: number;
  limit: number;
  offset: number;
};
export type RetryDeleteDocumentResponse = {
  document_id: string;
  status: "delete_requested" | "deleting";
  queue_status: "queued";
};
export type ReindexDocumentResponse = Schemas["ReindexDocumentResponse"];
export type ReindexDocumentGraphResponse = {
  document_id: string;
  status: "pending" | "extracting" | "completed" | "failed" | "skipped";
  queue_status: "queued";
};
export type DocumentStatusResponse = Schemas["DocumentStatusResponse"] & {
  graph_extraction_status?:
    | "pending"
    | "extracting"
    | "completed"
    | "failed"
    | "skipped"
    | null;
};
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
  embedding_provider_type?: string | null;
  embedding_vector_dimension?: number | null;
  ocr_applied?: boolean | null;
  hierarchical_mode?: boolean;
  parent_chunk_count?: number | null;
  child_chunk_count?: number | null;
  reason_codes: string[];
  adaptive_signals?: DocumentChunkingAdaptiveSignalsResponse | null;
  token_distribution?: DocumentChunkTokenDistributionResponse | null;
};
export type CitationPreviewResponse = {
  citation_id: string;
  document_id: string;
  chunk_id: string;
  filename: string;
  document_title?: string | null;
  document_type?: string | null;
  document_owner_id?: string | null;
  document_owner_email?: string | null;
  document_owner_display_name?: string | null;
  document_version_label?: string | null;
  document_last_updated_at?: string | null;
  document_last_indexed_at?: string | null;
  page_number?: number | null;
  chunk_index?: number | null;
  section_path?: string | null;
  source_section?: string | null;
  source_provider?: string | null;
  source_provider_label?: string | null;
  source_title?: string | null;
  source_key?: string | null;
  source_url?: string | null;
  source_link_allowed?: boolean;
  document_url: string;
  snippet: string;
  highlight_start_offset?: number | null;
  highlight_end_offset?: number | null;
  source_start_offset?: number | null;
  source_end_offset?: number | null;
  source_last_synced_at?: string | null;
  source_content_hash?: string | null;
  source_sync_version?: number | null;
  source_visibility?: string | null;
  source_trust_status?:
    | "trusted"
    | "stale"
    | "revoked"
    | "deleted"
    | "unknown"
    | "uploaded"
    | null;
  freshness_state?:
    | "current"
    | "stale"
    | "expired"
    | "deprecated"
    | "draft"
    | "unreviewed"
    | "unknown"
    | null;
  doc_trust_status?: string | null;
  doc_review_status?: string | null;
  doc_review_owner_id?: string | null;
  doc_review_due_date?: string | null;
  doc_expiry_date?: string | null;
  doc_version_label?: string | null;
  doc_review_date?: string | null;
  doc_effective_date?: string | null;
  doc_stale_warning?: boolean;
  doc_expired_warning?: boolean;
  doc_is_excluded_status?: boolean;
  doc_unreviewed_warning?: boolean;
  doc_deprecated_warning?: boolean;
  doc_ocr_quality_status?:
    | "high"
    | "medium"
    | "low"
    | "failed"
    | "not_required"
    | null;
  doc_ocr_low_confidence_warning?: boolean;
  request_id?: string | null;
};
export type DocumentCollectionSummary = {
  collection_id: string;
  name: string;
};

export type DocumentListItemResponse = Schemas["DocumentListItemResponse"] & {
  source?: string | null;
  source_provider?: string | null;
  source_provider_label?: string | null;
  graph_extraction_status?:
    | "pending"
    | "extracting"
    | "completed"
    | "failed"
    | "skipped"
    | null;
  language?: string | null;
  retention_class?: string | null;
  notes?: string | null;
  tags?: string[];
  collections?: DocumentCollectionSummary[];
  review_status?:
    | "current"
    | "trusted"
    | "needs_review"
    | "stale"
    | "expired"
    | "archived";
  review_owner_id?: string | null;
  review_due_date?: string | null;
  expiry_date?: string | null;
  trust_level?: string | null;
  trust_status?:
    | "draft"
    | "current"
    | "verified"
    | "stale"
    | "deprecated"
    | "superseded"
    | "expired";
  version_label?: string | null;
  review_date?: string | null;
};
export type DocumentListResponse = Omit<
  Schemas["DocumentListResponse"],
  "items"
> & {
  items: DocumentListItemResponse[];
  freshness?:
    | "current"
    | "trusted"
    | "needs_review"
    | "stale"
    | "expired"
    | "archived"
    | null;
};
export type DocumentLifecycleTimelineStepResponse =
  Schemas["DocumentLifecycleTimelineStepResponse"];
export type DocumentDetailResponse = Omit<
  Schemas["DocumentDetailResponse"],
  "chunking_diagnostics" | "language"
> & {
  graph_extraction_status?:
    | "pending"
    | "extracting"
    | "completed"
    | "failed"
    | "skipped"
    | null;
  language?: string | null;
  language_confidence?: number | null;
  language_source?: string | null;
  ocr_languages_override?: string | null;
  ocr_quality_snapshot?: OcrQualitySnapshot | null;
  extraction_snapshot?: ExtractionSnapshot | null;
  embedding_provider_type?: string | null;
  embedding_vector_dimension?: number | null;
  uploaded_by_user_id?: string | null;
  uploaded_by_user_email?: string | null;
  uploaded_by_user_display_name?: string | null;
  source_provider?: string | null;
  source_provider_label?: string | null;
  source_title?: string | null;
  source_key?: string | null;
  source_url?: string | null;
  source_link_allowed?: boolean;
  source_last_synced_at?: string | null;
  source_sync_version?: number | null;
  source_visibility?: string | null;
  source_trust_status?: string | null;
  document_title?: string | null;
  document_type?: string | null;
  document_owner_id?: string | null;
  document_owner_email?: string | null;
  document_owner_display_name?: string | null;
  document_version_label?: string | null;
  document_last_updated_at?: string | null;
  document_last_indexed_at?: string | null;
  chunking_diagnostics?: DocumentChunkingDiagnosticsResponse | null;
  review_status?:
    | "current"
    | "trusted"
    | "needs_review"
    | "stale"
    | "expired"
    | "archived";
  review_owner_id?: string | null;
  review_due_date?: string | null;
  expiry_date?: string | null;
  trust_level?: string | null;
  trust_status?:
    | "draft"
    | "current"
    | "verified"
    | "stale"
    | "deprecated"
    | "superseded"
    | "expired";
  version_label?: string | null;
  review_date?: string | null;
  effective_date?: string | null;
  trusted_at?: string | null;
  stale_after_days?: number | null;
};

export type OcrPageQuality = {
  page_number: number;
  status: "completed" | "failed" | "skipped";
  confidence: number | null;
};

export type OcrQualitySnapshot = {
  status: string;
  mode: string;
  languages: string[];
  effective_languages_string: string;
  pages_processed: number;
  pages_completed: number;
  pages_failed: number;
  duration_ms: number;
  avg_confidence: number | null;
  page_confidences: OcrPageQuality[];
  warnings: string[];
};

export type DocumentProfile =
  | "text_based"
  | "scanned"
  | "mixed"
  | "table_heavy"
  | "figure_heavy"
  | "form_like"
  | "encrypted"
  | "corrupted"
  | "unsupported";

export type ExtractionPageSummary = {
  page_number: number;
  char_count: number;
  text_coverage_ratio: number;
  image_coverage_ratio: number;
  requires_ocr: boolean;
  text_block_count: number;
  table_block_count: number;
  image_block_count: number;
  warnings: string[];
};

export type ExtractionSnapshot = {
  document_profile: DocumentProfile;
  page_count: number;
  total_text_blocks: number;
  total_table_blocks: number;
  total_image_blocks: number;
  extraction_engine: string;
  extraction_confidence: number;
  duration_ms: number;
  is_encrypted: boolean;
  warnings: string[];
  pages: ExtractionPageSummary[];
};

export type AdminLanguageOverrideRequest = {
  language: string | null;
};

export type AdminLanguageOverrideResponse = {
  document_id: string;
  language: string | null;
  language_source: string | null;
  language_confidence: number | null;
  updated_at: string;
};

export type AdminOcrConfigRequest = {
  ocr_languages: string[] | null;
};

export type AdminOcrConfigResponse = {
  document_id: string;
  ocr_languages_override: string | null;
  ocr_quality_snapshot: OcrQualitySnapshot | null;
  updated_at: string;
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
  freshness?:
    | "current"
    | "trusted"
    | "needs_review"
    | "stale"
    | "expired"
    | "archived";
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
  force?: boolean;
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
      freshness: options.freshness,
      file_type: options.file_type,
      sort_by: options.sort_by,
      sort_order: options.sort_order,
      filename_query: options.filename_query || undefined,
    },
  });
}

export async function getDocument(
  documentId: string,
  options: { signal?: AbortSignal } = {},
): Promise<DocumentDetailResponse> {
  return apiRequest<DocumentDetailResponse>(
    `/documents/${encodeURIComponent(documentId)}`,
    {
      signal: options.signal,
    },
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

export async function getCitationPreview(
  documentId: string,
  citationId: string,
  options: { signal?: AbortSignal } = {},
): Promise<CitationPreviewResponse> {
  return apiRequest<CitationPreviewResponse>(
    `/documents/${encodeURIComponent(documentId)}/citations/${encodeURIComponent(citationId)}/preview`,
    {
      signal: options.signal,
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

export async function reindexDocumentGraph(
  documentId: string,
): Promise<ReindexDocumentGraphResponse> {
  return apiRequest<ReindexDocumentGraphResponse>(
    `/documents/${encodeURIComponent(documentId)}/graph/reindex`,
    {
      method: "POST",
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

export async function bulkDeleteDocuments(
  documentIds: string[],
): Promise<BulkDeleteDocumentsResponse> {
  return apiRequest<BulkDeleteDocumentsResponse>("/documents/bulk-delete", {
    method: "POST",
    json: { document_ids: documentIds },
  });
}

export type AdminDeletionListOptions = {
  include_failed?: boolean;
  limit?: number;
  offset?: number;
};

export async function listAdminDocumentDeletion(
  options: AdminDeletionListOptions = {},
): Promise<AdminDocumentDeletionListResponse> {
  return apiRequest<AdminDocumentDeletionListResponse>(
    "/admin/documents/deletion",
    {
      query: {
        include_failed: options.include_failed,
        limit: options.limit,
        offset: options.offset,
      },
    },
  );
}

export async function retryDeleteDocument(
  documentId: string,
): Promise<RetryDeleteDocumentResponse> {
  return apiRequest<RetryDeleteDocumentResponse>(
    `/admin/documents/deletion/${encodeURIComponent(documentId)}/retry`,
    {
      method: "POST",
    },
  );
}

export async function overrideDocumentLanguage(
  documentId: string,
  payload: AdminLanguageOverrideRequest,
): Promise<AdminLanguageOverrideResponse> {
  return apiRequest<AdminLanguageOverrideResponse>(
    `/admin/documents/${encodeURIComponent(documentId)}/language`,
    {
      method: "PATCH",
      json: payload,
    },
  );
}

export async function configureDocumentOcr(
  documentId: string,
  payload: AdminOcrConfigRequest,
): Promise<AdminOcrConfigResponse> {
  return apiRequest<AdminOcrConfigResponse>(
    `/admin/documents/${encodeURIComponent(documentId)}/ocr-config`,
    {
      method: "PATCH",
      json: payload,
    },
  );
}

// ---------------------------------------------------------------------------
// Document versioning (F253)
// ---------------------------------------------------------------------------

export type DocumentVersionResponse = {
  version_id: string;
  document_id: string;
  version_number: number;
  change_reason:
    | "initial_upload"
    | "content_update"
    | "metadata_update"
    | "connector_sync"
    | "reindex"
    | "tombstone";
  content_hash?: string | null;
  extraction_hash?: string | null;
  chunking_profile_snapshot?: Record<string, unknown> | null;
  embedding_model?: string | null;
  embedding_vector_dimension?: number | null;
  index_version?: string | null;
  filename: string;
  page_count?: number | null;
  chunk_count?: number | null;
  status: string;
  indexed_at?: string | null;
  is_current: boolean;
  source_updated_at?: string | null;
  created_by_user_id?: string | null;
  created_at: string;
};

export type DocumentVersionListResponse = {
  document_id: string;
  items: DocumentVersionResponse[];
  total: number;
};

export async function getDocumentVersions(
  documentId: string,
): Promise<DocumentVersionListResponse> {
  return apiRequest<DocumentVersionListResponse>(
    `/documents/${encodeURIComponent(documentId)}/versions`,
  );
}

export const OCR_LANGUAGES: ReadonlyArray<{
  code: string;
  label: string;
  tesseract: string;
}> = [
  { code: "en", label: "English", tesseract: "eng" },
  { code: "de", label: "German", tesseract: "deu" },
  { code: "es", label: "Spanish", tesseract: "spa" },
  { code: "fr", label: "French", tesseract: "fra" },
];
