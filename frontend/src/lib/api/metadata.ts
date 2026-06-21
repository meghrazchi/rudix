import { apiRequest } from "@/lib/api/request";

export type MetadataFieldType =
  | "text"
  | "select"
  | "multi_select"
  | "date"
  | "boolean"
  | "number";

export type MetadataFieldResponse = {
  field_id: string;
  organization_id: string;
  name: string;
  display_name: string;
  field_type: MetadataFieldType;
  allowed_values: string[] | null;
  is_required: boolean;
  is_filterable: boolean;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type MetadataFieldListResponse = {
  items: MetadataFieldResponse[];
  total: number;
};

export type CreateMetadataFieldRequest = {
  name: string;
  display_name: string;
  field_type: MetadataFieldType;
  allowed_values?: string[] | null;
  is_required?: boolean;
  is_filterable?: boolean;
  description?: string | null;
  sort_order?: number;
};

export type UpdateMetadataFieldRequest = {
  display_name?: string;
  allowed_values?: string[] | null;
  is_required?: boolean;
  is_filterable?: boolean;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
};

export type DocumentMetadataValueResponse = {
  field_id: string;
  field_name: string;
  display_name: string;
  field_type: MetadataFieldType;
  value: string | string[] | boolean | number | null;
  updated_at: string;
};

export type DocumentMetadataResponse = {
  document_id: string;
  values: DocumentMetadataValueResponse[];
};

export type MetadataValueIn = {
  field_id: string;
  value: string | string[] | boolean | number | null;
};

export type SetDocumentMetadataRequest = {
  values: MetadataValueIn[];
};

export type BulkSetMetadataRequest = {
  document_ids: string[];
  values: MetadataValueIn[];
};

export type BulkSetMetadataResponse = {
  updated: number;
  skipped: number;
  errors: string[];
};

export type TagSuggestionResponse = {
  field_id: string;
  prefix: string;
  suggestions: string[];
};

export type MetadataAuditEntryResponse = {
  audit_id: string;
  document_id: string;
  field_id: string;
  field_name: string;
  changed_by_id: string | null;
  old_value: string | null;
  new_value: string | null;
  action: "set" | "delete" | "bulk_set";
  created_at: string;
};

export type MetadataAuditListResponse = {
  items: MetadataAuditEntryResponse[];
  total: number;
};

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

export type FilterDocumentsResponse = {
  document_ids: string[];
};

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
