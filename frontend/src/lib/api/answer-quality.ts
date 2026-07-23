import { apiRequest } from "@/lib/api/request";

export type AnswerQualityLevel =
  | "high"
  | "medium"
  | "low"
  | "warning"
  | "not_found";

export type AnswerQualityReport = {
  metrics: {
    total_questions: number;
    average_confidence: number | null;
    average_citation_support: number | null;
    not_found_count: number;
    missing_citations_count: number;
    stale_source_warning_count: number;
    source_conflict_count: number;
    unsupported_claims_removed: number;
  };
  confidence_distribution: Array<{ level: AnswerQualityLevel; count: number }>;
  trends: Array<{
    date: string;
    answer_count: number;
    average_confidence: number | null;
    average_citation_support: number | null;
    not_found_count: number;
  }>;
  low_confidence_by_collection: Array<{
    collection_id: string | null;
    collection_name: string;
    low_confidence_count: number;
  }>;
  bad_feedback_categories: Array<{ category: string; count: number }>;
  items: AnswerQualityRow[];
  pagination: { page: number; page_size: number; total: number; pages: number };
};

export type AnswerQualityRow = {
  message_id: string;
  question: string;
  user_id: string;
  user_name: string;
  collection_id: string | null;
  collection_name: string | null;
  source_id: string | null;
  source_name: string | null;
  confidence: number | null;
  confidence_level: AnswerQualityLevel;
  citation_support_score: number | null;
  warnings: string[];
  feedback_status: string | null;
  created_at: string;
};

export type AnswerQualityDetail = {
  message_id: string;
  question: string;
  final_answer: string;
  user_id: string;
  user_name: string;
  confidence: number | null;
  confidence_level: AnswerQualityLevel;
  citation_support_score: number | null;
  confidence_reasons: string[];
  warnings: string[];
  sources: Array<{
    document_id: string;
    document_name: string;
    collection_id: string | null;
    collection_name: string | null;
    page_number: number | null;
  }>;
  feedback_id: string | null;
  feedback_category: string | null;
  feedback_comment: string | null;
  feedback_status: string | null;
  related_evaluation_case_id: string | null;
  review_item_id: string | null;
  created_at: string;
};

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
