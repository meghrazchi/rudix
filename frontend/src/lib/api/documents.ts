import { apiRequest } from "@/lib/api/request";

export type DocumentFileType = "pdf" | "txt" | "docx";
export type DocumentStatus =
  | "uploaded"
  | "processing"
  | "indexed"
  | "failed"
  | "deleting"
  | "deleted";
export type DocumentSortBy =
  | "created_at"
  | "updated_at"
  | "filename"
  | "status";
export type SortOrder = "asc" | "desc";

export type DocumentErrorDetails = {
  stage: string;
  code: string;
  category: string;
  retryable: boolean;
  message: string;
};

export type UploadDocumentResponse = {
  document_id: string;
  filename: string;
  status: "uploaded";
  queue_status: "queued";
  checksum: string;
  message: string;
};

export type DeleteDocumentResponse = {
  document_id: string;
  status: "deleting" | "deleted";
};

export type ReindexDocumentResponse = {
  document_id: string;
  status: "processing";
  queue_status: "queued";
};

export type DocumentStatusResponse = {
  document_id: string;
  status: DocumentStatus;
  error_message: string | null;
  error_details: DocumentErrorDetails | null;
  updated_at: string | null;
};

export type DocumentListItemResponse = {
  document_id: string;
  filename: string;
  file_type: DocumentFileType;
  status: DocumentStatus;
  page_count: number | null;
  chunk_count: number;
  error_message: string | null;
  error_details: DocumentErrorDetails | null;
  created_at: string;
  updated_at: string;
};

export type DocumentListResponse = {
  items: DocumentListItemResponse[];
  total: number;
  limit: number;
  offset: number;
  status: DocumentStatus | null;
  sort_by: DocumentSortBy;
  sort_order: SortOrder;
};

export type DocumentDetailResponse = {
  document_id: string;
  filename: string;
  file_type: DocumentFileType;
  status: DocumentStatus;
  page_count: number | null;
  chunk_count: number;
  checksum: string | null;
  error_message: string | null;
  error_details: DocumentErrorDetails | null;
  lifecycle_timeline?: DocumentLifecycleTimelineStepResponse[];
  created_at: string;
  updated_at: string;
};

export type DocumentLifecycleTimelineStepResponse = {
  step: string;
  label: string;
  description: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  document_id: string;
  pipeline_run_id: string | null;
  pipeline_type: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  logs: string[];
};

export type DocumentChunkPreviewResponse = {
  chunk_id: string;
  page_number: number | null;
  chunk_index: number;
  token_count: number;
  embedding_model: string;
  index_version: string;
  text_preview: string;
  text: string | null;
  created_at: string;
};

export type DocumentChunksResponse = {
  document_id: string;
  items: DocumentChunkPreviewResponse[];
  total: number;
  limit: number;
  offset: number;
  include_full_text: boolean;
};

export type CreateUploadUrlRequest = {
  filename: string;
  file_type: DocumentFileType;
  file_size_bytes: number;
};

export type CreateUploadUrlResponse = {
  document_id: string;
  upload_url: string;
  object_key: string;
  expires_in_seconds: number;
};

export type ListDocumentsOptions = {
  limit?: number;
  offset?: number;
  status?: DocumentStatus;
  sort_by?: DocumentSortBy;
  sort_order?: SortOrder;
};

export type DocumentChunksOptions = {
  limit?: number;
  offset?: number;
  include_full_text?: boolean;
};

export async function uploadDocument(
  file: File,
  signal?: AbortSignal,
): Promise<UploadDocumentResponse> {
  const formData = new FormData();
  formData.set("file", file);

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
      sort_by: options.sort_by,
      sort_order: options.sort_order,
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
): Promise<ReindexDocumentResponse> {
  return apiRequest<ReindexDocumentResponse>(
    `/documents/${encodeURIComponent(documentId)}/reindex`,
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
