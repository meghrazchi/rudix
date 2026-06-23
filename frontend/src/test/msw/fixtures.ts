import type {
  AuditLogListResponse,
  UsageSummaryResponse,
} from "@/lib/api/admin-usage";
import type {
  BillingContact,
  BillingPlanInfo,
  BillingPortalSession,
  BillingQuota,
  BillingUsageSummary,
  Invoice,
} from "@/lib/api/billing";
import type {
  ChatQueryResponse,
  ChatSessionListResponse,
  ChatSessionMessageListResponse,
  ChatSessionResponse,
} from "@/lib/api/chat";
import type {
  DocumentChunksResponse,
  DocumentDetailResponse,
  DocumentListResponse,
  DocumentStatusResponse,
} from "@/lib/api/documents";
import type {
  ChunkingProfileList,
  ChunkingProfilePreviewResponse,
  ChunkingStrategyCatalog,
} from "@/lib/schemas/chunking-profiles";
import type {
  EvaluationQuestionListResponse,
  EvaluationRunDetailResponse,
  EvaluationSetListResponse,
  RunEvaluationResponse,
} from "@/lib/api/evaluations";
import type { HealthResponse } from "@/lib/api/health";
import type {
  OrganizationProfile,
  OrganizationSettings,
  IngestionDefaults,
} from "@/lib/api/organization";
import type {
  TeamMember,
  TeamMemberListResponse,
  InviteTeamMemberResponse,
} from "@/lib/api/team";
import type {
  PipelineNodeDetailResponse,
  PipelineRunGraphResponse,
  PipelineRunResolveResponse,
  PipelineStepListResponse,
} from "@/lib/api/pipeline";
import type {
  AuditEvent,
  LoginPolicy,
  SecurityPosture,
  SecuritySession,
} from "@/lib/api/security";
import type { TopBarNotificationsResponse } from "@/lib/api/notifications";
import type { UserPreferences, UserProfile } from "@/lib/schemas/settings";

export const MSW_FIXTURES_API_BASE_URL = "http://api.test";

export const mockDocumentsList: DocumentListResponse = {
  items: [
    {
      document_id: "doc-1",
      filename: "Employee-Handbook.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 12,
      chunk_count: 42,
      error_message: null,
      error_details: null,
      created_at: "2026-05-19T09:30:00Z",
      updated_at: "2026-05-20T08:30:00Z",
    },
    {
      document_id: "doc-2",
      filename: "Runbook.txt",
      file_type: "txt",
      status: "failed",
      page_count: 3,
      chunk_count: 0,
      error_message: "Chunk embedding failed",
      error_details: null,
      created_at: "2026-05-18T09:30:00Z",
      updated_at: "2026-05-20T07:30:00Z",
    },
  ],
  total: 2,
  limit: 20,
  offset: 0,
  status: null,
  sort_by: "updated_at",
  sort_order: "desc",
};

export const mockDocumentDetail: DocumentDetailResponse = {
  document_id: "doc-1",
  filename: "Employee-Handbook.pdf",
  file_type: "pdf",
  status: "indexed",
  page_count: 12,
  chunk_count: 42,
  checksum: "sha256:fixture",
  error_message: null,
  error_details: null,
  language: "en",
  uploaded_by_user_id: "user-1",
  uploaded_by_user_email: "owner@example.com",
  uploaded_by_user_display_name: "Avery Owner",
  source_provider: "confluence",
  source_provider_label: "Confluence",
  source_title: "Employee Handbook",
  source_key: "page-123",
  source_url: "https://confluence.example.test/wiki/spaces/ENG/pages/123",
  source_link_allowed: true,
  source_last_synced_at: "2026-05-20T08:00:00Z",
  source_sync_version: 5,
  source_visibility: "org_wide",
  source_trust_status: "trusted",
  document_title: "Employee-Handbook.pdf",
  document_type: "pdf",
  document_owner_id: "user-1",
  document_owner_email: "owner@example.com",
  document_owner_display_name: "Avery Owner",
  document_version_label: "v3",
  document_last_updated_at: "2026-05-20T08:30:00Z",
  document_last_indexed_at: "2026-05-20T08:15:00Z",
  review_status: "current",
  trust_status: "current",
  chunking_diagnostics: {
    strategy: "adaptive_hybrid",
    selected_strategy: "page_aware",
    profile_version: "1.0",
    profile_source: "custom_profile",
    chunk_size_tokens: 700,
    chunk_overlap_tokens: 120,
    embedding_model: "text-embedding-3-small",
    index_version: "v1",
    ocr_applied: true,
    hierarchical_mode: false,
    parent_chunk_count: null,
    child_chunk_count: null,
    reason_codes: ["pdf_ocr_applied"],
    adaptive_signals: {
      file_type: "pdf",
      page_count: 12,
      total_token_count: 5200,
      ocr_applied: true,
      heading_density: 0.3,
      avg_chars_per_page: null,
      avg_paragraph_tokens: null,
    },
    token_distribution: {
      min_tokens: 120,
      max_tokens: 260,
      avg_tokens: 188.5,
      total_tokens: 7917,
    },
  },
  created_at: "2026-05-19T09:30:00Z",
  updated_at: "2026-05-20T08:30:00Z",
};

export const mockDocumentStatus: DocumentStatusResponse = {
  document_id: "doc-1",
  status: "indexed",
  error_message: null,
  error_details: null,
  updated_at: "2026-05-20T08:30:00Z",
};

export const mockDocumentChunks: DocumentChunksResponse = {
  document_id: "doc-1",
  items: [
    {
      chunk_id: "chunk-1",
      page_number: 1,
      chunk_index: 0,
      token_count: 180,
      embedding_model: "text-embedding-3-small",
      index_version: "v1",
      section_path: "Handbook > Introduction",
      language: "en",
      chunk_level: 0,
      child_count: 0,
      source_start_offset: 0,
      source_end_offset: 280,
      text_preview: "Rudix processes enterprise documents securely.",
      text: null,
      created_at: "2026-05-20T08:10:00Z",
    },
  ],
  total: 1,
  limit: 8,
  offset: 0,
  include_full_text: false,
};

export const mockChunkingStrategyCatalog: ChunkingStrategyCatalog = {
  strategies: [
    {
      name: "adaptive_hybrid",
      display_name: "Adaptive Hybrid",
      description:
        "Selects a concrete chunking strategy based on structure and OCR signals.",
      suitable_for: ["mixed enterprise content", "production defaults"],
      requires_page_structure: false,
      supports_hierarchical: false,
    },
    {
      name: "page_aware",
      display_name: "Page Aware",
      description: "Preserves page boundaries for citation-heavy documents.",
      suitable_for: ["pdf", "ocr", "evidence packets"],
      requires_page_structure: true,
      supports_hierarchical: false,
    },
  ],
  default_config: {
    strategy: "adaptive_hybrid",
    chunk_size_tokens: 700,
    chunk_overlap_tokens: 120,
    language: null,
    min_tokens: 88,
    strategy_options: {},
  },
  feature_chunking_profiles_enabled: true,
};

export const mockChunkingProfiles: ChunkingProfileList = {
  profiles: [
    {
      profile_id: "9f3d5d4a-6dc0-4bca-8cff-433e1e019611",
      organization_id: "c8ae2f17-c58e-499e-88bf-e6b0a8648c21",
      name: "Operations Default",
      slug: "operations-default",
      config: {
        strategy: "adaptive_hybrid",
        chunk_size_tokens: 700,
        chunk_overlap_tokens: 120,
        language: "en",
        min_tokens: 88,
        strategy_options: {},
      },
      is_default: true,
      is_system: false,
      created_at: "2026-05-20T08:00:00Z",
      updated_at: "2026-05-20T08:00:00Z",
      created_by_user_id: "11111111-1111-4111-8111-111111111111",
      updated_by_user_id: "11111111-1111-4111-8111-111111111111",
    },
  ],
  total: 1,
  has_org_default: true,
};

export const mockChunkingProfilePreview: ChunkingProfilePreviewResponse = {
  strategy_used: "page_aware",
  chunk_count: 6,
  min_tokens: 90,
  max_tokens: 210,
  avg_tokens: 153.5,
  total_tokens: 921,
  reason_codes: ["pdf_ocr_applied"],
  sample_chunks: [
    {
      chunk_index: 0,
      token_count: 180,
      section_path: "Handbook > Introduction",
      chunk_level: 0,
      is_parent: false,
    },
  ],
  warnings: [],
};

export const mockChatSessions: ChatSessionListResponse = {
  items: [
    {
      session_id: "session-1",
      title: "Onboarding FAQ",
      message_count: 4,
      created_at: "2026-05-20T07:00:00Z",
      updated_at: "2026-05-20T08:00:00Z",
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

export const mockChatSession: ChatSessionResponse = mockChatSessions
  .items[0] as ChatSessionResponse;

export const mockChatMessages: ChatSessionMessageListResponse = {
  items: [
    {
      message_id: "user-msg-1",
      role: "user",
      content: "How do we index documents?",
      confidence_score: null,
      confidence_category: null,
      citations: [],
      created_at: "2026-05-20T07:50:00Z",
    },
    {
      message_id: "assistant-msg-1",
      role: "assistant",
      content: "Use /documents/upload and monitor status until indexed.",
      confidence_score: 0.82,
      confidence_category: "high",
      citations: [],
      created_at: "2026-05-20T07:50:10Z",
    },
  ],
  total: 2,
  limit: 50,
  offset: 0,
};

export const mockChatQueryResponse: ChatQueryResponse = {
  chat_session_id: "session-1",
  message_id: "assistant-msg-2",
  answer:
    "Index documents from the Documents page and track status in Dashboard.",
  confidence_score: 0.78,
  confidence_category: "medium",
  confidence_explanation: {
    top_similarity: 0.81,
    average_similarity: 0.71,
    top_rerank_score: 0.73,
    citation_support_score: 0.8,
    citation_validation_score: 0.84,
    citation_coverage_score: 0.82,
    retrieval_agreement_score: 0.76,
    raw_score: 0.78,
    citation_validation_multiplier: 1,
    not_found_penalty_multiplier: 1,
    no_context: false,
    not_found_signal: false,
    weights: {},
    thresholds: {},
  },
  not_found: false,
  citation_validation_failed: false,
  citations: [
    {
      document_id: "doc-1",
      chunk_id: "chunk-1",
      filename: "Employee-Handbook.pdf",
      page_number: 1,
      score: 0.84,
      similarity_score: 0.81,
      rerank_score: 0.74,
      rerank_rank: 1,
      text_snippet: "Rudix processes enterprise documents securely.",
    },
  ],
  debug: {
    latencies_ms: { total: 321 },
    retrieval_count: 4,
    selected_count: 2,
    rerank_applied: true,
    embedding_model: "text-embedding-3-small",
    llm_model: "gpt-5.4-mini",
  },
  created_at: "2026-05-20T08:10:00Z",
};

export const mockEvaluationSets: EvaluationSetListResponse = {
  items: [
    {
      evaluation_set_id: "eval-set-1",
      name: "Support QA",
      description: "Regression quality checks",
      question_count: 12,
      status: "active",
      version: 1,
      scope: {},
      created_at: "2026-05-15T08:00:00Z",
      updated_at: "2026-05-20T08:00:00Z",
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
};

export const mockEvaluationQuestions: EvaluationQuestionListResponse = {
  evaluation_set_id: "eval-set-1",
  items: [
    {
      evaluation_question_id: "eq-1",
      evaluation_set_id: "eval-set-1",
      question: "What is the escalation policy?",
      expected_answer: "Escalate to Tier 2 after failed troubleshooting.",
      expected_document_id: "doc-1",
      expected_page_number: 4,
      tags: ["support", "policy"],
      metadata: {},
      created_at: "2026-05-16T08:00:00Z",
      updated_at: "2026-05-16T08:00:00Z",
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
};

export const mockEvaluationRunQueued: RunEvaluationResponse = {
  evaluation_run_id: "eval-run-1",
  status: "queued",
};

export const mockEvaluationRunDetail: EvaluationRunDetailResponse = {
  evaluation_run_id: "eval-run-1",
  evaluation_set_id: "eval-set-1",
  status: "completed",
  config: {
    top_k: 5,
    rerank: true,
  },
  summary: {
    answer_relevance: 0.74,
    faithfulness: 0.79,
  },
  failure_reason: null,
  failure_type: null,
  started_at: "2026-05-20T08:00:00Z",
  completed_at: "2026-05-20T08:05:00Z",
  created_at: "2026-05-20T08:00:00Z",
  updated_at: "2026-05-20T08:05:00Z",
  results: {
    items: [
      {
        evaluation_result_id: "result-1",
        evaluation_question_id: "eq-1",
        question: "What is the escalation policy?",
        status: "completed",
        generated_answer: "Escalate to Tier 2 after failed troubleshooting.",
        retrieval_score: 0.85,
        faithfulness_score: 0.79,
        citation_accuracy_score: 0.8,
        answer_relevance_score: 0.74,
        latency_ms: 455,
        metrics: {},
        failure_reason: null,
        failure_type: null,
        details: {},
        created_at: "2026-05-20T08:00:30Z",
        updated_at: "2026-05-20T08:00:30Z",
      },
    ],
    total: 1,
    limit: 20,
    offset: 0,
  },
};

export const mockPipelineSteps: PipelineStepListResponse = {
  steps: ["extract", "chunk", "embed", "retrieve", "generate"],
};

export const mockPipelineRunGraph: PipelineRunGraphResponse = {
  pipeline_run_id: "pipe-1",
  pipeline_type: "chat.answer",
  status: "completed",
  nodes: [
    {
      id: "retrieve",
      label: "Retrieve",
      section: "query",
      status: "completed",
      duration_ms: 98,
      metrics: {},
    },
    {
      id: "llm",
      label: "LLM",
      section: "query",
      status: "completed",
      duration_ms: 210,
      metrics: {},
    },
  ],
  edges: [
    {
      id: "edge-1",
      source: "retrieve",
      target: "llm",
    },
  ],
};

export const mockPipelineRunResolve: PipelineRunResolveResponse = {
  pipeline_run_id: "pipe-1",
  pipeline_type: "chat.answer",
  status: "completed",
};

export const mockPipelineNodeDetail: PipelineNodeDetailResponse = {
  node_id: "retrieve",
  title: "Retrieve",
  description: "Fetch top context chunks",
  status: "completed",
  inputs: {},
  outputs: {},
  config: {},
  logs: [],
  error_message: null,
  error_details: {},
  metrics: {},
  started_at: "2026-05-20T08:00:00Z",
  completed_at: "2026-05-20T08:00:01Z",
  duration_ms: 98,
};

export const mockHealth: HealthResponse = {
  status: "ok",
  timestamp: "2026-05-20T08:00:00Z",
  dependencies: {
    postgresql: { ok: true, detail: "Connected", metadata: {} },
    redis: { ok: true, detail: "Connected", metadata: {} },
    rabbitmq: { ok: true, detail: "Connected", metadata: {} },
    minio: { ok: true, detail: "Connected", metadata: {} },
    qdrant: { ok: true, detail: "Connected", metadata: {} },
    openai: { ok: true, detail: "Configured", metadata: {} },
  },
  failed_dependencies: [],
};

export const mockReadinessDegraded: HealthResponse = {
  ...mockHealth,
  status: "degraded",
  dependencies: {
    ...mockHealth.dependencies,
    qdrant: {
      ok: false,
      detail: "Collection unavailable",
      metadata: {},
    },
  },
  failed_dependencies: ["qdrant"],
};

export const mockUsageSummary: UsageSummaryResponse = {
  organization_id: "org-1",
  range: {
    from: "2026-04-21",
    to: "2026-05-20",
  },
  granularity: "day",
  totals: {
    input_tokens: 10_000,
    output_tokens: 3_000,
    cost_usd: 12.34,
    event_count: 77,
    questions_asked: 18,
    avg_confidence: 0.81,
    avg_latency_ms: 482,
  },
  series: [],
};

export const mockAuditLogs: AuditLogListResponse = {
  items: [
    {
      audit_log_id: "audit-1",
      organization_id: "org-1",
      user_id: "user-1",
      action: "documents.reindex.queued",
      resource_type: "document",
      resource_id: "doc-1",
      request_id: "req-1",
      metadata: { status_code: 202 },
      created_at: "2026-05-20T07:30:00Z",
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
  range: {
    from: "2026-04-21",
    to: "2026-05-20",
  },
};

export const mockTopBarNotifications: TopBarNotificationsResponse = {
  items: [
    {
      id: "notif-1",
      title: "Failed job detected",
      message: "A document indexing task failed in your organization.",
      created_at: "2026-05-20T08:20:00Z",
      severity: "error",
      kind: "failed_job",
      href: "/documents",
      allowed_roles: ["owner", "admin"],
    },
  ],
};

// ── Settings fixtures ─────────────────────────────────────────────────────────

export const mockUserProfile: UserProfile = {
  id: "user-1",
  email: "alice@example.com",
  name: "Alice Example",
  avatarUrl: null,
  createdAt: "2026-01-15T10:00:00Z",
};

export const mockUserPreferences: UserPreferences = {
  language: "en",
  timezone: "America/New_York",
  dateFormat: "MM/DD/YYYY",
  theme: "light",
  landingPage: "dashboard",
  keyboardShortcutHints: true,
  emailNotifications: true,
  digestFrequency: "weekly",
};

export const mockSecuritySessions: SecuritySession[] = [
  {
    id: "session-1",
    device: "Chrome on macOS",
    ip_address: "203.0.113.10",
    location: "New York, US",
    created_at: "2026-06-01T08:00:00Z",
    last_active_at: "2026-06-03T09:00:00Z",
    is_current: true,
  },
  {
    id: "session-2",
    device: "Safari on iPhone",
    ip_address: "203.0.113.20",
    location: "Brooklyn, US",
    created_at: "2026-05-28T14:30:00Z",
    last_active_at: "2026-06-02T19:00:00Z",
    is_current: false,
  },
];

export const mockLoginPolicy: LoginPolicy = {
  domain_allowlist: ["example.com"],
  session_timeout_hours: 24,
  sso_required: false,
  invite_only: true,
  mfa_required: false,
};

export const mockSecurityPosture: SecurityPosture = {
  prompt_injection_protection: true,
  citation_validation: true,
  tenant_isolation: true,
  output_validation: false,
  tool_policy_enforced: null,
  last_audit_at: "2026-05-30T00:00:00Z",
};

export const mockSecurityAuditEvents: AuditEvent[] = [
  {
    id: "audit-1",
    event_type: "team.member.invited",
    actor_email: "alice@example.com",
    created_at: "2026-06-02T11:00:00Z",
    summary: "Invited bob@example.com as member",
  },
  {
    id: "audit-2",
    event_type: "document.deleted",
    actor_email: "alice@example.com",
    created_at: "2026-06-01T15:30:00Z",
    summary: "Deleted document 'Runbook.txt'",
  },
];

export const mockOrganizationProfile: OrganizationProfile = {
  id: "org-1",
  name: "Example Corp",
  slug: "example-corp",
  primary_domain: "example.com",
  domain_allowlist: ["example.com"],
  support_email: "support@example.com",
  description: "An example organization for testing.",
  created_at: "2026-01-01T00:00:00Z",
  plan: "Team",
};

export const mockOrganizationSettings: OrganizationSettings = {
  default_member_role: "member",
  invite_only: true,
  allowed_email_domains: ["example.com"],
  default_document_visibility: "private",
  default_collection: null,
  retention_days: 365,
  source_download: "admins",
  evaluation_access: true,
  agentic_access: false,
  mcp_access: false,
  analytics_enabled: true,
};

export const mockIngestionDefaults: IngestionDefaults = {
  allowed_file_types: ["pdf", "docx", "txt", "md"],
  max_upload_size_mb: 25,
  max_page_count: 500,
  duplicate_handling: "skip",
  auto_index: true,
  reindex_policy: "on_update",
  retry_policy: "once",
  default_metadata_tags: [],
};

export const mockBillingPlanInfo: BillingPlanInfo = {
  plan_name: "Team",
  status: "active",
  billing_cycle: "monthly",
  renewal_date: "2026-07-01T00:00:00Z",
  trial_end_date: null,
  seats_used: 4,
  seats_included: 10,
  storage_used_gb: 1.2,
  storage_included_gb: 50,
  monthly_questions_used: 820,
  monthly_questions_included: 5000,
  token_allowance_used: 1200000,
  token_allowance_included: 10000000,
  evaluation_allowance_used: 12,
  evaluation_allowance_included: 100,
  agent_allowance_used: 0,
  agent_allowance_included: 50,
  connector_allowance_used: 0,
  connector_allowance_included: 5,
  can_manage_subscription: true,
  can_cancel_plan: true,
};

export const mockBillingUsageSummary: BillingUsageSummary = {
  range: { from: "2026-05-04T00:00:00Z", to: "2026-06-03T00:00:00Z" },
  documents_uploaded: 18,
  indexed_documents: 15,
  storage_used_gb: 1.2,
  total_chunks: 630,
  questions_asked: 820,
  avg_confidence: 0.82,
  avg_latency_ms: 1340,
  input_tokens: 900000,
  output_tokens: 300000,
  estimated_llm_cost_usd: 1.43,
  evaluation_runs: 12,
  agent_runs: 0,
  connector_sync_jobs: 0,
  failed_indexing_jobs: 3,
};

export const mockBillingQuotas: BillingQuota[] = [
  { resource: "seats", label: "Team seats", used: 4, limit: 10, unit: "seats" },
  {
    resource: "storage",
    label: "Storage",
    used: 1.2,
    limit: 50,
    unit: "GB",
  },
  {
    resource: "questions",
    label: "Monthly questions",
    used: 820,
    limit: 5000,
    unit: "questions",
  },
  {
    resource: "evaluations",
    label: "Evaluation runs",
    used: 12,
    limit: 100,
    unit: "runs",
  },
];

export const mockInvoices: Invoice[] = [
  {
    id: "inv-1",
    date: "2026-06-01T00:00:00Z",
    amount_usd: 49.0,
    status: "paid",
    download_url: null,
  },
  {
    id: "inv-2",
    date: "2026-05-01T00:00:00Z",
    amount_usd: 49.0,
    status: "paid",
    download_url: null,
  },
];

export const mockBillingContact: BillingContact = {
  email: "billing@example.com",
  name: "Example Corp",
  address_line1: "123 Main St",
  address_line2: null,
  city: "New York",
  state: "NY",
  postal_code: "10001",
  country: "US",
  tax_id: null,
  payment_method_summary: "Visa ending 4242",
};

export const mockBillingPortalSession: BillingPortalSession = {
  url: "https://billing.example.com/portal/session-token-abc123",
  expires_at: "2026-06-03T09:05:00Z",
};

// ── Team fixtures ─────────────────────────────────────────────────────────────

export const mockTeamMemberOwner: TeamMember = {
  member_id: "member-1",
  user_id: "user-1",
  name: "Alice Example",
  email: "alice@example.com",
  role: "owner",
  custom_role_id: null,
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
};

export const mockTeamMemberAdmin: TeamMember = {
  member_id: "member-2",
  user_id: "user-2",
  name: "Bob Admin",
  email: "bob@example.com",
  role: "admin",
  custom_role_id: null,
  status: "active",
  created_at: "2026-02-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
};

export const mockTeamMemberInvited: TeamMember = {
  member_id: "member-3",
  user_id: null,
  name: "carol@example.com",
  email: "carol@example.com",
  role: "member",
  custom_role_id: null,
  status: "invited",
  created_at: "2026-06-02T10:00:00Z",
  updated_at: "2026-06-02T10:00:00Z",
};

export const mockTeamMembers: TeamMemberListResponse = {
  items: [mockTeamMemberOwner, mockTeamMemberAdmin, mockTeamMemberInvited],
  total: 3,
  limit: 10,
  offset: 0,
};

export const mockTeamMemberInviteResponse: InviteTeamMemberResponse = {
  member: mockTeamMemberInvited,
  invited: true,
};
