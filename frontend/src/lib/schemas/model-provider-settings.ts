import { z } from "zod";

const _nonBlankString = (max: number) =>
  z
    .string()
    .trim()
    .min(1, "Value must not be blank")
    .max(max)
    .nullable()
    .optional();

export const updateModelProviderSettingsSchema = z
  .object({
    provider: _nonBlankString(64),
    llm_model: _nonBlankString(255),
    embedding_model: _nonBlankString(255),
    max_tokens: z.coerce
      .number()
      .int()
      .min(1)
      .max(1_000_000)
      .nullable()
      .optional(),
    timeout_seconds: z.coerce
      .number()
      .int()
      .min(1)
      .max(600)
      .nullable()
      .optional(),
    max_retries: z.coerce.number().int().min(0).max(10).nullable().optional(),
    fallback_model: _nonBlankString(255),
    disabled_models: z
      .array(z.string().trim().min(1, "Model name must not be blank").max(255))
      .max(50)
      .optional()
      .nullable()
      .refine(
        (val) => {
          if (!val) return true;
          return new Set(val).size === val.length;
        },
        { message: "disabled_models must not contain duplicates" },
      ),
    change_note: z.string().trim().max(1000).nullable().optional(),
  })
  .refine(
    (data) =>
      Object.keys(data).some(
        (key) =>
          key !== "change_note" && data[key as keyof typeof data] !== undefined,
      ),
    { message: "At least one setting field must be provided" },
  );

export const modelProviderSettingsResponseSchema = z.object({
  organization_id: z.string(),
  provider: z.string().nullable(),
  llm_model: z.string().nullable(),
  embedding_model: z.string().nullable(),
  max_tokens: z.number().int().nullable(),
  timeout_seconds: z.number().int().nullable(),
  max_retries: z.number().int().nullable(),
  fallback_model: z.string().nullable(),
  disabled_models: z.array(z.string()),
  llm_key_configured: z.boolean(),
  version: z.number().int().nonnegative(),
  updated_by_id: z.string().nullable(),
  updated_at: z.string(),
});

export const effectiveModelProviderPolicySchema = z.object({
  organization_id: z.string(),
  provider: z.string(),
  llm_model: z.string(),
  embedding_model: z.string(),
  max_tokens: z.number().int().nullable(),
  timeout_seconds: z.number().int(),
  max_retries: z.number().int(),
  fallback_model: z.string().nullable(),
  disabled_models: z.array(z.string()),
  llm_key_configured: z.boolean(),
  source: z.enum(["org_override", "system_default"]),
  version: z.number().int().nonnegative(),
});

export const modelProviderChangeLogEntrySchema = z.object({
  entry_id: z.string().uuid(),
  organization_id: z.string(),
  version_number: z.number().int().positive(),
  settings_snapshot: z.record(z.string(), z.unknown()),
  change_note: z.string().nullable(),
  changed_by_id: z.string().nullable(),
  created_at: z.string(),
});

export const modelProviderChangeLogResponseSchema = z.object({
  items: z.array(modelProviderChangeLogEntrySchema),
  total: z.number().int().nonnegative(),
});

export type UpdateModelProviderSettingsInput = z.input<
  typeof updateModelProviderSettingsSchema
>;
export type UpdateModelProviderSettings = z.output<
  typeof updateModelProviderSettingsSchema
>;
export type ModelProviderSettingsResponse = z.infer<
  typeof modelProviderSettingsResponseSchema
>;
export type EffectiveModelProviderPolicy = z.infer<
  typeof effectiveModelProviderPolicySchema
>;
export type ModelProviderChangeLogEntry = z.infer<
  typeof modelProviderChangeLogEntrySchema
>;
export type ModelProviderChangeLogResponse = z.infer<
  typeof modelProviderChangeLogResponseSchema
>;
