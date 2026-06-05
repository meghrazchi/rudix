import { z } from "zod";

export const promptTemplateKeySchema = z.enum([
  "answer_generation",
  "summarization",
  "comparison",
  "citation_validation",
  "agent_planning",
]);

export const promptTemplateVersionStateSchema = z.enum([
  "draft",
  "review",
  "published",
]);

export const promptTemplateVariableSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1)
    .max(64)
    .regex(/^[A-Za-z_][A-Za-z0-9_]*$/),
  description: z.string().trim().max(1000).nullable().optional(),
  required: z.boolean().default(true),
  default: z.unknown().nullable().optional(),
});

export const promptTemplateVersionSchema = z.object({
  version_id: z.string().uuid(),
  prompt_template_id: z.string().uuid(),
  template_key: promptTemplateKeySchema,
  version_number: z.number().int().min(1),
  state: promptTemplateVersionStateSchema,
  is_active: z.boolean(),
  content: z.string(),
  variables: z.array(z.record(z.string(), z.unknown())),
  variable_schema: z.record(z.string(), z.unknown()),
  preview_context: z.record(z.string(), z.unknown()),
  change_note: z.string().nullable(),
  source_version_number: z.number().int().min(1).nullable(),
  created_by_id: z.string().uuid().nullable(),
  reviewed_by_id: z.string().uuid().nullable(),
  published_by_id: z.string().uuid().nullable(),
  reviewed_at: z.string().nullable(),
  published_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const promptTemplateSchema = z.object({
  prompt_template_id: z.string().uuid(),
  organization_id: z.string().uuid(),
  template_key: promptTemplateKeySchema,
  name: z.string(),
  description: z.string().nullable(),
  category: z.string(),
  latest_version_number: z.number().int().min(1),
  active_version_number: z.number().int().min(1).nullable(),
  active_version_id: z.string().uuid().nullable(),
  active_state: promptTemplateVersionStateSchema.nullable(),
  active_published_at: z.string().nullable(),
  eval_run_count: z.number().int().nonnegative(),
  created_by_id: z.string().uuid().nullable(),
  updated_by_id: z.string().uuid().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const promptTemplateListSchema = z.object({
  items: z.array(promptTemplateSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
});

export const promptTemplateVersionListSchema = z.object({
  prompt_template_id: z.string().uuid(),
  template_key: promptTemplateKeySchema,
  items: z.array(promptTemplateVersionSchema),
  total: z.number().int().nonnegative(),
});

export const promptTemplateEvalResultSchema = z.object({
  evaluation_run_id: z.string().uuid(),
  evaluation_set_id: z.string().uuid(),
  run_name: z.string().nullable(),
  status: z.string(),
  summary: z.record(z.string(), z.unknown()).nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

export const promptTemplateEvalResultListSchema = z.object({
  prompt_template_id: z.string().uuid(),
  template_key: promptTemplateKeySchema,
  version_number: z.number().int().min(1),
  items: z.array(promptTemplateEvalResultSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
});

export const promptTemplateDetailSchema = z.object({
  template: promptTemplateSchema,
  active_version: promptTemplateVersionSchema.nullable(),
  versions: promptTemplateVersionListSchema,
  eval_results: promptTemplateEvalResultListSchema.nullable(),
});

export const createPromptTemplateDraftSchema = z.object({
  source_version_number: z.number().int().min(1).nullable().optional(),
  change_note: z.string().trim().max(1000).nullable().optional(),
});

export const updatePromptTemplateVersionSchema = z.object({
  content: z.string().min(1).max(64_000).optional(),
  variables: z.array(promptTemplateVariableSchema).max(100).optional(),
  variable_schema: z.record(z.string(), z.unknown()).optional(),
  preview_context: z.record(z.string(), z.unknown()).optional(),
  change_note: z.string().trim().max(1000).nullable().optional(),
});

export const publishPromptTemplateVersionSchema = z.object({
  change_note: z.string().trim().max(1000).nullable().optional(),
});

export const rollbackPromptTemplateSchema = z.object({
  version_number: z.number().int().min(1),
  change_note: z.string().trim().max(1000).nullable().optional(),
});

export const previewPromptTemplateSchema = z.object({
  version_number: z.number().int().min(1).nullable().optional(),
  content: z.string().min(1).max(64_000).nullable().optional(),
  variables: z
    .array(promptTemplateVariableSchema)
    .max(100)
    .nullable()
    .optional(),
  variable_schema: z.record(z.string(), z.unknown()).nullable().optional(),
  context: z.record(z.string(), z.unknown()).default({}),
});

export const promptTemplatePreviewResponseSchema = z.object({
  template_key: promptTemplateKeySchema,
  version_number: z.number().int().min(1).nullable(),
  rendered_prompt: z.string(),
  context: z.record(z.string(), z.unknown()),
});

export type PromptTemplateKey = z.infer<typeof promptTemplateKeySchema>;
export type PromptTemplateVersionState = z.infer<
  typeof promptTemplateVersionStateSchema
>;
export type PromptTemplateVariable = z.infer<
  typeof promptTemplateVariableSchema
>;
export type PromptTemplate = z.infer<typeof promptTemplateSchema>;
export type PromptTemplateVersion = z.infer<typeof promptTemplateVersionSchema>;
export type PromptTemplateList = z.infer<typeof promptTemplateListSchema>;
export type PromptTemplateDetail = z.infer<typeof promptTemplateDetailSchema>;
export type PromptTemplateEvalResultList = z.infer<
  typeof promptTemplateEvalResultListSchema
>;
export type CreatePromptTemplateDraftRequest = z.infer<
  typeof createPromptTemplateDraftSchema
>;
export type UpdatePromptTemplateVersionRequest = z.infer<
  typeof updatePromptTemplateVersionSchema
>;
export type PublishPromptTemplateVersionRequest = z.infer<
  typeof publishPromptTemplateVersionSchema
>;
export type RollbackPromptTemplateRequest = z.infer<
  typeof rollbackPromptTemplateSchema
>;
export type PreviewPromptTemplateRequest = z.input<
  typeof previewPromptTemplateSchema
>;
export type PromptTemplatePreview = z.infer<
  typeof promptTemplatePreviewResponseSchema
>;
