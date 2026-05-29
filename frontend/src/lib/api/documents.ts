import { apiRequest } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];

export type DocumentFileType = Schemas["DocumentDetailResponse"]["file_type"];
export type DocumentStatus = Schemas["DocumentStatus"];
export type DocumentSortBy = Schemas["DocumentListResponse"]["sort_by"];
export type SortOrder = Schemas["DocumentListResponse"]["sort_order"];
export type DocumentErrorDetails = Schemas["DocumentErrorDetails"];
export type UploadDocumentResponse = Schemas["UploadDocumentResponse"];
export type DeleteDocumentResponse = Schemas["DeleteDocumentResponse"];
export type ReindexDocumentResponse = Schemas["ReindexDocumentResponse"];
export type DocumentStatusResponse = Schemas["DocumentStatusResponse"];
export type DocumentListItemResponse = Schemas["DocumentListItemResponse"];
export type DocumentListResponse = Schemas["DocumentListResponse"];
export type DocumentDetailResponse = Schemas["DocumentDetailResponse"];
export type DocumentLifecycleTimelineStepResponse =
  Schemas["DocumentLifecycleTimelineStepResponse"];
export type DocumentChunkPreviewResponse =
  Schemas["DocumentChunkPreviewResponse"];
export type DocumentChunksResponse = Schemas["DocumentChunksResponse"];
export type CreateUploadUrlRequest = Schemas["CreateUploadUrlRequest"];
export type CreateUploadUrlResponse = Schemas["CreateUploadUrlResponse"];

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
