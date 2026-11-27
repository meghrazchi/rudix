import { apiRequest } from "@/lib/api/request";
import type { Overlay, WithOptional } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];

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

// The schema types the value as free-form; the UI only produces a string or a list.
export type RuleCondition = Overlay<
  Schemas["RuleCondition"],
  { value: string | string[] }
>;

export type DynamicRuleSet = Overlay<
  Schemas["DynamicRuleSet"],
  { conditions: RuleCondition[] }
>;

// review_status has a server default; fixtures and older payloads may omit it.
export type CollectionListItemResponse = WithOptional<
  Schemas["CollectionListItemResponse"],
  "review_status"
>;

export type CollectionDetailResponse = Overlay<
  WithOptional<Schemas["CollectionDetailResponse"], "review_status">,
  { rule_schema: DynamicRuleSet | null }
>;

export type CollectionListResponse = Overlay<
  Schemas["CollectionListResponse"],
  { items: CollectionListItemResponse[] }
>;

export type CreateCollectionRequest = Schemas["CreateCollectionRequest"];

export type UpdateCollectionRequest = Schemas["UpdateCollectionRequest"];

export type DeleteCollectionResponse = Schemas["DeleteCollectionResponse"];

export type CollectionDocumentItem = WithOptional<
  Schemas["CollectionDocumentItem"],
  "review_status"
>;

export type CollectionDocumentsResponse = Overlay<
  Schemas["CollectionDocumentsResponse"],
  { items: CollectionDocumentItem[] }
>;

export type AddDocumentToCollectionResponse =
  Schemas["AddDocumentToCollectionResponse"];

export type DocumentCollectionsResponse =
  Schemas["DocumentCollectionsResponse"];

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

export type CollectionAccessGrant = Schemas["CollectionAccessGrantItem"];

export type CollectionPolicyResponse = Schemas["CollectionPolicyResponse"];

export type UpdateCollectionPolicyRequest =
  Schemas["UpdateCollectionPolicyRequest"];

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

export type CollectionRulesResponse = Schemas["CollectionRulesResponse"];

export type PreviewRulesDocumentItem = Schemas["PreviewRulesDocumentItem"];

export type PreviewRulesResponse = Schemas["PreviewRulesResponse"];

export type RefreshRulesResponse = Schemas["RefreshRulesResponse"];

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
