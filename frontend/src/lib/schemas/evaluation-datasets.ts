import { z } from "zod";

export const createEvaluationSetSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Dataset name is required")
    .max(255, "Dataset name must be 255 characters or fewer"),
  description: z
    .string()
    .trim()
    .max(8000, "Description must be 8000 characters or fewer")
    .optional()
    .or(z.literal("")),
});

export type CreateEvaluationSetFormValues = z.infer<
  typeof createEvaluationSetSchema
>;

export const updateEvaluationSetSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Dataset name is required")
    .max(255, "Dataset name must be 255 characters or fewer")
    .optional(),
  description: z
    .string()
    .trim()
    .max(8000, "Description must be 8000 characters or fewer")
    .optional()
    .or(z.literal("")),
});

export type UpdateEvaluationSetFormValues = z.infer<
  typeof updateEvaluationSetSchema
>;

const difficultyEnum = z.enum(["easy", "medium", "hard"]).optional();

export const createEvaluationQuestionSchema = z.object({
  question: z
    .string()
    .trim()
    .min(1, "Question is required")
    .max(8000, "Question must be 8000 characters or fewer"),
  expected_answer: z
    .string()
    .trim()
    .max(8000, "Expected answer must be 8000 characters or fewer")
    .optional()
    .or(z.literal("")),
  expected_page_number: z
    .number()
    .int()
    .min(1, "Page number must be at least 1")
    .optional()
    .nullable(),
  difficulty: difficultyEnum,
  tags: z.string().max(500, "Tags must be 500 characters or fewer").optional(),
});

export type CreateEvaluationQuestionFormValues = z.infer<
  typeof createEvaluationQuestionSchema
>;

export const updateEvaluationQuestionSchema = z.object({
  question: z
    .string()
    .trim()
    .min(1, "Question is required")
    .max(8000, "Question must be 8000 characters or fewer")
    .optional(),
  expected_answer: z
    .string()
    .trim()
    .max(8000, "Expected answer must be 8000 characters or fewer")
    .optional()
    .or(z.literal("")),
  expected_page_number: z
    .number()
    .int()
    .min(1, "Page number must be at least 1")
    .optional()
    .nullable(),
  difficulty: difficultyEnum,
  tags: z.string().max(500, "Tags must be 500 characters or fewer").optional(),
});

export type UpdateEvaluationQuestionFormValues = z.infer<
  typeof updateEvaluationQuestionSchema
>;

export const importCasesSchema = z.object({
  format: z.enum(["json", "csv"]),
  data: z
    .string()
    .trim()
    .min(1, "Import data is required")
    .max(500_000, "Import data must be 500 KB or fewer"),
  skip_duplicates: z.boolean().default(true),
});

export type ImportCasesFormValues = z.infer<typeof importCasesSchema>;

export function parseTagsString(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((t) => t.trim())
        .filter((t) => t.length > 0),
    ),
  );
}

export function normalizePageNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(parsed) || parsed < 1) return null;
  return parsed;
}
