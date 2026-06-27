import { apiRequest } from "@/lib/api/request";

export type FeatureFlagName =
  | "agents"
  | "mcp"
  | "connectors"
  | "evaluations"
  | "chunking_profiles"
  | "adaptive_chunking"
  | "graph_rag"
  | "graph_extraction"
  | "graph_explorer"
  | "advanced_pdf_extraction"
  | "language_aware_rag"
  | "pipeline_explorer"
  | "local_llm_profiles"
  | "experimental_profiles"
  | "provider_fallback"
  | "external_mcp_connectors"
  | "query_rewrite_preview"
  | "org_memory";

export const ALL_FLAG_NAMES: FeatureFlagName[] = [
  "agents",
  "mcp",
  "connectors",
  "evaluations",
  "chunking_profiles",
  "adaptive_chunking",
  "graph_rag",
  "graph_extraction",
  "graph_explorer",
  "advanced_pdf_extraction",
  "language_aware_rag",
  "pipeline_explorer",
  "local_llm_profiles",
  "experimental_profiles",
  "provider_fallback",
  "external_mcp_connectors",
  "query_rewrite_preview",
  "org_memory",
];

export const FLAG_LABELS: Record<FeatureFlagName, string> = {
  agents: "Agentic mode",
  mcp: "MCP integration",
  connectors: "Connectors",
  evaluations: "Evaluations",
  chunking_profiles: "Chunking profiles",
  adaptive_chunking: "Adaptive chunking",
  graph_rag: "GraphRAG retrieval",
  graph_extraction: "Graph extraction",
  graph_explorer: "Graph explorer",
  advanced_pdf_extraction: "Advanced PDF extraction",
  language_aware_rag: "Language-aware RAG",
  pipeline_explorer: "Pipeline explorer",
  local_llm_profiles: "Local LLM profiles",
  experimental_profiles: "Experimental model profiles",
  provider_fallback: "Provider fallback",
  external_mcp_connectors: "External MCP connectors",
  query_rewrite_preview: "Query rewrite preview",
  org_memory: "Organization memory",
};

export type FeatureFlagDetail = {
  name: string;
  enabled: boolean;
  env_default: boolean;
  has_org_override: boolean;
  override_enabled: boolean | null;
  override_reason: string | null;
  overridden_by_user_id: string | null;
  overridden_at: string | null;
};

export type FeatureFlagsResponse = {
  organization_id: string;
  flags: FeatureFlagDetail[];
};

export type FeatureFlagSetRequest = {
  enabled: boolean;
  reason?: string | null;
};

export type FeatureFlagSetResponse = {
  organization_id: string;
  flag: FeatureFlagDetail;
};

export type FeatureFlagDeleteResponse = {
  organization_id: string;
  flag_name: string;
  reverted_to_env_default: boolean;
  env_default: boolean;
};

export type PublicFeatureFlagsResponse = {
  flags: Record<string, boolean>;
};

export async function listAdminFeatureFlags(): Promise<FeatureFlagsResponse> {
  return apiRequest<FeatureFlagsResponse>("/admin/feature-flags", {
    method: "GET",
  });
}

export async function setAdminFeatureFlag(
  flagName: string,
  payload: FeatureFlagSetRequest,
): Promise<FeatureFlagSetResponse> {
  return apiRequest<FeatureFlagSetResponse>(
    `/admin/feature-flags/${encodeURIComponent(flagName)}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function clearAdminFeatureFlag(
  flagName: string,
): Promise<FeatureFlagDeleteResponse> {
  return apiRequest<FeatureFlagDeleteResponse>(
    `/admin/feature-flags/${encodeURIComponent(flagName)}`,
    {
      method: "DELETE",
    },
  );
}

export async function getPublicFeatureFlags(): Promise<PublicFeatureFlagsResponse> {
  return apiRequest<PublicFeatureFlagsResponse>("/feature-flags", {
    method: "GET",
  });
}
