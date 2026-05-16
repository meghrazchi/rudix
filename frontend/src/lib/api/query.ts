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
    session: (sessionId: string) => ["chat", "session", sessionId] as const,
    sessionMessages: (sessionId: string) =>
      ["chat", "session-messages", sessionId] as const,
  },
  evaluations: {
    sets: ["evaluations", "sets"] as const,
    setQuestions: (evaluationSetId: string, params?: Record<string, unknown>) =>
      ["evaluations", "set-questions", evaluationSetId, params ?? {}] as const,
    run: (evaluationRunId: string, params?: Record<string, unknown>) =>
      ["evaluations", "run", evaluationRunId, params ?? {}] as const,
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
    auditLogs: (params?: Record<string, unknown>) =>
      ["admin", "audit-logs", params ?? {}] as const,
  },
  topBar: {
    notifications: (endpoint: string) =>
      ["top-bar", "notifications", endpoint] as const,
  },
};

export type FrontendMutationKind =
  | "document.upload"
  | "document.delete"
  | "document.reindex"
  | "chat.query"
  | "evaluation.run";

export async function invalidateAfterMutation(
  queryClient: QueryClient,
  kind: FrontendMutationKind,
): Promise<void> {
  if (
    kind === "document.upload" ||
    kind === "document.delete" ||
    kind === "document.reindex"
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

  if (kind === "chat.query") {
    await queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions });
    return;
  }

  if (kind === "evaluation.run") {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.evaluations.sets,
    });
    return;
  }
}
