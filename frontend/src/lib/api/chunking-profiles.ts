import { apiRequest } from "@/lib/api/request";
import {
  chunkingProfileCreateRequestSchema,
  chunkingProfileListSchema,
  chunkingProfilePreviewRequestSchema,
  chunkingProfilePreviewResponseSchema,
  chunkingProfileSchema,
  chunkingProfileUpdateRequestSchema,
  chunkingStrategyCatalogSchema,
  type ChunkingProfile,
  type ChunkingProfileCreateRequest,
  type ChunkingProfileList,
  type ChunkingProfilePreviewRequest,
  type ChunkingProfilePreviewResponse,
  type ChunkingProfileUpdateRequest,
  type ChunkingStrategyCatalog,
} from "@/lib/schemas/chunking-profiles";

const CHUNKING_PROFILES_BASE_PATH = "/admin/chunking-profiles";

export async function getChunkingStrategyCatalog(): Promise<ChunkingStrategyCatalog> {
  const payload = await apiRequest<unknown>(
    `${CHUNKING_PROFILES_BASE_PATH}/strategies`,
    {
      method: "GET",
      retry: false,
    },
  );
  return chunkingStrategyCatalogSchema.parse(payload);
}

export async function listChunkingProfiles(): Promise<ChunkingProfileList> {
  const payload = await apiRequest<unknown>(CHUNKING_PROFILES_BASE_PATH, {
    method: "GET",
    retry: false,
  });
  return chunkingProfileListSchema.parse(payload);
}

export async function createChunkingProfile(
  payload: ChunkingProfileCreateRequest,
): Promise<ChunkingProfile> {
  const request = chunkingProfileCreateRequestSchema.parse(payload);
  const response = await apiRequest<unknown>(CHUNKING_PROFILES_BASE_PATH, {
    method: "POST",
    json: request,
    retry: false,
  });
  return chunkingProfileSchema.parse(response);
}

export async function updateChunkingProfile(
  profileId: string,
  payload: ChunkingProfileUpdateRequest,
): Promise<ChunkingProfile> {
  const request = chunkingProfileUpdateRequestSchema.parse(payload);
  const response = await apiRequest<unknown>(
    `${CHUNKING_PROFILES_BASE_PATH}/${encodeURIComponent(profileId)}`,
    {
      method: "PUT",
      json: request,
      retry: false,
    },
  );
  return chunkingProfileSchema.parse(response);
}

export async function setDefaultChunkingProfile(
  profileId: string,
): Promise<ChunkingProfile> {
  const response = await apiRequest<unknown>(
    `${CHUNKING_PROFILES_BASE_PATH}/${encodeURIComponent(profileId)}/set-default`,
    {
      method: "POST",
      retry: false,
    },
  );
  return chunkingProfileSchema.parse(response);
}

export async function previewChunkingProfile(
  payload: ChunkingProfilePreviewRequest,
): Promise<ChunkingProfilePreviewResponse> {
  const request = chunkingProfilePreviewRequestSchema.parse(payload);
  const response = await apiRequest<unknown>(
    `${CHUNKING_PROFILES_BASE_PATH}/preview`,
    {
      method: "POST",
      json: request,
      retry: false,
    },
  );
  return chunkingProfilePreviewResponseSchema.parse(response);
}
