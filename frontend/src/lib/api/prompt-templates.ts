import { apiRequest } from "@/lib/api/request";
import {
  createPromptTemplateDraftSchema,
  previewPromptTemplateSchema,
  promptTemplateDetailSchema,
  promptTemplateEvalResultListSchema,
  promptTemplateListSchema,
  promptTemplatePreviewResponseSchema,
  promptTemplateVersionSchema,
  publishPromptTemplateVersionSchema,
  rollbackPromptTemplateSchema,
  updatePromptTemplateVersionSchema,
  type CreatePromptTemplateDraftRequest,
  type PreviewPromptTemplateRequest,
  type PromptTemplateDetail,
  type PromptTemplateEvalResultList,
  type PromptTemplateKey,
  type PromptTemplateList,
  type PromptTemplatePreview,
  type PromptTemplateVersion,
  type PublishPromptTemplateVersionRequest,
  type RollbackPromptTemplateRequest,
  type UpdatePromptTemplateVersionRequest,
} from "@/lib/schemas/prompt-templates";

const BASE_PATH = "/prompt-templates";

export async function listPromptTemplates(
  params: {
    limit?: number;
    offset?: number;
  } = {},
): Promise<PromptTemplateList> {
  const response = await apiRequest<unknown>(BASE_PATH, {
    query: { limit: params.limit, offset: params.offset },
  });
  return promptTemplateListSchema.parse(response);
}

export async function getPromptTemplate(
  templateKey: PromptTemplateKey,
): Promise<PromptTemplateDetail> {
  const response = await apiRequest<unknown>(
    `${BASE_PATH}/${encodeURIComponent(templateKey)}`,
  );
  return promptTemplateDetailSchema.parse(response);
}

export async function createPromptTemplateDraft(
  templateKey: PromptTemplateKey,
  payload: CreatePromptTemplateDraftRequest,
): Promise<PromptTemplateVersion> {
  const request = createPromptTemplateDraftSchema.parse(payload);
  const response = await apiRequest<unknown>(
    `${BASE_PATH}/${encodeURIComponent(templateKey)}/drafts`,
    { method: "POST", json: request },
  );
  return promptTemplateVersionSchema.parse(response);
}

export async function updatePromptTemplateVersion(
  templateKey: PromptTemplateKey,
  versionNumber: number,
  payload: UpdatePromptTemplateVersionRequest,
): Promise<PromptTemplateVersion> {
  const request = updatePromptTemplateVersionSchema.parse(payload);
  const response = await apiRequest<unknown>(
    `${BASE_PATH}/${encodeURIComponent(templateKey)}/versions/${versionNumber}`,
    { method: "PATCH", json: request },
  );
  return promptTemplateVersionSchema.parse(response);
}

export async function submitPromptTemplateVersionForReview(
  templateKey: PromptTemplateKey,
  versionNumber: number,
): Promise<PromptTemplateVersion> {
  const response = await apiRequest<unknown>(
    `${BASE_PATH}/${encodeURIComponent(templateKey)}/versions/${versionNumber}/submit-review`,
    { method: "POST" },
  );
  return promptTemplateVersionSchema.parse(response);
}

export async function publishPromptTemplateVersion(
  templateKey: PromptTemplateKey,
  versionNumber: number,
  payload: PublishPromptTemplateVersionRequest,
): Promise<PromptTemplateVersion> {
  const request = publishPromptTemplateVersionSchema.parse(payload);
  const response = await apiRequest<unknown>(
    `${BASE_PATH}/${encodeURIComponent(templateKey)}/versions/${versionNumber}/publish`,
    { method: "POST", json: request },
  );
  return promptTemplateVersionSchema.parse(response);
}

export async function rollbackPromptTemplate(
  templateKey: PromptTemplateKey,
  payload: RollbackPromptTemplateRequest,
): Promise<PromptTemplateVersion> {
  const request = rollbackPromptTemplateSchema.parse(payload);
  const response = await apiRequest<unknown>(
    `${BASE_PATH}/${encodeURIComponent(templateKey)}/rollback`,
    { method: "POST", json: request },
  );
  return promptTemplateVersionSchema.parse(response);
}

export async function previewPromptTemplate(
  templateKey: PromptTemplateKey,
  payload: PreviewPromptTemplateRequest,
): Promise<PromptTemplatePreview> {
  const request = previewPromptTemplateSchema.parse(payload);
  const response = await apiRequest<unknown>(
    `${BASE_PATH}/${encodeURIComponent(templateKey)}/preview`,
    { method: "POST", json: request },
  );
  return promptTemplatePreviewResponseSchema.parse(response);
}

export async function listPromptTemplateEvalResults(
  templateKey: PromptTemplateKey,
  versionNumber: number,
  params: { limit?: number; offset?: number } = {},
): Promise<PromptTemplateEvalResultList> {
  const response = await apiRequest<unknown>(
    `${BASE_PATH}/${encodeURIComponent(templateKey)}/versions/${versionNumber}/eval-results`,
    { query: { limit: params.limit, offset: params.offset } },
  );
  return promptTemplateEvalResultListSchema.parse(response);
}
