import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type MetadataFieldType =
  | "text"
  | "select"
  | "multi_select"
  | "date"
  | "boolean"
  | "number";

export type MetadataFieldResponse = Served<Schemas["MetadataFieldResponse"]>;

export type MetadataFieldListResponse = Served<
  Schemas["MetadataFieldListResponse"]
>;

export type CreateMetadataFieldRequest = Schemas["CreateMetadataFieldRequest"];

export type UpdateMetadataFieldRequest = Schemas["UpdateMetadataFieldRequest"];

export type DocumentMetadataValueResponse = Served<
  Schemas["DocumentMetadataValueResponse"]
>;

export type DocumentMetadataResponse = Served<
  Schemas["DocumentMetadataResponse"]
>;

export type MetadataValueIn = Served<Schemas["MetadataValueIn"]>;

export type SetDocumentMetadataRequest = Schemas["SetDocumentMetadataRequest"];

export type BulkSetMetadataRequest = Schemas["BulkSetMetadataRequest"];

export type BulkSetMetadataResponse = Served<
  Schemas["BulkSetMetadataResponse"]
>;

export type TagSuggestionResponse = Served<Schemas["TagSuggestionResponse"]>;

export type MetadataAuditEntryResponse = Served<
  Schemas["MetadataAuditEntryResponse"]
>;

export type MetadataAuditListResponse = Served<
  Schemas["MetadataAuditListResponse"]
>;

// ── Admin: taxonomy field CRUD ─────────────────────────────────────────────────

export async function listMetadataFields(
  includeInactive = false,
): Promise<MetadataFieldListResponse> {
  return apiRequest<MetadataFieldListResponse>("/admin/metadata/fields", {
    query: { include_inactive: includeInactive },
  });
}

export async function createMetadataField(
  payload: CreateMetadataFieldRequest,
): Promise<MetadataFieldResponse> {
  return apiRequest<MetadataFieldResponse>("/admin/metadata/fields", {
    method: "POST",
    json: payload,
  });
}

export async function getMetadataField(
  fieldId: string,
): Promise<MetadataFieldResponse> {
  return apiRequest<MetadataFieldResponse>(
    `/admin/metadata/fields/${encodeURIComponent(fieldId)}`,
  );
}

export async function updateMetadataField(
  fieldId: string,
  payload: UpdateMetadataFieldRequest,
): Promise<MetadataFieldResponse> {
  return apiRequest<MetadataFieldResponse>(
    `/admin/metadata/fields/${encodeURIComponent(fieldId)}`,
    { method: "PATCH", json: payload },
  );
}

export async function deleteMetadataField(fieldId: string): Promise<void> {
  await apiRequest<unknown>(
    `/admin/metadata/fields/${encodeURIComponent(fieldId)}`,
    { method: "DELETE" },
  );
}

export async function suggestTagValues(
  fieldId: string,
  prefix: string,
): Promise<TagSuggestionResponse> {
  return apiRequest<TagSuggestionResponse>(
    `/admin/metadata/fields/${encodeURIComponent(fieldId)}/suggest`,
    { query: { prefix } },
  );
}

// ── Document metadata ──────────────────────────────────────────────────────────

export async function getDocumentMetadata(
  documentId: string,
): Promise<DocumentMetadataResponse> {
  return apiRequest<DocumentMetadataResponse>(
    `/documents/${encodeURIComponent(documentId)}/metadata`,
  );
}

export async function setDocumentMetadata(
  documentId: string,
  payload: SetDocumentMetadataRequest,
): Promise<DocumentMetadataResponse> {
  return apiRequest<DocumentMetadataResponse>(
    `/documents/${encodeURIComponent(documentId)}/metadata`,
    { method: "PUT", json: payload },
  );
}

export async function bulkSetMetadata(
  payload: BulkSetMetadataRequest,
): Promise<BulkSetMetadataResponse> {
  return apiRequest<BulkSetMetadataResponse>("/admin/metadata/bulk-set", {
    method: "POST",
    json: payload,
  });
}

export type FilterDocumentsResponse = Served<
  Schemas["FilterDocumentsResponse"]
>;

export async function filterDocumentsByMetadata(
  filters: Array<{ fieldId: string; value: string }>,
): Promise<FilterDocumentsResponse> {
  const params = filters.map((f) => `${f.fieldId}:${f.value}`);
  return apiRequest<FilterDocumentsResponse>(
    "/admin/metadata/filter-documents",
    {
      query: { filter: params },
    },
  );
}

export async function getDocumentMetadataAudit(
  documentId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<MetadataAuditListResponse> {
  return apiRequest<MetadataAuditListResponse>(
    `/documents/${encodeURIComponent(documentId)}/metadata/audit`,
    { query: { limit: options.limit, offset: options.offset } },
  );
}
