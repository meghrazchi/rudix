import { z } from "zod";

import { apiRequest } from "@/lib/api/request";

// GET /admin/vector-index/status (R06-08): read-only status of the vector index
// generations and the caller's organisation's reindex progress.

export const vectorIndexActiveSchema = z.object({
  generation: z.number().int().nullable(),
  embedding_model: z.string(),
  vector_size: z.number().int(),
  activated_at: z.string().nullable().optional(),
});

export const vectorIndexBuildingSchema = z.object({
  generation: z.number().int(),
  embedding_model: z.string(),
  state: z.enum(["building", "verifying"]),
  started_at: z.string(),
});

export const vectorIndexProgressSchema = z.object({
  documents_total: z.number().int().nonnegative(),
  documents_done: z.number().int().nonnegative(),
});

export const vectorIndexStatusSchema = z.object({
  alias: z.string().nullable(),
  legacy_mode: z.boolean(),
  active: vectorIndexActiveSchema.nullable(),
  building: vectorIndexBuildingSchema.nullable().optional(),
  progress: vectorIndexProgressSchema.nullable().optional(),
});

export type VectorIndexStatus = z.infer<typeof vectorIndexStatusSchema>;
export type VectorIndexProgress = z.infer<typeof vectorIndexProgressSchema>;

export const VECTOR_INDEX_STATUS_PATH = "/admin/vector-index/status";

export async function getVectorIndexStatus(): Promise<VectorIndexStatus> {
  const payload = await apiRequest<unknown>(VECTOR_INDEX_STATUS_PATH, {
    method: "GET",
    retry: false,
  });
  return vectorIndexStatusSchema.parse(payload);
}

/** Share of the organisation's indexed documents the building generation holds (0..1). */
export function progressFraction(
  progress: VectorIndexProgress | null | undefined,
): number {
  if (!progress || progress.documents_total <= 0) {
    return 0;
  }
  return Math.min(1, progress.documents_done / progress.documents_total);
}
