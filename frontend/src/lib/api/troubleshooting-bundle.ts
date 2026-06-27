import { apiRequest } from "@/lib/api/request";

const BASE = "/admin/troubleshooting-bundle";

// ── Types ─────────────────────────────────────────────────────────────────────

export type BundleSourceType =
  | "chat_message"
  | "document"
  | "connector_sync"
  | "evaluation_run"
  | "failed_job";

export type BundleRedactionConfig = {
  redact_prompts: boolean;
  redact_snippets: boolean;
  redact_pii: boolean;
  redact_source_content: boolean;
  include_redacted_logs: boolean;
};

export type TroubleshootingBundleRequest = {
  source_type: BundleSourceType;
  source_id: string;
  include_markdown: boolean;
  redaction: BundleRedactionConfig;
};

export type BundleIdentifiers = {
  bundle_id: string;
  source_type: string;
  source_id: string;
  organization_id: string;
  trace_id: string | null;
  request_id: string | null;
  celery_task_id: string | null;
};

export type BundleLifecycleStage = {
  stage: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  latency_ms: number | null;
  error_code: string | null;
  error_message: string | null;
};

export type BundleWarning = {
  code: string;
  message: string;
  severity: string;
};

export type BundleConfigFingerprint = {
  rag_profile_key: string | null;
  chunking_profile_id: string | null;
  answer_language_mode: string | null;
  collection_ids: string[];
  feature_flags: string[];
};

export type TroubleshootingBundleResponse = {
  schema_version: string;
  bundle_id: string;
  generated_at: string;
  exported_by_user_id: string;
  organization_id: string;
  source_type: string;
  source_id: string;
  redaction_config: BundleRedactionConfig;
  identifiers: BundleIdentifiers;
  lifecycle_stages: BundleLifecycleStage[];
  config_fingerprint: BundleConfigFingerprint | null;
  warnings: BundleWarning[];
  detail: Record<string, unknown> | null;
  logs: Array<Record<string, unknown>>;
  markdown_summary: string | null;
};

// ── API functions ──────────────────────────────────────────────────────────────

export const SOURCE_TYPE_LABELS: Record<BundleSourceType, string> = {
  chat_message: "Chat Message",
  document: "Document",
  connector_sync: "Connector Sync Run",
  evaluation_run: "Evaluation Run",
  failed_job: "Failed Job",
};

export const DEFAULT_REDACTION_CONFIG: BundleRedactionConfig = {
  redact_prompts: true,
  redact_snippets: true,
  redact_pii: true,
  redact_source_content: true,
  include_redacted_logs: true,
};

export async function exportTroubleshootingBundle(
  req: TroubleshootingBundleRequest,
): Promise<Blob> {
  return apiRequest<Blob>(`${BASE}/export`, {
    method: "POST",
    json: req,
    responseType: "blob",
  });
}
