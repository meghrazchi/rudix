import { apiRequest } from "@/lib/api/request";
import type { DocumentListItemResponse } from "@/lib/api/documents";

export type CollectionAccessPolicy =
  | "org_wide"
  | "admin_only"
  | "selected_roles"
  | "selected_members";

export type GranteeType = "role" | "member";

export type RuleField =
  | "file_type"
  | "language"
  | "status"
  | "ingestion_source"
  | "trust_status"
  | "uploaded_by_user_id"
  | "tags";

export type RuleOperator =
  | "eq"
  | "neq"
  | "in"
  | "not_in"
  | "contains"
  | "not_contains";

export type RuleLogic = "and" | "or";

export type RuleCondition = {
  field: RuleField;
  operator: RuleOperator;
  value: string | string[];
};

export type DynamicRuleSet = {
  logic: RuleLogic;
  conditions: RuleCondition[];
};

export type CollectionListItemResponse = {
  collection_id: string;
  name: string;
  description: string | null;
  owner_id: string;
  owner_email: string | null;
  document_count: number;
  indexed_count: number;
  access_policy: CollectionAccessPolicy;
  is_dynamic: boolean;
  last_rule_evaluated_at: string | null;
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
  created_at: string;
  updated_at: string;
};

export type CollectionDetailResponse = CollectionListItemResponse & {
  created_by_email: string | null;
  rule_schema: DynamicRuleSet | null;
};

export type CollectionListResponse = {
  items: CollectionListItemResponse[];
  total: number;
  freshness?: CollectionListItemResponse["review_status"] | null;
};

export type CreateCollectionRequest = {
  name: string;
  description?: string | null;
  access_policy?: CollectionAccessPolicy;
  is_dynamic?: boolean;
  rule_schema?: DynamicRuleSet | null;
};

export type UpdateCollectionRequest = {
  name?: string;
  description?: string | null;
  access_policy?: CollectionAccessPolicy;
  review_status?:
    | "current"
    | "trusted"
    | "needs_review"
    | "stale"
    | "expired"
    | "archived"
    | null;
  review_owner_id?: string | null;
  review_due_date?: string | null;
  expiry_date?: string | null;
  trust_level?: string | null;
};

export type DeleteCollectionResponse = {
  collection_id: string;
  archived: boolean;
};

export type CollectionDocumentsResponse = {
  items: DocumentListItemResponse[];
  total: number;
};

export type AddDocumentToCollectionResponse = {
  collection_id: string;
  document_id: string;
};

export type DocumentCollectionsResponse = {
  items: CollectionListItemResponse[];
};

export type ListCollectionsOptions = {
  limit?: number;
  offset?: number;
  name_query?: string;
  freshness?:
    | "current"
    | "trusted"
    | "needs_review"
    | "stale"
    | "expired"
    | "archived";
};

// ── Access policy types ────────────────────────────────────────────────────────

export type CollectionAccessGrant = {
  grantee_type: GranteeType;
  grantee_value: string; // role name or user_id
};

export type CollectionPolicyResponse = {
  collection_id: string;
  access_policy: CollectionAccessPolicy;
  grants: CollectionAccessGrant[];
};

export type UpdateCollectionPolicyRequest = {
  access_policy: CollectionAccessPolicy;
  grants?: CollectionAccessGrant[];
};

// ── Collection CRUD ────────────────────────────────────────────────────────────

export async function listCollections(
  options: ListCollectionsOptions = {},
): Promise<CollectionListResponse> {
  return apiRequest<CollectionListResponse>("/collections", {
    query: {
      limit: options.limit,
      offset: options.offset,
      name_query: options.name_query || undefined,
      freshness: options.freshness,
    },
  });
}

export async function getCollection(
  collectionId: string,
): Promise<CollectionDetailResponse> {
  return apiRequest<CollectionDetailResponse>(
    `/collections/${encodeURIComponent(collectionId)}`,
  );
}

export async function createCollection(
  payload: CreateCollectionRequest,
): Promise<CollectionDetailResponse> {
  return apiRequest<CollectionDetailResponse>("/collections", {
    method: "POST",
    json: payload,
  });
}

export async function updateCollection(
  collectionId: string,
  payload: UpdateCollectionRequest,
): Promise<CollectionDetailResponse> {
  return apiRequest<CollectionDetailResponse>(
    `/collections/${encodeURIComponent(collectionId)}`,
    {
      method: "PATCH",
      json: payload,
    },
  );
}

export async function deleteCollection(
  collectionId: string,
): Promise<DeleteCollectionResponse> {
  return apiRequest<DeleteCollectionResponse>(
    `/collections/${encodeURIComponent(collectionId)}`,
    { method: "DELETE" },
  );
}

// ── Access policy management ───────────────────────────────────────────────────

export async function getCollectionPolicy(
  collectionId: string,
): Promise<CollectionPolicyResponse> {
  return apiRequest<CollectionPolicyResponse>(
    `/collections/${encodeURIComponent(collectionId)}/access-policy`,
  );
}

export async function updateCollectionPolicy(
  collectionId: string,
  payload: UpdateCollectionPolicyRequest,
): Promise<CollectionPolicyResponse> {
  return apiRequest<CollectionPolicyResponse>(
    `/collections/${encodeURIComponent(collectionId)}/access-policy`,
    {
      method: "PUT",
      json: payload,
    },
  );
}

// ── Collection documents ───────────────────────────────────────────────────────

export async function listCollectionDocuments(
  collectionId: string,
  options: {
    limit?: number;
    offset?: number;
    freshness?:
      | "current"
      | "trusted"
      | "needs_review"
      | "stale"
      | "expired"
      | "archived";
  } = {},
): Promise<CollectionDocumentsResponse> {
  return apiRequest<CollectionDocumentsResponse>(
    `/collections/${encodeURIComponent(collectionId)}/documents`,
    {
      query: {
        limit: options.limit,
        offset: options.offset,
        freshness: options.freshness,
      },
    },
  );
}

export async function addDocumentToCollection(
  collectionId: string,
  documentId: string,
): Promise<AddDocumentToCollectionResponse> {
  return apiRequest<AddDocumentToCollectionResponse>(
    `/collections/${encodeURIComponent(collectionId)}/documents`,
    {
      method: "POST",
      json: { document_id: documentId },
    },
  );
}

export async function removeDocumentFromCollection(
  collectionId: string,
  documentId: string,
): Promise<void> {
  await apiRequest<unknown>(
    `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  );
}

export async function getDocumentCollections(
  documentId: string,
): Promise<DocumentCollectionsResponse> {
  return apiRequest<DocumentCollectionsResponse>(
    `/documents/${encodeURIComponent(documentId)}/collections`,
  );
}

export async function setDocumentCollections(
  documentId: string,
  collectionIds: string[],
): Promise<DocumentCollectionsResponse> {
  return apiRequest<DocumentCollectionsResponse>(
    `/documents/${encodeURIComponent(documentId)}/collections`,
    {
      method: "PUT",
      json: { collection_ids: collectionIds },
    },
  );
}

// ── Dynamic rules ──────────────────────────────────────────────────────────────

export type CollectionRulesResponse = {
  collection_id: string;
  is_dynamic: boolean;
  rule_schema: DynamicRuleSet | null;
  last_rule_evaluated_at: string | null;
  matched_count: number;
};

export type PreviewRulesDocumentItem = {
  document_id: string;
  filename: string;
  file_type: string;
  language: string | null;
  status: string;
  trust_status: string | null;
  tags: string | null;
  ingestion_source: string | null;
};

export type PreviewRulesResponse = {
  total: number;
  items: PreviewRulesDocumentItem[];
};

export type RefreshRulesResponse = {
  collection_id: string;
  matched_count: number;
  last_rule_evaluated_at: string | null;
};

export async function setCollectionRules(
  collectionId: string,
  ruleSchema: DynamicRuleSet,
): Promise<CollectionRulesResponse> {
  return apiRequest<CollectionRulesResponse>(
    `/collections/${encodeURIComponent(collectionId)}/rules`,
    {
      method: "PUT",
      json: { rule_schema: ruleSchema },
    },
  );
}

export async function previewCollectionRules(
  collectionId: string,
  ruleSchema: DynamicRuleSet,
  limit = 20,
): Promise<PreviewRulesResponse> {
  return apiRequest<PreviewRulesResponse>(
    `/collections/${encodeURIComponent(collectionId)}/rules/preview`,
    {
      method: "POST",
      json: { rule_schema: ruleSchema, limit },
    },
  );
}

export async function refreshCollectionRules(
  collectionId: string,
): Promise<RefreshRulesResponse> {
  return apiRequest<RefreshRulesResponse>(
    `/collections/${encodeURIComponent(collectionId)}/rules/refresh`,
    { method: "POST" },
  );
}
