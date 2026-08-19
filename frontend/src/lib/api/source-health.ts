import { apiRequest } from "@/lib/api/request";
import {
  sourceHealthChartsSchema,
  sourceHealthErrorDetailSchema,
  sourceHealthListSchema,
  sourceHealthSummarySchema,
  type SourceHealthCharts,
  type SourceHealthErrorDetail,
  type SourceHealthList,
  type SourceHealthQuery,
  type SourceHealthSummary,
  type SourceType,
} from "@/lib/schemas/source-health";

const SOURCE_HEALTH_BASE_PATH = "/admin/source-health";

function toQueryRecord(query: SourceHealthQuery) {
  return {
    source_type: query.source_type,
    status: query.status,
    collection_id: query.collection_id,
    owner_id: query.owner_id,
    freshness: query.freshness,
    review_status: query.review_status,
    ocr_quality: query.ocr_quality,
    graph_indexed: query.graph_indexed,
    missing_metadata: query.missing_metadata,
    q: query.q,
    page: query.page,
    page_size: query.page_size,
  };
}

export async function getSourceHealthSummary(): Promise<SourceHealthSummary> {
  const payload = await apiRequest<unknown>(
    `${SOURCE_HEALTH_BASE_PATH}/summary`,
    {
      method: "GET",
      retry: false,
    },
  );
  return sourceHealthSummarySchema.parse(payload);
}

export async function getSourceHealthCharts(): Promise<SourceHealthCharts> {
  const payload = await apiRequest<unknown>(
    `${SOURCE_HEALTH_BASE_PATH}/charts`,
    {
      method: "GET",
      retry: false,
    },
  );
  return sourceHealthChartsSchema.parse(payload);
}

export async function listSourceHealth(
  query: SourceHealthQuery = {},
): Promise<SourceHealthList> {
  const payload = await apiRequest<unknown>(
    `${SOURCE_HEALTH_BASE_PATH}/sources`,
    {
      method: "GET",
      query: toQueryRecord(query),
      retry: false,
    },
  );
  return sourceHealthListSchema.parse(payload);
}

export async function getSourceHealthError(
  sourceType: SourceType,
  sourceId: string,
): Promise<SourceHealthErrorDetail> {
  const payload = await apiRequest<unknown>(
    `${SOURCE_HEALTH_BASE_PATH}/sources/${encodeURIComponent(sourceType)}/${encodeURIComponent(sourceId)}/error`,
    {
      method: "GET",
      retry: false,
    },
  );
  return sourceHealthErrorDetailSchema.parse(payload);
}

export async function exportSourceHealth(
  query: SourceHealthQuery = {},
): Promise<Blob> {
  return apiRequest<Blob>(`${SOURCE_HEALTH_BASE_PATH}/export`, {
    method: "GET",
    query: toQueryRecord(query),
    responseType: "blob",
    retry: false,
  });
}
