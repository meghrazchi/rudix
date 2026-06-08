import { z } from "zod";

export const ragCitationStrictnessSchema = z.enum([
  "strict",
  "moderate",
  "lenient",
]);
export const ragSafetyModeSchema = z.enum(["strict", "standard", "permissive"]);

export const ragProfileConfigSchema = z.object({
  top_k: z.coerce.number().int().min(1).max(100).default(10),
  rerank_enabled: z.boolean().default(false),
  rerank_model: z.string().trim().max(255).nullable().optional(),
  confidence_threshold: z.coerce.number().min(0).max(1).default(0),
  citation_strictness: ragCitationStrictnessSchema.default("moderate"),
  model_provider: z.string().trim().max(64).nullable().optional(),
  model_name: z.string().trim().max(255).nullable().optional(),
  prompt_template: z.string().max(32_000).nullable().optional(),
  safety_mode: ragSafetyModeSchema.default("standard"),
  chunk_filter: z.record(z.string(), z.unknown()).nullable().optional(),
  max_context_tokens: z.coerce
    .number()
    .int()
    .min(256)
    .max(128_000)
    .nullable()
    .optional(),
});

export const ragProfileCreateRequestSchema = z.object({
  name: z.string().trim().min(1, "Profile name is required.").max(255),
  description: z.string().trim().max(8000).nullable().optional(),
  config: ragProfileConfigSchema.optional(),
  set_as_default: z.boolean().default(false),
  change_note: z.string().trim().max(1000).nullable().optional(),
});

export const ragProfileUpdateRequestSchema = z.object({
  name: z.string().trim().min(1).max(255).nullable().optional(),
  description: z.string().trim().max(8000).nullable().optional(),
  config: ragProfileConfigSchema.nullable().optional(),
  set_as_default: z.boolean().nullable().optional(),
  change_note: z.string().trim().max(1000).nullable().optional(),
});

export const ragProfileResponseSchema = z.object({
  profile_id: z.string().uuid(),
  organization_id: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  config: ragProfileConfigSchema,
  is_default: z.boolean(),
  is_archived: z.boolean(),
  version: z.number().int().nonnegative(),
  created_by_id: z.string().uuid().nullable(),
  updated_by_id: z.string().uuid().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const ragProfileListResponseSchema = z.object({
  items: z.array(ragProfileResponseSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().nonnegative(),
  offset: z.number().int().nonnegative(),
});

export const ragProfileVersionResponseSchema = z.object({
  version_id: z.string().uuid(),
  rag_profile_id: z.string().uuid(),
  version_number: z.number().int().nonnegative(),
  config_snapshot: ragProfileConfigSchema,
  change_note: z.string().nullable(),
  changed_by_id: z.string().uuid().nullable(),
  created_at: z.string(),
});

export const ragProfileVersionListResponseSchema = z.object({
  items: z.array(ragProfileVersionResponseSchema),
  total: z.number().int().nonnegative(),
});

export const rollbackRagProfileRequestSchema = z.object({
  version_number: z.number().int().min(1, "Version number must be at least 1."),
  change_note: z.string().trim().max(1000).nullable().optional(),
});

export type RagProfileConfigInput = z.input<typeof ragProfileConfigSchema>;
export type RagProfileConfig = z.output<typeof ragProfileConfigSchema>;
export type RagProfileCreateRequest = z.infer<
  typeof ragProfileCreateRequestSchema
>;
export type RagProfileUpdateRequest = z.infer<
  typeof ragProfileUpdateRequestSchema
>;
export type RagProfileResponse = z.infer<typeof ragProfileResponseSchema>;
export type RagProfileListResponse = z.infer<
  typeof ragProfileListResponseSchema
>;
export type RagProfileVersionResponse = z.infer<
  typeof ragProfileVersionResponseSchema
>;
export type RagProfileVersionListResponse = z.infer<
  typeof ragProfileVersionListResponseSchema
>;
export type RollbackRagProfileRequest = z.infer<
  typeof rollbackRagProfileRequestSchema
>;
