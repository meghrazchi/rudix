import { apiRequest } from "@/lib/api/request";

export type RagCitationStrictness = "strict" | "moderate" | "lenient";
export type RagSafetyMode = "strict" | "standard" | "permissive";
export type RagProfileSource =
  | "collection_override"
  | "org_default"
  | "system_default";

export type RagProfileConfig = {
  top_k?: number;
  rerank_enabled?: boolean;
  rerank_model?: string | null;
  confidence_threshold?: number;
  citation_strictness?: RagCitationStrictness;
  model_provider?: string | null;
  model_name?: string | null;
  prompt_template?: string | null;
  safety_mode?: RagSafetyMode;
  chunk_filter?: Record<string, unknown> | null;
  max_context_tokens?: number | null;
};

export type RagProfileResponse = {
  profile_id: string;
  organization_id: string;
  name: string;
  description: string | null;
  config: RagProfileConfig;
  is_default: boolean;
  is_archived: boolean;
  version: number;
  created_by_id: string | null;
  updated_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type RagProfileListResponse = {
  items: RagProfileResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type RagProfileVersionResponse = {
  version_id: string;
  rag_profile_id: string;
  version_number: number;
  config_snapshot: RagProfileConfig;
  change_note: string | null;
  changed_by_id: string | null;
  created_at: string;
};

export type RagProfileVersionListResponse = {
  items: RagProfileVersionResponse[];
  total: number;
};

export type CollectionOverrideResponse = {
  override_id: string;
  organization_id: string;
  collection_id: string;
  rag_profile_id: string;
  created_by_id: string | null;
  created_at: string;
};

export type CollectionOverrideListResponse = {
  items: CollectionOverrideResponse[];
  total: number;
};

export type ResolvedRagProfileResponse = {
  profile_id: string;
  name: string;
  version: number;
  config: RagProfileConfig;
  source: RagProfileSource;
};

export type CreateRagProfileRequest = {
  name: string;
  description?: string | null;
  config?: RagProfileConfig;
  set_as_default?: boolean;
  change_note?: string | null;
};

export type UpdateRagProfileRequest = {
  name?: string | null;
  description?: string | null;
  config?: RagProfileConfig | null;
  set_as_default?: boolean | null;
  change_note?: string | null;
};

export type RollbackRagProfileRequest = {
  version_number: number;
  change_note?: string | null;
};

export type SetCollectionOverrideRequest = {
  rag_profile_id: string;
};

// ---------------------------------------------------------------------------
// CRUD
// ---------------------------------------------------------------------------

export async function listRagProfiles(
  params: {
    include_archived?: boolean;
    limit?: number;
    offset?: number;
  } = {},
): Promise<RagProfileListResponse> {
  return apiRequest<RagProfileListResponse>("/rag-profiles", {
    query: {
      include_archived: params.include_archived,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export async function createRagProfile(
  payload: CreateRagProfileRequest,
): Promise<RagProfileResponse> {
  return apiRequest<RagProfileResponse>("/rag-profiles", {
    method: "POST",
    json: payload,
  });
}

export async function getRagProfile(
  profileId: string,
): Promise<RagProfileResponse> {
  return apiRequest<RagProfileResponse>(
    `/rag-profiles/${encodeURIComponent(profileId)}`,
  );
}

export async function updateRagProfile(
  profileId: string,
  payload: UpdateRagProfileRequest,
): Promise<RagProfileResponse> {
  return apiRequest<RagProfileResponse>(
    `/rag-profiles/${encodeURIComponent(profileId)}`,
    { method: "PATCH", json: payload },
  );
}

export async function archiveRagProfile(
  profileId: string,
): Promise<RagProfileResponse> {
  return apiRequest<RagProfileResponse>(
    `/rag-profiles/${encodeURIComponent(profileId)}/archive`,
    { method: "POST" },
  );
}

export async function unarchiveRagProfile(
  profileId: string,
): Promise<RagProfileResponse> {
  return apiRequest<RagProfileResponse>(
    `/rag-profiles/${encodeURIComponent(profileId)}/unarchive`,
    { method: "POST" },
  );
}

export async function setDefaultRagProfile(
  profileId: string,
): Promise<RagProfileResponse> {
  return apiRequest<RagProfileResponse>(
    `/rag-profiles/${encodeURIComponent(profileId)}/set-default`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// Versions
// ---------------------------------------------------------------------------

export async function listRagProfileVersions(
  profileId: string,
): Promise<RagProfileVersionListResponse> {
  return apiRequest<RagProfileVersionListResponse>(
    `/rag-profiles/${encodeURIComponent(profileId)}/versions`,
  );
}

export async function rollbackRagProfile(
  profileId: string,
  payload: RollbackRagProfileRequest,
): Promise<RagProfileResponse> {
  return apiRequest<RagProfileResponse>(
    `/rag-profiles/${encodeURIComponent(profileId)}/rollback`,
    { method: "POST", json: payload },
  );
}

// ---------------------------------------------------------------------------
// Resolve
// ---------------------------------------------------------------------------

export async function resolveRagProfile(
  collectionId?: string,
): Promise<ResolvedRagProfileResponse> {
  return apiRequest<ResolvedRagProfileResponse>("/rag-profiles/resolve", {
    query: { collection_id: collectionId },
  });
}

// ---------------------------------------------------------------------------
// Collection overrides
// ---------------------------------------------------------------------------

export async function listCollectionOverrides(): Promise<CollectionOverrideListResponse> {
  return apiRequest<CollectionOverrideListResponse>(
    "/rag-profiles/overrides/collections",
  );
}

export async function setCollectionOverride(
  collectionId: string,
  payload: SetCollectionOverrideRequest,
): Promise<CollectionOverrideResponse> {
  return apiRequest<CollectionOverrideResponse>(
    `/rag-profiles/overrides/collections/${encodeURIComponent(collectionId)}`,
    { method: "PUT", json: payload },
  );
}

export async function deleteCollectionOverride(
  collectionId: string,
): Promise<void> {
  return apiRequest<void>(
    `/rag-profiles/overrides/collections/${encodeURIComponent(collectionId)}`,
    { method: "DELETE" },
  );
}
