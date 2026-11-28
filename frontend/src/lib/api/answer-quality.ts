import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type AnswerQualityLevel =
  | "high"
  | "medium"
  | "low"
  | "warning"
  | "not_found";

export type AnswerQualityReport = Served<
  Schemas["AnswerQualityReportResponse"]
>;

export type AnswerQualityRow = Served<Schemas["AnswerQualityRow"]>;

export type AnswerQualityDetail = Served<
  Schemas["AnswerQualityDetailResponse"]
>;

export type AnswerQualityQuery = {
  from?: string;
  to?: string;
  collection_id?: string;
  source_id?: string;
  user_id?: string;
  warning?: string;
  confidence?: string;
  page?: number;
  page_size?: number;
  sort?: "created_at" | "confidence" | "citation_support";
  direction?: "asc" | "desc";
};

export async function getAnswerQualityReport(
  query: AnswerQualityQuery = {},
): Promise<AnswerQualityReport> {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined) params.set(key, String(value));
  });
  const qs = params.toString();
  return apiRequest<AnswerQualityReport>(
    `/reports/answer-quality${qs ? `?${qs}` : ""}`,
  );
}

export async function getAnswerQualityDetail(
  messageId: string,
): Promise<AnswerQualityDetail> {
  return apiRequest<AnswerQualityDetail>(
    `/reports/answer-quality/${encodeURIComponent(messageId)}`,
  );
}
