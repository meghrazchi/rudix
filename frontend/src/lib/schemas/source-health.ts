import { z } from "zod";

export const sourceHealthSummarySchema = z.object({
  total_sources: z.number().int(),
  indexed: z.number().int(),
  failed_indexing: z.number().int(),
  pending: z.number().int(),
  ocr_required: z.number().int(),
  ocr_low_confidence: z.number().int(),
  table_extraction_warnings: z.number().int(),
  missing_metadata: z.number().int(),
  stale: z.number().int(),
  deprecated: z.number().int(),
  expired: z.number().int(),
  unreviewed: z.number().int(),
  needs_review: z.number().int(),
  generated_at: z.string(),
});

export const sourceStatusCountSchema = z.object({
  status: z.string(),
  count: z.number().int(),
});

export const indexingFailurePointSchema = z.object({
  date: z.string(),
  failed_count: z.number().int(),
});

export const staleByCollectionSchema = z.object({
  collection_id: z.string().nullable(),
  collection_name: z.string(),
  stale_count: z.number().int(),
});

export const ocrQualityCountSchema = z.object({
  ocr_quality_status: z.string(),
  count: z.number().int(),
});

export const reviewNeedsByOwnerSchema = z.object({
  owner_id: z.string().nullable(),
  owner_name: z.string(),
  needs_review_count: z.number().int(),
});

export const connectorFreshnessSchema = z.object({
  connection_id: z.string(),
  connector_name: z.string(),
  provider_key: z.string().nullable(),
  last_successful_sync_at: z.string().nullable(),
  days_since_last_sync: z.number().int().nullable(),
  status: z.string(),
});

export const sourceHealthChartsSchema = z.object({
  status_distribution: z.array(sourceStatusCountSchema),
  indexing_failures: z.array(indexingFailurePointSchema),
  stale_by_collection: z.array(staleByCollectionSchema),
  ocr_quality_distribution: z.array(ocrQualityCountSchema),
  review_needs_by_owner: z.array(reviewNeedsByOwnerSchema),
  connector_freshness: z.array(connectorFreshnessSchema),
  generated_at: z.string(),
});

export const sourceTypeSchema = z.enum(["file", "connector", "collection"]);
export const freshnessSchema = z.enum(["fresh", "stale", "expired"]);

export const sourceHealthRowSchema = z.object({
  source_type: sourceTypeSchema,
  source_id: z.string(),
  source_name: z.string(),
  connector_name: z.string().nullable().optional(),
  collection_id: z.string().nullable().optional(),
  collection_name: z.string().nullable().optional(),
  owner_id: z.string().nullable().optional(),
  owner_name: z.string().nullable().optional(),
  status: z.string(),
  last_indexed_at: z.string().nullable().optional(),
  last_updated_at: z.string().nullable().optional(),
  freshness: freshnessSchema,
  trust_status: z.string().nullable().optional(),
  ocr_quality: z.string().nullable().optional(),
  review_status: z.string().nullable().optional(),
  graph_indexed: z.string().nullable().optional(),
  missing_metadata: z.boolean(),
  error_message: z.string().nullable().optional(),
  available_actions: z.array(z.string()),
});

export const sourceHealthListSchema = z.object({
  rows: z.array(sourceHealthRowSchema),
  total: z.number().int(),
  page: z.number().int(),
  page_size: z.number().int(),
});

export const tableWarningItemSchema = z.object({
  chunk_id: z.string(),
  page_number: z.number().int().nullable(),
  confidence: z.number().nullable(),
  reason: z.string(),
});

export const sourceHealthErrorDetailSchema = z.object({
  source_type: sourceTypeSchema,
  source_id: z.string(),
  source_name: z.string(),
  status: z.string(),
  error_message: z.string().nullable().optional(),
  extraction_warnings: z.array(z.string()),
  ocr_quality_status: z.string().nullable().optional(),
  ocr_avg_confidence: z.number().nullable().optional(),
  table_warnings: z.array(tableWarningItemSchema),
});

export type SourceHealthSummary = z.infer<typeof sourceHealthSummarySchema>;
export type SourceHealthCharts = z.infer<typeof sourceHealthChartsSchema>;
export type SourceType = z.infer<typeof sourceTypeSchema>;
export type Freshness = z.infer<typeof freshnessSchema>;
export type SourceHealthRow = z.infer<typeof sourceHealthRowSchema>;
export type SourceHealthList = z.infer<typeof sourceHealthListSchema>;
export type TableWarningItem = z.infer<typeof tableWarningItemSchema>;
export type SourceHealthErrorDetail = z.infer<
  typeof sourceHealthErrorDetailSchema
>;

export type SourceHealthQuery = {
  source_type?: SourceType;
  status?: string;
  collection_id?: string;
  owner_id?: string;
  freshness?: Freshness;
  review_status?: string;
  ocr_quality?: string;
  graph_indexed?: "yes" | "no" | "failed";
  missing_metadata?: boolean;
  q?: string;
  page?: number;
  page_size?: number;
};
