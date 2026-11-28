import type { Overlay, Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type RagCitationStrictness = "strict" | "moderate" | "lenient";
export type RagSafetyMode = "strict" | "standard" | "permissive";
export type RagProfileSource =
  | "collection_override"
  | "org_default"
  | "system_default";

export type RagProfileConfig = Served<Schemas["RagProfileConfig"]>;

export type RagProfileResponse = Overlay<
  Served<Schemas["RagProfileResponse"]>,
  { config: RagProfileConfig }
>;

export type RagProfileListResponse = Overlay<
  Served<Schemas["RagProfileListResponse"]>,
  { items: RagProfileResponse[] }
>;

export type RagProfileVersionResponse = Served<
  Schemas["RagProfileVersionResponse"]
>;

export type RagProfileVersionListResponse = Served<
  Schemas["RagProfileVersionListResponse"]
>;

export type CollectionOverrideResponse = Served<
  Schemas["CollectionOverrideResponse"]
>;

export type CollectionOverrideListResponse = Served<
  Schemas["CollectionOverrideListResponse"]
>;

export type ResolvedRagProfileResponse = Served<
  Schemas["ResolvedRagProfileResponse"]
>;

export type CreateRagProfileRequest = Schemas["CreateRagProfileRequest"];

export type UpdateRagProfileRequest = Schemas["UpdateRagProfileRequest"];

export type RollbackRagProfileRequest = Schemas["RollbackRagProfileRequest"];

export type SetCollectionOverrideRequest =
  Schemas["SetCollectionOverrideRequest"];

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
