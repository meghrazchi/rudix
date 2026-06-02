import { z } from "zod";

const optionalTrimmedString = z
  .string()
  .trim()
  .transform((value) => (value.length > 0 ? value : null))
  .nullable()
  .optional();

export const chunkingProfileConfigSchema = z
  .object({
    strategy: z.string().trim().min(1).max(64),
    chunk_size_tokens: z.number().int().min(100).max(4000),
    chunk_overlap_tokens: z.number().int().min(0).max(2000),
    language: optionalTrimmedString,
    min_tokens: z.number().int().min(1).max(500).nullable().optional(),
    strategy_options: z.record(z.string(), z.unknown()).default({}),
  })
  .refine(
    (value) => value.chunk_overlap_tokens < value.chunk_size_tokens,
    "chunk_overlap_tokens must be smaller than chunk_size_tokens",
  );

export const chunkingProfileCreateRequestSchema = z.object({
  name: z.string().trim().min(1).max(100),
  slug: z
    .string()
    .trim()
    .min(2)
    .max(64)
    .regex(/^[a-z0-9][a-z0-9-]*[a-z0-9]$/)
    .nullable()
    .optional(),
  config: chunkingProfileConfigSchema,
  set_as_default: z.boolean().default(false),
});

export const chunkingProfileUpdateRequestSchema = z.object({
  name: z.string().trim().min(1).max(100).nullable().optional(),
  config: chunkingProfileConfigSchema.nullable().optional(),
  set_as_default: z.boolean().nullable().optional(),
});

export const chunkingStrategyInfoSchema = z.object({
  name: z.string(),
  display_name: z.string(),
  description: z.string(),
  suitable_for: z.array(z.string()),
  requires_page_structure: z.boolean(),
  supports_hierarchical: z.boolean(),
});

export const chunkingStrategyCatalogSchema = z.object({
  strategies: z.array(chunkingStrategyInfoSchema),
  default_config: chunkingProfileConfigSchema,
  feature_chunking_profiles_enabled: z.boolean(),
});

export const chunkingProfileSchema = z.object({
  profile_id: z.string().uuid(),
  organization_id: z.string().uuid(),
  name: z.string(),
  slug: z.string(),
  config: chunkingProfileConfigSchema,
  is_default: z.boolean(),
  is_system: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
  created_by_user_id: z.string().uuid().nullable(),
  updated_by_user_id: z.string().uuid().nullable(),
});

export const chunkingProfileListSchema = z.object({
  profiles: z.array(chunkingProfileSchema),
  total: z.number().int().nonnegative(),
  has_org_default: z.boolean(),
});

export const chunkingPreviewChunkMetaSchema = z.object({
  chunk_index: z.number().int().nonnegative(),
  token_count: z.number().int().nonnegative(),
  section_path: z.string().nullable(),
  chunk_level: z.number().int().nonnegative(),
  is_parent: z.boolean(),
});

export const chunkingProfilePreviewRequestSchema = z.object({
  config: chunkingProfileConfigSchema,
  sample_text: z.string().min(1).max(20_000),
  file_type: z.enum(["txt", "md", "pdf", "docx"]).default("txt"),
});

export const chunkingProfilePreviewResponseSchema = z.object({
  strategy_used: z.string(),
  chunk_count: z.number().int().nonnegative(),
  min_tokens: z.number().int().nonnegative(),
  max_tokens: z.number().int().nonnegative(),
  avg_tokens: z.number().nonnegative(),
  total_tokens: z.number().int().nonnegative(),
  reason_codes: z.array(z.string()).default([]),
  sample_chunks: z.array(chunkingPreviewChunkMetaSchema),
  warnings: z.array(z.string()),
});

export type ChunkingProfileConfigInput = z.infer<
  typeof chunkingProfileConfigSchema
>;
export type ChunkingProfileCreateRequest = z.infer<
  typeof chunkingProfileCreateRequestSchema
>;
export type ChunkingProfileUpdateRequest = z.infer<
  typeof chunkingProfileUpdateRequestSchema
>;
export type ChunkingStrategyInfo = z.infer<typeof chunkingStrategyInfoSchema>;
export type ChunkingStrategyCatalog = z.infer<
  typeof chunkingStrategyCatalogSchema
>;
export type ChunkingProfile = z.infer<typeof chunkingProfileSchema>;
export type ChunkingProfileList = z.infer<typeof chunkingProfileListSchema>;
export type ChunkingProfilePreviewRequest = z.infer<
  typeof chunkingProfilePreviewRequestSchema
>;
export type ChunkingProfilePreviewResponse = z.infer<
  typeof chunkingProfilePreviewResponseSchema
>;
