import { QueryClient } from "@tanstack/react-query";

import { isApiClientError } from "@/lib/api/errors";

function parseIntegerEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return fallback;
  }
  return parsed;
}

function parseRetryCountFromEnv(): number {
  const defaultValue = process.env.NODE_ENV === "production" ? 2 : 1;
  return parseIntegerEnv(
    process.env.NEXT_PUBLIC_QUERY_RETRY_COUNT,
    defaultValue,
  );
}

function parseStaleTimeFromEnv(): number {
  const defaultMs = process.env.NODE_ENV === "production" ? 30_000 : 10_000;
  return parseIntegerEnv(
    process.env.NEXT_PUBLIC_QUERY_STALE_TIME_MS,
    defaultMs,
  );
}

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  const maxRetries = parseRetryCountFromEnv();
  if (failureCount >= maxRetries) {
    return false;
  }

  if (isApiClientError(error)) {
    return error.retryable;
  }

  return true;
}

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: parseStaleTimeFromEnv(),
        retry: (failureCount, error) => shouldRetryQuery(failureCount, error),
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}

let activeAppQueryClient: QueryClient | null = null;

export function registerAppQueryClient(queryClient: QueryClient): () => void {
  activeAppQueryClient = queryClient;

  return () => {
    if (activeAppQueryClient === queryClient) {
      activeAppQueryClient = null;
    }
  };
}

export async function clearAuthSensitiveQueryState(): Promise<void> {
  if (!activeAppQueryClient) {
    return;
  }

  await activeAppQueryClient.cancelQueries();
  activeAppQueryClient.clear();
}

export const queryKeys = {
  collections: {
    all: ["collections"] as const,
    list: (params?: Record<string, unknown>) =>
      ["collections", "list", params ?? {}] as const,
    detail: (collectionId: string) =>
      ["collections", "detail", collectionId] as const,
    documents: (collectionId: string, params?: Record<string, unknown>) =>
      ["collections", "documents", collectionId, params ?? {}] as const,
    policy: (collectionId: string) =>
      ["collections", "policy", collectionId] as const,
  },
  documents: {
    all: ["documents"] as const,
    list: (params?: Record<string, unknown>) =>
      ["documents", "list", params ?? {}] as const,
    detail: (documentId: string) =>
      ["documents", "detail", documentId] as const,
    status: (documentId: string) =>
      ["documents", "status", documentId] as const,
    chunks: (documentId: string, params?: Record<string, unknown>) =>
      ["documents", "chunks", documentId, params ?? {}] as const,
  },
  chat: {
    sessions: ["chat", "sessions"] as const,
    sessionsQuery: (params?: { search?: string }) =>
      ["chat", "sessions", params ?? {}] as const,
    session: (sessionId: string) => ["chat", "session", sessionId] as const,
    sessionMessages: (sessionId: string) =>
      ["chat", "session-messages", sessionId] as const,
  },
  agent: {
    all: ["agent"] as const,
    run: (runId: string) => ["agent", "run", runId] as const,
    runs: (params?: Record<string, unknown>) =>
      ["agent", "runs", params ?? {}] as const,
    approvals: (params?: Record<string, unknown>) =>
      ["agent", "approvals", params ?? {}] as const,
    trace: (runId: string) => ["agent", "trace", runId] as const,
    traceRetention: ["admin", "agent", "trace-retention"] as const,
  },
  evaluations: {
    sets: ["evaluations", "sets"] as const,
    setQuestions: (evaluationSetId: string, params?: Record<string, unknown>) =>
      ["evaluations", "set-questions", evaluationSetId, params ?? {}] as const,
    run: (evaluationRunId: string, params?: Record<string, unknown>) =>
      ["evaluations", "run", evaluationRunId, params ?? {}] as const,
    runs: (params?: Record<string, unknown>) =>
      ["evaluations", "runs", params ?? {}] as const,
    compare: (
      runAId: string,
      runBId: string,
      params?: Record<string, unknown>,
    ) => ["evaluations", "compare", runAId, runBId, params ?? {}] as const,
    setVersions: (evaluationSetId: string) =>
      ["evaluations", "set-versions", evaluationSetId] as const,
    setValidation: (evaluationSetId: string) =>
      ["evaluations", "set-validation", evaluationSetId] as const,
    languageBreakdown: (evaluationRunId: string) =>
      ["evaluations", "language-breakdown", evaluationRunId] as const,
    languageCoverage: (evaluationSetId: string) =>
      ["evaluations", "language-coverage", evaluationSetId] as const,
  },
  graph: {
    all: ["graph"] as const,
    entities: (params?: Record<string, unknown>) =>
      ["graph", "entities", params ?? {}] as const,
    entity: (entityId: string, params?: Record<string, unknown>) =>
      ["graph", "entity", entityId, params ?? {}] as const,
    documentInsights: (documentId: string) =>
      ["graph", "document-insights", documentId] as const,
    stats: ["graph", "stats"] as const,
    relationships: (params?: Record<string, unknown>) =>
      ["graph", "relationships", params ?? {}] as const,
    neighbors: (entityId: string, params?: Record<string, unknown>) =>
      ["graph", "neighbors", entityId, params ?? {}] as const,
  },
  pipeline: {
    all: ["pipeline"] as const,
    steps: ["pipeline", "steps"] as const,
    run: (runId: string) => ["pipeline", "run", runId] as const,
    node: (runId: string, nodeId: string) =>
      ["pipeline", "node", runId, nodeId] as const,
  },
  health: {
    status: ["health", "status"] as const,
    readiness: ["health", "readiness"] as const,
  },
  admin: {
    usage: (params?: Record<string, unknown>) =>
      ["admin", "usage", params ?? {}] as const,
    dashboard: (params?: Record<string, unknown>) =>
      ["admin", "usage-dashboard", params ?? {}] as const,
    auditLogs: (params?: Record<string, unknown>) =>
      ["admin", "audit-logs", params ?? {}] as const,
    observability: (params?: Record<string, unknown>) =>
      ["admin", "observability", params ?? {}] as const,
    providerObservability: (params?: Record<string, unknown>) =>
      ["admin", "provider-observability", params ?? {}] as const,
    governance: ["admin", "governance"] as const,
    agentPolicy: ["admin", "agent-policy"] as const,
    agentPolicyEffective: (runId: string) =>
      ["admin", "agent-policy", "effective", runId] as const,
    failedJobs: (params?: Record<string, unknown>) =>
      ["admin", "failed-jobs", params ?? {}] as const,
    failedJobDetail: (jobId: string) =>
      ["admin", "failed-jobs", jobId] as const,
    chunkingStrategies: ["admin", "chunking-profiles", "strategies"] as const,
    chunkingProfiles: ["admin", "chunking-profiles", "profiles"] as const,
    statusSnapshot: ["admin", "status-snapshot"] as const,
    incidents: (params?: Record<string, unknown>) =>
      ["admin", "incidents", params ?? {}] as const,
    incidentDetail: (incidentId: string) =>
      ["admin", "incidents", incidentId] as const,
    featureFlags: ["admin", "feature-flags"] as const,
    webhooks: ["admin", "webhooks"] as const,
    webhookDeliveries: (webhookId: string) =>
      ["admin", "webhooks", webhookId, "deliveries"] as const,
    mcpPolicy: ["admin", "mcp", "policy"] as const,
    mcpStatus: ["admin", "mcp", "status"] as const,
    mcpTools: ["admin", "mcp", "tools"] as const,
    mcpAuditEvents: (params?: Record<string, unknown>) =>
      ["admin", "mcp", "audit-events", params ?? {}] as const,
  },
  featureFlags: ["feature-flags"] as const,
  statusBanner: ["status", "banner"] as const,
  ragProfiles: {
    all: ["rag-profiles"] as const,
    list: (params?: Record<string, unknown>) =>
      ["rag-profiles", "list", params ?? {}] as const,
    detail: (profileId: string) =>
      ["rag-profiles", "detail", profileId] as const,
    versions: (profileId: string) =>
      ["rag-profiles", "versions", profileId] as const,
    overrides: ["rag-profiles", "overrides"] as const,
    resolve: (collectionId?: string) =>
      ["rag-profiles", "resolve", collectionId ?? ""] as const,
  },
  modelProviderSettings: {
    all: ["model-provider-settings"] as const,
    settings: ["model-provider-settings", "settings"] as const,
    effectivePolicy: ["model-provider-settings", "effective-policy"] as const,
    changeLog: (params?: Record<string, unknown>) =>
      ["model-provider-settings", "change-log", params ?? {}] as const,
  },
  modelProfiles: {
    all: ["model-profiles"] as const,
    list: ["model-profiles", "list"] as const,
    effective: ["model-profiles", "effective"] as const,
    detail: (taskType: string) =>
      ["model-profiles", "detail", taskType] as const,
  },
  modelProviderDiagnostics: {
    all: ["model-provider-diagnostics"] as const,
    providers: ["model-provider-diagnostics", "providers"] as const,
  },
  quotas: {
    all: ["quotas"] as const,
    policy: ["quotas", "policy"] as const,
    usage: ["quotas", "usage"] as const,
    myUsage: ["quotas", "my-usage"] as const,
    overrides: (params?: Record<string, unknown>) =>
      ["quotas", "overrides", params ?? {}] as const,
    changeLog: (params?: Record<string, unknown>) =>
      ["quotas", "change-log", params ?? {}] as const,
  },
  promptTemplates: {
    all: ["prompt-templates"] as const,
    list: (params?: Record<string, unknown>) =>
      ["prompt-templates", "list", params ?? {}] as const,
    detail: (templateKey: string) =>
      ["prompt-templates", "detail", templateKey] as const,
    evalResults: (templateKey: string, versionNumber: number) =>
      ["prompt-templates", "eval-results", templateKey, versionNumber] as const,
  },
  topBar: {
    notifications: (endpoint: string) =>
      ["top-bar", "notifications", endpoint] as const,
  },
  notifications: {
    all: ["notifications"] as const,
    list: (params?: Record<string, unknown>) =>
      ["notifications", "list", params ?? {}] as const,
    unreadCount: ["notifications", "unread-count"] as const,
  },
  feedbackReview: {
    all: ["feedback-review"] as const,
    list: (params?: Record<string, unknown>) =>
      ["feedback-review", "list", params ?? {}] as const,
    detail: (reviewId: string) =>
      ["feedback-review", "detail", reviewId] as const,
  },
  profile: {
    me: ["profile", "me"] as const,
    preferences: ["profile", "preferences"] as const,
  },
  organization: {
    all: ["organization"] as const,
    profile: ["organization", "profile"] as const,
    settings: ["organization", "settings"] as const,
    ingestion: ["organization", "ingestion"] as const,
  },
  team: {
    all: ["team"] as const,
    members: (params?: Record<string, unknown>) =>
      ["team", "members", params ?? {}] as const,
  },
  security: {
    all: ["security"] as const,
    sessions: ["security", "sessions"] as const,
    loginPolicy: ["security", "login-policy"] as const,
    posture: ["security", "posture"] as const,
    auditEvents: (params?: Record<string, unknown>) =>
      ["security", "audit-events", params ?? {}] as const,
  },
  billing: {
    all: ["billing"] as const,
    plan: ["billing", "plan"] as const,
    usage: (range?: string) => ["billing", "usage", range ?? "30d"] as const,
    quotas: ["billing", "quotas"] as const,
    invoices: ["billing", "invoices"] as const,
    contact: ["billing", "contact"] as const,
  },
  connectorConnections: ["connectors", "connections"] as const,
  connectorConnection: (connectionId: string) =>
    ["connectors", "connections", connectionId] as const,
  connectorPermissionReview: (connectionId: string) =>
    ["connectors", "permission-review", connectionId] as const,
  connectorSyncJobs: (connectionId: string) =>
    ["connectors", connectionId, "sync-jobs"] as const,
  connectorSyncRuns: (connectionId: string) =>
    ["connectors", connectionId, "sync-runs"] as const,
  connectorSyncRun: (runId: string) =>
    ["connectors", "sync-runs", runId] as const,
  connectorConflicts: (connectionId: string, status?: string) =>
    ["connectors", connectionId, "conflicts", status ?? "all"] as const,
  connectorProviders: ["connectors", "providers"] as const,
  connectorProvider: (key: string) => ["connectors", "providers", key] as const,
  connectorDiscovery: (
    connectionId: string,
    providerKey: string,
    scope: string,
    params?: Record<string, unknown>,
  ) =>
    [
      "connectors",
      "discovery",
      connectionId,
      providerKey,
      scope,
      params ?? {},
    ] as const,
};

export type FrontendMutationKind =
  | "document.upload"
  | "document.delete"
  | "document.reindex"
  | "document.graph.reindex"
  | "collection.create"
  | "collection.update"
  | "collection.delete"
  | "collection.document.add"
  | "collection.document.remove"
  | "collection.policy.update"
  | "chat.query"
  | "chat.session.rename"
  | "chat.session.delete"
  | "agent.run"
  | "agent.run.cancel"
  | "evaluation.run"
  | "evaluation.set.update"
  | "evaluation.set.delete"
  | "evaluation.set.publish"
  | "evaluation.set.duplicate"
  | "evaluation.set.import"
  | "evaluation.question.update"
  | "evaluation.question.delete"
  | "notification.read"
  | "notification.unread"
  | "notification.mark-all-read"
  | "profile.update"
  | "profile.preferences.update"
  | "organization.profile.update"
  | "organization.settings.update"
  | "organization.ingestion.update"
  | "team.invite"
  | "team.role.update"
  | "team.remove"
  | "security.session.revoke"
  | "security.session.revoke-all"
  | "security.login-policy.update"
  | "billing.contact.update"
  | "rag-profile.create"
  | "rag-profile.update"
  | "rag-profile.archive"
  | "rag-profile.unarchive"
  | "rag-profile.set-default"
  | "rag-profile.rollback"
  | "rag-profile.override.set"
  | "rag-profile.override.delete"
  | "model-provider-settings.update"
  | "model-provider-settings.reset"
  | "quota-policy.update"
  | "quota-policy.reset"
  | "quota-override.create"
  | "quota-override.delete"
  | "webhook.create"
  | "webhook.update"
  | "webhook.delete"
  | "webhook.rotate-secret"
  | "webhook.test"
  | "mcp.policy.update";

export async function invalidateAfterMutation(
  queryClient: QueryClient,
  kind: FrontendMutationKind,
): Promise<void> {
  if (
    kind === "collection.create" ||
    kind === "collection.update" ||
    kind === "collection.delete"
  ) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.collections.all,
    });
    return;
  }

  if (kind === "collection.policy.update") {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.collections.all,
    });
    return;
  }

  if (
    kind === "collection.document.add" ||
    kind === "collection.document.remove"
  ) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.collections.all,
    });
    await queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
    return;
  }

  if (
    kind === "document.upload" ||
    kind === "document.delete" ||
    kind === "document.reindex" ||
    kind === "document.graph.reindex"
  ) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
    await queryClient.invalidateQueries({ queryKey: queryKeys.pipeline.all });
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey) && query.queryKey[0] === "dashboard",
    });
    await queryClient.invalidateQueries({ queryKey: queryKeys.admin.usage() });
    return;
  }

  if (
    kind === "chat.query" ||
    kind === "agent.run" ||
    kind === "chat.session.rename" ||
    kind === "chat.session.delete"
  ) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions });
    return;
  }

  if (kind === "agent.run.cancel") {
    await queryClient.invalidateQueries({ queryKey: queryKeys.agent.all });
    return;
  }

  if (kind === "evaluation.run") {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.evaluations.sets,
    });
    return;
  }

  if (
    kind === "evaluation.set.update" ||
    kind === "evaluation.set.delete" ||
    kind === "evaluation.set.publish" ||
    kind === "evaluation.set.duplicate" ||
    kind === "evaluation.set.import" ||
    kind === "evaluation.question.update" ||
    kind === "evaluation.question.delete"
  ) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.evaluations.sets,
    });
    return;
  }

  if (
    kind === "notification.read" ||
    kind === "notification.unread" ||
    kind === "notification.mark-all-read"
  ) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.notifications.all,
    });
    return;
  }

  if (kind === "profile.update") {
    await queryClient.invalidateQueries({ queryKey: queryKeys.profile.me });
    return;
  }

  if (kind === "profile.preferences.update") {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.profile.preferences,
    });
    return;
  }

  if (
    kind === "organization.profile.update" ||
    kind === "organization.settings.update" ||
    kind === "organization.ingestion.update"
  ) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.organization.all,
    });
    return;
  }

  if (
    kind === "team.invite" ||
    kind === "team.role.update" ||
    kind === "team.remove"
  ) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.team.all });
    return;
  }

  if (
    kind === "security.session.revoke" ||
    kind === "security.session.revoke-all"
  ) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.security.sessions,
    });
    return;
  }

  if (kind === "security.login-policy.update") {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.security.loginPolicy,
    });
    return;
  }

  if (kind === "billing.contact.update") {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.billing.contact,
    });
    return;
  }

  if (
    kind === "rag-profile.create" ||
    kind === "rag-profile.update" ||
    kind === "rag-profile.archive" ||
    kind === "rag-profile.unarchive" ||
    kind === "rag-profile.set-default" ||
    kind === "rag-profile.rollback"
  ) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.ragProfiles.all,
    });
    return;
  }

  if (
    kind === "model-provider-settings.update" ||
    kind === "model-provider-settings.reset"
  ) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.modelProviderSettings.all,
    });
    return;
  }

  if (kind === "quota-policy.update" || kind === "quota-policy.reset") {
    await queryClient.invalidateQueries({ queryKey: queryKeys.quotas.all });
    return;
  }

  if (kind === "quota-override.create" || kind === "quota-override.delete") {
    await queryClient.invalidateQueries({ queryKey: queryKeys.quotas.all });
    return;
  }

  if (
    kind === "webhook.create" ||
    kind === "webhook.update" ||
    kind === "webhook.delete" ||
    kind === "webhook.rotate-secret" ||
    kind === "webhook.test"
  ) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.admin.webhooks });
    return;
  }

  if (kind === "mcp.policy.update") {
    await queryClient.invalidateQueries({ queryKey: queryKeys.admin.mcpPolicy });
    return;
  }

  if (
    kind === "rag-profile.override.set" ||
    kind === "rag-profile.override.delete"
  ) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.ragProfiles.overrides,
    });
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey) &&
        query.queryKey[0] === "rag-profiles" &&
        query.queryKey[1] === "resolve",
    });
    return;
  }
}
