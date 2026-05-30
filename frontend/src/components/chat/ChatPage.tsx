"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  createAgentRun,
  decideAgentRunApproval,
  getAgentRun,
  type AgentRunCreateRequest,
  type AgentRunCreateResponse,
  type AgentApprovalDecisionRequest,
  type AgentRunDetailResponse,
  type AgentRuntimeMode,
} from "@/lib/api/agent";
import {
  createChatSession,
  listChatSessionMessages,
  listChatSessions,
  queryChat,
  type ChatCitationResponse,
  type ChatDebugResponse,
  type ChatSessionMessageResponse,
  type ChatQueryRequest,
  type ChatQueryResponse,
} from "@/lib/api/chat";
import {
  listDocuments,
  type DocumentListItemResponse,
} from "@/lib/api/documents";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import {
  buildPipelineExplorerHref,
  normalizePipelineRunType,
  type PipelineRunType,
} from "@/lib/pipeline-links";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { loadSettingsPreferences } from "@/lib/settings-preferences";
import { useAuthSession } from "@/lib/use-auth-session";

const DRAFT_SESSION_KEY = "__draft__";

function parsePositiveIntegerEnv(
  value: string | undefined,
  fallback: number,
): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

const MAX_INDEXED_DOCS = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_MAX_INDEXED_DOCS,
  200,
);
const SESSION_LIST_LIMIT = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_SESSION_LIST_LIMIT,
  10,
);
const CONTEXT_MODAL_PAGE_SIZE = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_CONTEXT_MODAL_PAGE_SIZE,
  8,
);
const SESSION_TITLE_MAX_LENGTH = 120;
const MIN_TOP_K = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_TOP_K_MIN,
  1,
);
const MAX_TOP_K = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_TOP_K_MAX,
  20,
);
const DEFAULT_TOP_K = Math.min(
  Math.max(
    parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_DEFAULT, 5),
    MIN_TOP_K,
  ),
  MAX_TOP_K,
);
const AGENT_RUN_POLL_INTERVAL_MS = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_AGENT_RUN_POLL_INTERVAL_MS,
  3_000,
);
const AGENTIC_CHAT_ENABLED =
  process.env.NEXT_PUBLIC_CHAT_AGENTIC_ENABLED !== "false";
const DEFAULT_AGENTIC_MODE =
  process.env.NEXT_PUBLIC_CHAT_AGENTIC_DEFAULT === "true";
const CHAT_SETTINGS_STORAGE_KEY = "rudix.chat.settings.v1";
const CHAT_FEEDBACK_ENABLED = getFrontendRuntimeConfig().features.feedback;
const STREAMING_PLACEHOLDER_ENABLED =
  process.env.NEXT_PUBLIC_CHAT_STREAMING_ENABLED === "true";

type PersistedChatSettings = {
  topK: number;
  rerank: boolean;
  selectedDocumentIds: string[];
  agenticMode?: boolean;
};

type ChatTurn = {
  question: string;
  response: {
    message_id: string;
    answer: string;
    confidence_score: number;
    confidence_category: "low" | "medium" | "high";
    not_found: boolean;
    debug: ChatDebugResponse | null;
    citations: ChatCitationResponse[];
    created_at: string;
    agent_run_id: string | null;
    agent_run_status: string | null;
    agent_run_error: AgentRunCreateResponse["run"]["error"] | null;
    agent_mode: AgentRuntimeMode | null;
  };
};

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "N/A";
  }
  return value.toFixed(3);
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "N/A";
  }
  return `${(value * 100).toFixed(1)}%`;
}


function confidenceBadgeClass(
  _confidence: ChatQueryResponse["confidence_category"],
): string {
  return "inline-flex items-center gap-1 rounded-full bg-[#e4e1ee] px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
}

function agentRunStatusClass(status: string): string {
  if (status === "completed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "failed" || status === "cancelled") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
}


function isTerminalAgentRunStatus(status: string): boolean {
  return (
    status === "completed" || status === "failed" || status === "cancelled"
  );
}

function toObject(value: unknown): Record<string, unknown> {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function toStringOrNull(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function toNumberOrNull(value: unknown): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return value;
}

function toSessionDisplayTitle(
  sessionTitle: string | null | undefined,
  thread: ChatTurn[],
): string {
  const normalizedTitle = toStringOrNull(sessionTitle);
  if (normalizedTitle) {
    return normalizedTitle;
  }
  const firstQuestion = toStringOrNull(thread[0]?.question);
  if (firstQuestion) {
    return firstQuestion;
  }
  return "Untitled session";
}

function toConfidenceCategory(
  value: unknown,
  score: number,
): "low" | "medium" | "high" {
  if (value === "low" || value === "medium" || value === "high") {
    return value;
  }
  if (score >= 0.8) {
    return "high";
  }
  if (score >= 0.5) {
    return "medium";
  }
  return "low";
}

function normalizeAgentCitation(
  citation: Record<string, unknown>,
): ChatCitationResponse {
  return {
    document_id: toStringOrNull(citation.document_id) ?? "",
    chunk_id: toStringOrNull(citation.chunk_id) ?? "",
    filename: toStringOrNull(citation.filename),
    page_number: toNumberOrNull(citation.page_number),
    score: toNumberOrNull(citation.score),
    similarity_score: toNumberOrNull(citation.similarity_score),
    rerank_score: toNumberOrNull(citation.rerank_score),
    rerank_rank: toNumberOrNull(citation.rerank_rank),
    text_snippet:
      toStringOrNull(citation.text_snippet) ?? toStringOrNull(citation.snippet),
  };
}

function readDebugString(
  debug: ChatDebugResponse | null,
  key: string,
): string | null {
  if (!debug) {
    return null;
  }
  const value = (debug as Record<string, unknown>)[key];
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : null;
}

function getChatRunType(debug: ChatDebugResponse | null): PipelineRunType {
  const debugRunType = normalizePipelineRunType(
    readDebugString(debug, "pipeline_type") ??
      readDebugString(debug, "run_type"),
  );
  return debugRunType ?? "chat.answer";
}

function buildChatPipelineHref(response: ChatTurn["response"]): string | null {
  const chatMessageId = response.message_id.trim();
  const runId =
    readDebugString(response.debug, "pipeline_run_id") ??
    readDebugString(response.debug, "run_id");
  const runType = getChatRunType(response.debug);
  const firstCitationDocumentId =
    response.citations.find((citation) => Boolean(citation.document_id))
      ?.document_id ?? null;

  if (!chatMessageId && !runId && !firstCitationDocumentId) {
    return null;
  }

  return buildPipelineExplorerHref({
    runId,
    runType,
    chatMessageId: chatMessageId || null,
    documentId: firstCitationDocumentId,
  });
}

function isAdminLikeRole(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

function activeThreadKey(sessionId: string | null): string {
  return sessionId ?? DRAFT_SESSION_KEY;
}

function toTurnResponseFromQuery(
  response: ChatQueryResponse,
): ChatTurn["response"] {
  return {
    message_id: response.message_id,
    answer: response.answer,
    confidence_score: response.confidence_score,
    confidence_category: response.confidence_category,
    not_found: response.not_found,
    debug: response.debug ?? null,
    citations: response.citations ?? [],
    created_at: response.created_at,
    agent_run_id: null,
    agent_run_status: null,
    agent_run_error: null,
    agent_mode: null,
  };
}

function toTurnResponseFromHistoryMessage(
  message: ChatSessionMessageResponse,
): ChatTurn["response"] {
  return {
    message_id: message.message_id,
    answer: message.content,
    confidence_score:
      typeof message.confidence_score === "number"
        ? message.confidence_score
        : 0,
    confidence_category: message.confidence_category ?? "low",
    not_found: false,
    debug: null,
    citations: message.citations ?? [],
    created_at: message.created_at,
    agent_run_id: null,
    agent_run_status: null,
    agent_run_error: null,
    agent_mode: null,
  };
}

function toTurnResponseFromAgentRun(
  run: AgentRunCreateResponse["run"],
): ChatTurn["response"] {
  const outcome = run.outcome ?? null;
  const confidence = toObject(outcome?.confidence ?? {});
  const score = toNumberOrNull(confidence.score) ?? 0;
  const answer =
    toStringOrNull(outcome?.answer) ??
    toStringOrNull(run.error?.message) ??
    "No answer was generated.";

  const citations = Array.isArray(outcome?.citations)
    ? outcome.citations.map((citation) =>
        normalizeAgentCitation(toObject(citation)),
      )
    : [];

  return {
    message_id: run.run_id,
    answer,
    confidence_score: score,
    confidence_category: toConfidenceCategory(confidence.category, score),
    not_found: Boolean(outcome?.not_found),
    debug: null,
    citations,
    created_at: new Date().toISOString(),
    agent_run_id: run.run_id,
    agent_run_status: run.status,
    agent_run_error: run.error ?? null,
    agent_mode: outcome?.mode ?? null,
  };
}

function buildTurnsFromSessionMessages(
  messages: ChatSessionMessageResponse[],
): ChatTurn[] {
  const turns: ChatTurn[] = [];
  let lastUserQuestion: string | null = null;

  for (const message of messages) {
    if (message.role === "user") {
      lastUserQuestion = message.content;
      continue;
    }
    if (message.role !== "assistant") {
      continue;
    }

    turns.push({
      question: lastUserQuestion ?? "Question unavailable.",
      response: toTurnResponseFromHistoryMessage(message),
    });
    lastUserQuestion = null;
  }

  return turns;
}

function replaceSessionParamInUrl(sessionId: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  const nextUrl = new URL(window.location.href);
  if (sessionId) {
    nextUrl.searchParams.set("session_id", sessionId);
  } else {
    nextUrl.searchParams.delete("session_id");
  }
  window.history.replaceState(
    window.history.state,
    "",
    `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`,
  );
}

function readPersistedChatSettings(): PersistedChatSettings | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(CHAT_SETTINGS_STORAGE_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as Partial<PersistedChatSettings> | null;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }

    const storedTopK =
      typeof parsed.topK === "number" && Number.isFinite(parsed.topK)
        ? Math.min(MAX_TOP_K, Math.max(MIN_TOP_K, Math.trunc(parsed.topK)))
        : DEFAULT_TOP_K;

    const selectedDocumentIds = Array.isArray(parsed.selectedDocumentIds)
      ? parsed.selectedDocumentIds.filter(
          (value): value is string => typeof value === "string",
        )
      : [];

    return {
      topK: storedTopK,
      rerank: parsed.rerank !== false,
      selectedDocumentIds,
      agenticMode: parsed.agenticMode === true,
    };
  } catch {
    return null;
  }
}

function getFileIcon(filename: string | null | undefined): string {
  if (!filename) return "insert_drive_file";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "article";
  if (["md", "txt", "doc", "docx"].includes(ext)) return "description";
  if (["xlsx", "xls", "csv"].includes(ext)) return "table_chart";
  return "insert_drive_file";
}

function getFileTypeLabel(filename: string | null | undefined): string {
  if (!filename) return "FILE";
  return filename.split(".").pop()?.toUpperCase() ?? "FILE";
}

function getFileTypeColorClass(filename: string | null | undefined): string {
  if (!filename) return "text-[#464555]";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "text-[#3525cd]";
  if (["md", "txt", "doc", "docx"].includes(ext)) return "text-emerald-600";
  if (["xlsx", "xls", "csv"].includes(ext)) return "text-amber-600";
  return "text-[#464555]";
}


export function ChatPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { state } = useAuthSession();
  const lastAppliedSessionIdRef = useRef<string | null>(null);
  const contextModalRef = useRef<HTMLDivElement | null>(null);
  const persistedSettings = useMemo(() => readPersistedChatSettings(), []);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [contextSearchQuery, setContextSearchQuery] = useState("");
  const [contextPage, setContextPage] = useState(1);
  const [isContextModalOpen, setIsContextModalOpen] = useState(false);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>(
    () => persistedSettings?.selectedDocumentIds ?? [],
  );
  const [topK, setTopK] = useState(
    () => persistedSettings?.topK ?? DEFAULT_TOP_K,
  );
  const [rerank, setRerank] = useState(() => persistedSettings?.rerank ?? true);
  const [agenticMode, setAgenticMode] = useState(
    () => persistedSettings?.agenticMode === true || DEFAULT_AGENTIC_MODE,
  );
  const [threadsBySession, setThreadsBySession] = useState<
    Record<string, ChatTurn[]>
  >({});
  const [selectedResponseMessageId, setSelectedResponseMessageId] = useState<
    string | null
  >(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [submitRequestId, setSubmitRequestId] = useState<string | null>(null);
  const [feedbackByMessageId, setFeedbackByMessageId] = useState<
    Record<string, "up" | "down">
  >({});
  const [activeCitation, setActiveCitation] = useState<ChatCitationResponse | null>(null);
  const [isKnowledgeHubOpen, setIsKnowledgeHubOpen] = useState(false);

  const settingsPreferencesQuery = useQuery({
    queryKey: ["settings", "preferences", "chat"],
    queryFn: loadSettingsPreferences,
    retry: false,
  });

  const sessionsQuery = useInfiniteQuery({
    queryKey: queryKeys.chat.sessions,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listChatSessions({
        limit: SESSION_LIST_LIMIT,
        offset: Number(pageParam),
      }),
    getNextPageParam: (lastPage, allPages) => {
      const loadedCount = allPages.reduce(
        (total, page) => total + page.items.length,
        0,
      );
      if (loadedCount >= lastPage.total) {
        return undefined;
      }
      return loadedCount;
    },
  });

  const sessions = useMemo(() => {
    const allItems =
      sessionsQuery.data?.pages.flatMap((page) => page.items) ?? [];
    const seen = new Set<string>();
    return allItems.filter((session) => {
      if (seen.has(session.session_id)) {
        return false;
      }
      seen.add(session.session_id);
      return true;
    });
  }, [sessionsQuery.data?.pages]);

  const totalSessions = sessionsQuery.data?.pages[0]?.total ?? sessions.length;

  const shouldLoadActiveSessionHistory =
    activeSessionId !== null &&
    (threadsBySession[activeThreadKey(activeSessionId)] ?? []).length === 0;

  useEffect(() => {
    const sessionIdFromQuery = searchParams.get("session_id");
    if (!sessionIdFromQuery) {
      lastAppliedSessionIdRef.current = null;
      return;
    }
    if (lastAppliedSessionIdRef.current === sessionIdFromQuery) {
      return;
    }
    setActiveSessionId(sessionIdFromQuery);
    setPendingQuestion(null);
    setSubmitRequestId(null);
    lastAppliedSessionIdRef.current = sessionIdFromQuery;
  }, [searchParams]);

  const sessionMessagesQuery = useQuery({
    queryKey: queryKeys.chat.sessionMessages(activeSessionId ?? ""),
    queryFn: async () => {
      const response = await listChatSessionMessages(activeSessionId ?? "", {
        limit: 500,
        offset: 0,
      });
      if (!activeSessionId) {
        return response;
      }
      const threadKey = activeThreadKey(activeSessionId);
      const hydratedTurns = buildTurnsFromSessionMessages(response.items);
      setThreadsBySession((previous) => {
        const existing = previous[threadKey];
        if (existing && existing.length > 0) {
          return previous;
        }
        return {
          ...previous,
          [threadKey]: hydratedTurns,
        };
      });
      return response;
    },
    enabled: shouldLoadActiveSessionHistory,
  });

  const indexedDocumentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      status: "indexed",
      limit: MAX_INDEXED_DOCS,
      offset: 0,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: MAX_INDEXED_DOCS,
        offset: 0,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
  });

  const indexedDocuments = useMemo(
    () =>
      indexedDocumentsQuery.data?.items.filter(
        (item) => item.status === "indexed",
      ) ?? [],
    [indexedDocumentsQuery.data?.items],
  );

  const indexedDocumentIdSet = useMemo(
    () => new Set(indexedDocuments.map((item) => item.document_id)),
    [indexedDocuments],
  );

  const documentIdFromQuery = searchParams.get("document_id");
  const filteredSelectedDocumentIds = useMemo(() => {
    const validSelectedDocumentIds = selectedDocumentIds.filter((documentId) =>
      indexedDocumentIdSet.has(documentId),
    );
    if (
      documentIdFromQuery &&
      indexedDocumentIdSet.has(documentIdFromQuery) &&
      !validSelectedDocumentIds.includes(documentIdFromQuery)
    ) {
      return [documentIdFromQuery, ...validSelectedDocumentIds];
    }
    return validSelectedDocumentIds;
  }, [documentIdFromQuery, indexedDocumentIdSet, selectedDocumentIds]);
  const contextSearchQueryNormalized = contextSearchQuery.trim().toLowerCase();
  const searchableIndexedDocuments = useMemo(() => {
    if (!contextSearchQueryNormalized) {
      return indexedDocuments;
    }

    return indexedDocuments.filter((document) => {
      const filename = document.filename.toLowerCase();
      const fileType = document.file_type.toLowerCase();
      return (
        filename.includes(contextSearchQueryNormalized) ||
        fileType.includes(contextSearchQueryNormalized)
      );
    });
  }, [contextSearchQueryNormalized, indexedDocuments]);
  const contextPageCount = useMemo(
    () =>
      Math.max(
        1,
        Math.ceil(searchableIndexedDocuments.length / CONTEXT_MODAL_PAGE_SIZE),
      ),
    [searchableIndexedDocuments.length],
  );
  const boundedContextPage = Math.min(contextPage, contextPageCount);
  const pagedSearchableIndexedDocuments = useMemo(() => {
    const start = (boundedContextPage - 1) * CONTEXT_MODAL_PAGE_SIZE;
    return searchableIndexedDocuments.slice(
      start,
      start + CONTEXT_MODAL_PAGE_SIZE,
    );
  }, [boundedContextPage, searchableIndexedDocuments]);
  const contextPageStartIndex =
    searchableIndexedDocuments.length === 0
      ? 0
      : (boundedContextPage - 1) * CONTEXT_MODAL_PAGE_SIZE + 1;
  const contextPageEndIndex =
    searchableIndexedDocuments.length === 0
      ? 0
      : Math.min(
          boundedContextPage * CONTEXT_MODAL_PAGE_SIZE,
          searchableIndexedDocuments.length,
        );

  const hasIndexedDocuments = indexedDocuments.length > 0;
  const contextScopeDocumentCount =
    filteredSelectedDocumentIds.length > 0
      ? filteredSelectedDocumentIds.length
      : indexedDocuments.length;

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const payload: PersistedChatSettings = {
      topK,
      rerank,
      selectedDocumentIds: filteredSelectedDocumentIds,
      agenticMode,
    };
    window.localStorage.setItem(
      CHAT_SETTINGS_STORAGE_KEY,
      JSON.stringify(payload),
    );
  }, [agenticMode, filteredSelectedDocumentIds, rerank, topK]);

  useEffect(() => {
    if (!isContextModalOpen) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      setIsContextModalOpen(false);
      setContextSearchQuery("");
      setContextPage(1);
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isContextModalOpen]);

  const activeSession =
    sessions.find((item) => item.session_id === activeSessionId) ?? null;
  const thread = useMemo(
    () => threadsBySession[activeThreadKey(activeSessionId)] ?? [],
    [activeSessionId, threadsBySession],
  );
  const sessionDisplayTitleById = useMemo(() => {
    const mapped = new Map<string, string>();
    for (const session of sessions) {
      const sessionThread =
        threadsBySession[activeThreadKey(session.session_id)] ?? [];
      mapped.set(
        session.session_id,
        toSessionDisplayTitle(session.title, sessionThread),
      );
    }
    return mapped;
  }, [sessions, threadsBySession]);
  const activeSessionDisplayTitle = useMemo(() => {
    if (!activeSessionId) {
      return null;
    }
    return toSessionDisplayTitle(activeSession?.title, thread);
  }, [activeSession?.title, activeSessionId, thread]);
  const effectiveSelectedResponseMessageId = useMemo(() => {
    if (thread.length === 0) {
      return null;
    }
    if (
      selectedResponseMessageId &&
      thread.some(
        (turn) => turn.response.message_id === selectedResponseMessageId,
      )
    ) {
      return selectedResponseMessageId;
    }
    return thread[thread.length - 1].response.message_id;
  }, [selectedResponseMessageId, thread]);
  const selectedCitationTurn =
    thread.find(
      (turn) => turn.response.message_id === effectiveSelectedResponseMessageId,
    ) ??
    thread[thread.length - 1] ??
    null;
  const selectedCitationPipelineHref = selectedCitationTurn
    ? buildChatPipelineHref(selectedCitationTurn.response)
    : null;
  const selectedAgentRunId =
    selectedCitationTurn?.response.agent_run_id ?? null;
  const selectedAgentRunQuery = useQuery({
    queryKey: queryKeys.agent.run(selectedAgentRunId ?? ""),
    queryFn: () => getAgentRun(selectedAgentRunId ?? ""),
    enabled: Boolean(selectedAgentRunId),
    refetchInterval: (query) => {
      const data = query.state.data as AgentRunDetailResponse | undefined;
      if (!data || isTerminalAgentRunStatus(data.status)) {
        return false;
      }
      return AGENT_RUN_POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: true,
  });

  const queryMutation = useMutation({
    mutationFn: (payload: ChatQueryRequest) => queryChat(payload),
    onSuccess: async (response, payload) => {
      const resolvedSessionId =
        response.chat_session_id ?? payload.chat_session_id ?? activeSessionId;
      const nextSessionId = resolvedSessionId ?? DRAFT_SESSION_KEY;
      const previousThreadKey = activeThreadKey(
        payload.chat_session_id ?? null,
      );
      const nextTurn: ChatTurn = {
        question: payload.question,
        response: toTurnResponseFromQuery(response),
      };

      setThreadsBySession((previous) => {
        const sourceThread = previous[previousThreadKey] ?? [];
        const merged = [...sourceThread, nextTurn];
        const next = { ...previous, [nextSessionId]: merged };
        if (previousThreadKey !== nextSessionId) {
          delete next[previousThreadKey];
        }
        return next;
      });

      setActiveSessionId(resolvedSessionId ?? null);
      setSelectedResponseMessageId(nextTurn.response.message_id);
      replaceSessionParamInUrl(resolvedSessionId ?? null);
      setSubmitRequestId(null);
      setPendingQuestion(null);
      await invalidateAfterMutation(queryClient, "chat.query");
    },
    onError: (error) => {
      setSubmitRequestId(extractRequestIdFromError(error));
      setPendingQuestion(null);
    },
  });

  const agentRunMutation = useMutation({
    mutationFn: (payload: AgentRunCreateRequest) => createAgentRun(payload),
  });

  const decideApprovalMutation = useMutation({
    mutationFn: (params: {
      runId: string;
      approvalId: string;
      payload: AgentApprovalDecisionRequest;
    }) =>
      decideAgentRunApproval(params.runId, params.approvalId, params.payload),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.agent.run(variables.runId),
      });
    },
  });

  const createSessionMutation = useMutation({
    mutationFn: (title: string | null) => createChatSession({ title }),
  });

  const isComposerDisabled =
    queryMutation.isPending ||
    agentRunMutation.isPending ||
    createSessionMutation.isPending ||
    question.trim().length === 0 ||
    indexedDocumentsQuery.isLoading ||
    indexedDocumentsQuery.isError ||
    !hasIndexedDocuments;

  const listForbidden =
    isForbiddenError(indexedDocumentsQuery.error) ||
    isForbiddenError(sessionsQuery.error);
  const composerError =
    queryMutation.error ??
    agentRunMutation.error ??
    createSessionMutation.error;
  const composerForbidden = isForbiddenError(composerError);
  const canDecideApprovals = isAdminLikeRole(state.session?.role ?? null);
  const showDebugDetails =
    isAdminLikeRole(state.session?.role ?? null) ||
    Boolean(settingsPreferencesQuery.data?.developerMode);
  const selectedCitationDocumentCount = useMemo(() => {
    if (!selectedCitationTurn) {
      return 0;
    }
    const uniqueDocumentIds = new Set(
      selectedCitationTurn.response.citations
        .map((citation) => citation.document_id)
        .filter((documentId): documentId is string => documentId.length > 0),
    );
    return uniqueDocumentIds.size;
  }, [selectedCitationTurn]);

  function toggleDocument(documentId: string) {
    setSelectedDocumentIds((previous) => {
      const validPrevious = previous.filter((value) =>
        indexedDocumentIdSet.has(value),
      );
      if (validPrevious.includes(documentId)) {
        return validPrevious.filter((value) => value !== documentId);
      }
      return [...validPrevious, documentId];
    });
  }

  function resetForNewChat() {
    setActiveSessionId(null);
    setSelectedResponseMessageId(null);
    setQuestion("");
    setPendingQuestion(null);
    setSubmitRequestId(null);
    replaceSessionParamInUrl(null);
  }

  async function handleApprovalDecision(params: {
    runId: string;
    approvalId: string;
    status: "approved" | "rejected";
  }) {
    await decideApprovalMutation.mutateAsync({
      runId: params.runId,
      approvalId: params.approvalId,
      payload: {
        status: params.status,
      },
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitQuestion();
  }

  async function submitQuestion() {
    const trimmedQuestion = question.trim();
    await submitQuestionText(trimmedQuestion, true);
  }

  async function submitQuestionText(
    questionText: string,
    clearComposerOnSubmit: boolean,
  ) {
    const trimmedQuestion = questionText.trim();
    if (
      !trimmedQuestion ||
      queryMutation.isPending ||
      agentRunMutation.isPending ||
      createSessionMutation.isPending ||
      !hasIndexedDocuments
    ) {
      return;
    }

    setSubmitRequestId(null);
    setPendingQuestion(trimmedQuestion);
    if (clearComposerOnSubmit) {
      setQuestion("");
    }

    if (AGENTIC_CHAT_ENABLED && agenticMode) {
      const previousThreadKey = activeThreadKey(activeSessionId);
      let fallbackToStandardQuery = false;
      const payload: AgentRunCreateRequest = {
        agentic_mode: true,
        request: {
          objective: trimmedQuestion,
          mode: "answer",
          question: trimmedQuestion,
          document_ids:
            filteredSelectedDocumentIds.length > 0
              ? filteredSelectedDocumentIds
              : undefined,
          top_k: topK,
          rerank,
        },
      };

      try {
        const response = await agentRunMutation.mutateAsync(payload);
        const nextTurn: ChatTurn = {
          question: trimmedQuestion,
          response: toTurnResponseFromAgentRun(response.run),
        };
        setThreadsBySession((previous) => {
          const sourceThread = previous[previousThreadKey] ?? [];
          return {
            ...previous,
            [previousThreadKey]: [...sourceThread, nextTurn],
          };
        });
        setSelectedResponseMessageId(nextTurn.response.message_id);
        setSubmitRequestId(null);
        setPendingQuestion(null);
        await invalidateAfterMutation(queryClient, "agent.run");
        return;
      } catch (error) {
        if (isApiClientError(error) && error.code === "feature_not_available") {
          // Backend agentic feature is off; fall back to standard query flow.
          setAgenticMode(false);
          agentRunMutation.reset();
          setSubmitRequestId(null);
          fallbackToStandardQuery = true;
        } else {
          setSubmitRequestId(extractRequestIdFromError(error));
          if (clearComposerOnSubmit) {
            setQuestion(trimmedQuestion);
          }
          setPendingQuestion(null);
          return;
        }
      }
      if (!fallbackToStandardQuery) {
        return;
      }
    }

    let targetSessionId = activeSessionId;
    if (!targetSessionId) {
      try {
        const createdSession = await createSessionMutation.mutateAsync(
          trimmedQuestion.slice(0, SESSION_TITLE_MAX_LENGTH),
        );
        targetSessionId = createdSession.session_id;
        setActiveSessionId(createdSession.session_id);
        replaceSessionParamInUrl(createdSession.session_id);
      } catch (error) {
        setSubmitRequestId(extractRequestIdFromError(error));
        setPendingQuestion(null);
        if (clearComposerOnSubmit) {
          setQuestion(trimmedQuestion);
        }
        return;
      }
    }

    queryMutation.mutate(
      {
        question: trimmedQuestion,
        chat_session_id: targetSessionId,
        document_ids:
          filteredSelectedDocumentIds.length > 0
            ? filteredSelectedDocumentIds
            : undefined,
        top_k: topK,
        rerank,
      },
      {
        onError: (error) => {
          setSubmitRequestId(extractRequestIdFromError(error));
          if (clearComposerOnSubmit) {
            setQuestion(trimmedQuestion);
          }
          setPendingQuestion(null);
        },
      },
    );
  }

  if (listForbidden) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Chat access is restricted"
          description="Your role does not have permission to query documents in this organization."
          requestId={extractRequestIdFromError(
            indexedDocumentsQuery.error ?? sessionsQuery.error,
          )}
          compact={false}
        />
      </section>
    );
  }

  return (
    <>
      <section className="flex h-full min-h-0 flex-col gap-4 px-4 py-4 lg:px-8 lg:py-6">
        <header className="rounded-2xl border border-[#d7d4e8] bg-white px-4 py-4 shadow-sm lg:px-5">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0">
              <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
                Rudix Chat
              </p>
              <h1 className="truncate text-xl font-semibold text-[#2a2640] lg:text-2xl">
                Chat Session
              </h1>
              <div className="mt-2 inline-flex items-center gap-2 rounded-lg bg-[#ece8ff] px-2.5 py-1">
                <span className="font-mono text-xs text-[#463f7b]">
                  {activeSessionId ?? DRAFT_SESSION_KEY}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <span
                  className="material-symbols-outlined pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-[18px] text-[#6a6780]"
                  aria-hidden="true"
                >
                  search
                </span>
                <input
                  type="text"
                  placeholder="Search sessions..."
                  className="h-9 w-60 rounded-full border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-xs text-[#2f2a46] ring-[#3525cd]/20 outline-none focus:ring"
                />
              </div>
              <Link
                href="/documents"
                className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
              >
                Upload documents
              </Link>
              <button
                type="button"
                onClick={resetForNewChat}
                className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
              >
                New chat
              </button>
            </div>
          </div>
        </header>

        <div className={`grid min-h-0 flex-1 gap-4 ${(isKnowledgeHubOpen || activeCitation !== null) ? "xl:grid-cols-[280px_minmax(0,1fr)_320px]" : "xl:grid-cols-[280px_minmax(0,1fr)]"}`}>
          <aside className="hide-scrollbar min-h-0 space-y-4 xl:overflow-y-auto xl:pr-1">
            <section className="rounded-2xl border border-[#d7d4e8] bg-[#f5f2ff] p-4">
              <h2 className="mb-2 text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
                Sessions
              </h2>
              {sessionsQuery.isLoading ? (
                <LoadingState compact title="Loading sessions..." />
              ) : sessionsQuery.isError ? (
                <ErrorState
                  compact
                  error={sessionsQuery.error}
                  description={getApiErrorMessage(sessionsQuery.error)}
                  onRetry={() => {
                    void sessionsQuery.refetch();
                  }}
                />
              ) : sessions.length ? (
                <>
                  <ul className="space-y-2">
                    {sessions.map((session) => (
                      <li key={session.session_id}>
                        <button
                          type="button"
                          onClick={() => {
                            setActiveSessionId(session.session_id);
                            setSubmitRequestId(null);
                            setPendingQuestion(null);
                            replaceSessionParamInUrl(session.session_id);
                          }}
                          className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition ${
                            session.session_id === activeSessionId
                              ? "border-[#3525cd] bg-[#ece8ff] text-[#2f2a46]"
                              : "border-[#dfdbef] bg-white text-[#4f4b63] hover:bg-[#faf9ff]"
                          }`}
                        >
                          <p className="truncate font-semibold">
                            {sessionDisplayTitleById.get(session.session_id) ??
                              "Untitled session"}
                          </p>
                          <p className="mt-1 text-xs">
                            {session.message_count} messages • updated{" "}
                            {formatDate(session.updated_at)}
                          </p>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {sessionsQuery.hasNextPage ? (
                    <button
                      type="button"
                      onClick={() => {
                        void sessionsQuery.fetchNextPage();
                      }}
                      disabled={sessionsQuery.isFetchingNextPage}
                      className="mt-3 w-full rounded-lg border border-[#cbc5e6] px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {sessionsQuery.isFetchingNextPage
                        ? "Loading more sessions..."
                        : `Load more sessions (${sessions.length}/${totalSessions})`}
                    </button>
                  ) : null}
                </>
              ) : (
                <EmptyState
                  compact
                  title="No sessions yet. Ask your first question to start one."
                />
              )}
            </section>
          </aside>

          <section className="min-h-0 rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
            <div className="flex h-full min-h-0 flex-col">
              <div className="border-b border-[#e2dff1] px-4 py-3">
                <h2 className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
                  Conversation
                </h2>
                <p className="mt-1 text-xs text-[#5f5a74]">
                  {activeSession ? (
                    <>
                      Session:{" "}
                      <span className="font-semibold text-[#2f2a46]">
                        {activeSessionDisplayTitle}
                      </span>
                      {" • "}
                      {activeSession.message_count} messages
                      {" • "}
                      updated {formatDate(activeSession.updated_at)}
                    </>
                  ) : (
                    "New chat draft. Start with a question to create a session."
                  )}
                </p>
              </div>

              <div className="hide-scrollbar min-h-0 flex-1 overflow-y-auto bg-white p-4">
                {sessionMessagesQuery.isLoading &&
                activeSession &&
                thread.length === 0 &&
                activeSession.message_count > 0 ? (
                  <LoadingState compact title="Loading session history..." />
                ) : null}

                {sessionMessagesQuery.isError &&
                activeSession &&
                thread.length === 0 &&
                activeSession.message_count > 0 ? (
                  <ErrorState
                    compact
                    title="Unable to load prior messages"
                    error={sessionMessagesQuery.error}
                    description={getApiErrorMessage(sessionMessagesQuery.error)}
                    onRetry={() => {
                      void sessionMessagesQuery.refetch();
                    }}
                  />
                ) : null}

                {thread.length === 0 &&
                !pendingQuestion &&
                !sessionMessagesQuery.isLoading ? (
                  <EmptyState
                    compact
                    title="No messages yet. Submit a question to start the conversation."
                  />
                ) : (
                  <ul className="space-y-6">
                    {thread.map((turn, turnIndex) => {
                      const isLatestTurn = turnIndex === thread.length - 1;

                      return (
                        <li
                          key={turn.response.message_id}
                          className="space-y-3"
                        >
                          <div className="flex justify-end">
                            <article className="max-w-[80%] rounded-xl rounded-tr-none bg-[#f0ecf9] px-4 py-3 shadow-sm">
                              <p className="sr-only">Question</p>
                              <p className="hide-scrollbar max-h-72 overflow-y-auto pr-1 text-sm break-words whitespace-pre-wrap text-[#1b1b24]">
                                {turn.question}
                              </p>
                            </article>
                          </div>

                          <div className="flex items-start gap-3">
                            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#3525cd] text-white">
                              <span
                                className="material-symbols-outlined text-[18px]"
                                aria-hidden="true"
                                style={{ fontVariationSettings: "'FILL' 1" }}
                              >
                                auto_awesome
                              </span>
                            </div>
                            <article className="max-w-[92%] flex-1 rounded-xl rounded-tl-none border border-[#c7c4d8] bg-[#f0ecf9] px-4 py-3 shadow-sm">
                              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                                <span
                                  className={confidenceBadgeClass(
                                    turn.response.confidence_category,
                                  )}
                                >
                                  <span
                                    className="material-symbols-outlined text-xs"
                                    aria-hidden="true"
                                    style={{ fontVariationSettings: "'FILL' 1" }}
                                  >
                                    check_circle
                                  </span>
                                  Confidence{" "}
                                  {formatPercent(turn.response.confidence_score)}
                                </span>
                                <div className="flex items-center gap-2">
                                  {turn.response.agent_run_status ? (
                                    <span
                                      className={agentRunStatusClass(
                                        turn.response.agent_run_status,
                                      )}
                                    >
                                      Agent {turn.response.agent_run_status}
                                    </span>
                                  ) : null}
                                  <span className="font-mono text-xs text-[#6a6780]">
                                    {formatDate(turn.response.created_at)}
                                  </span>
                                </div>
                              </div>

                              {turn.response.confidence_category === "low" &&
                              !turn.response.not_found ? (
                                <p className="mb-3 rounded-lg border border-[#c7c4d8] bg-white px-3 py-2 text-xs text-[#464555]">
                                  Low confidence warning: validate this answer
                                  against the cited source text.
                                </p>
                              ) : null}

                              {turn.response.not_found ? (
                                <div className="space-y-2">
                                  <p className="rounded-lg border border-[#d2cee6] bg-[#faf9ff] px-3 py-2 text-sm break-words text-[#2f2a46]">
                                    No grounded answer was found in the selected
                                    documents.
                                  </p>
                                  <p className="text-xs text-[#6a6780]">
                                    Try refining your question, changing
                                    document scope, or adjusting retrieval
                                    settings.
                                  </p>
                                </div>
                              ) : (
                                <>
                                  <p className="hide-scrollbar max-h-80 overflow-y-auto pr-1 text-sm break-words whitespace-pre-wrap text-[#2f2a46]">
                                    {turn.response.answer}
                                  </p>
                                  {turn.response.citations.length > 0 && (
                                    <div className="mt-3 grid grid-cols-2 gap-2">
                                      {turn.response.citations.map((citation, ci) => (
                                        <button
                                          key={`inline:${citation.document_id}:${citation.chunk_id}:${ci}`}
                                          type="button"
                                          onClick={() => {
                                            setSelectedResponseMessageId(turn.response.message_id);
                                            setIsKnowledgeHubOpen(false);
                                            setActiveCitation(citation);
                                          }}
                                          className="relative flex items-start gap-2 rounded-lg border border-[#c7c4d8] bg-white p-2 text-left hover:bg-[#eae6f4] transition-colors cursor-pointer"
                                        >
                                          <span
                                            className={`material-symbols-outlined text-base shrink-0 ${getFileTypeColorClass(citation.filename)}`}
                                            aria-hidden="true"
                                          >
                                            {getFileIcon(citation.filename)}
                                          </span>
                                          <div className="min-w-0 overflow-hidden">
                                            <p className={`text-[10px] font-bold mb-0.5 ${getFileTypeColorClass(citation.filename)}`}>
                                              {getFileTypeLabel(citation.filename)}
                                            </p>
                                            <p
                                              className="truncate text-xs font-bold text-[#1b1b24]"
                                              title={citation.filename ?? "Document"}
                                            >
                                              {citation.filename ?? "Document"}
                                            </p>
                                            {citation.text_snippet && (
                                              <p className="mt-0.5 line-clamp-1 text-[10px] text-[#464555]">
                                                {citation.text_snippet}
                                              </p>
                                            )}
                                          </div>
                                        </button>
                                      ))}
                                    </div>
                                  )}
                                  {turn.response.citations[0]?.text_snippet && (
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setSelectedResponseMessageId(turn.response.message_id);
                                        setActiveCitation(null);
                                        setIsKnowledgeHubOpen(true);
                                      }}
                                      className="mt-3 w-full cursor-pointer rounded-r border-l-4 border-[#3525cd] bg-white px-3 py-2 text-left italic text-sm text-[#464555] shadow-sm hover:bg-[#f5f2ff] transition-colors"
                                    >
                                      {turn.response.citations[0].text_snippet}
                                    </button>
                                  )}
                                </>
                              )}
                              {turn.response.agent_run_error ? (
                                <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
                                  Agent stop reason:{" "}
                                  {turn.response.agent_run_error.message}
                                </p>
                              ) : null}
                              {isLatestTurn ? (
                                <div className="mt-3 flex flex-wrap items-center gap-2">
                                  {CHAT_FEEDBACK_ENABLED ? (
                                    <>
                                      <button
                                        type="button"
                                        aria-label="Mark answer helpful"
                                        onClick={() => {
                                          setFeedbackByMessageId((previous) => {
                                            const next = { ...previous };
                                            if (
                                              next[turn.response.message_id] ===
                                              "up"
                                            ) {
                                              delete next[
                                                turn.response.message_id
                                              ];
                                            } else {
                                              next[turn.response.message_id] =
                                                "up";
                                            }
                                            return next;
                                          });
                                        }}
                                        className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs ${feedbackByMessageId[turn.response.message_id] === "up" ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-[#d2cee6] text-[#3e376f] hover:bg-[#f5f3ff]"}`}
                                      >
                                        <span
                                          className="material-symbols-outlined text-[16px]"
                                          aria-hidden="true"
                                        >
                                          thumb_up
                                        </span>
                                        Helpful
                                      </button>
                                      <button
                                        type="button"
                                        aria-label="Mark answer not helpful"
                                        onClick={() => {
                                          setFeedbackByMessageId((previous) => {
                                            const next = { ...previous };
                                            if (
                                              next[turn.response.message_id] ===
                                              "down"
                                            ) {
                                              delete next[
                                                turn.response.message_id
                                              ];
                                            } else {
                                              next[turn.response.message_id] =
                                                "down";
                                            }
                                            return next;
                                          });
                                        }}
                                        className={`inline-flex items-center rounded border px-2 py-1 text-xs ${feedbackByMessageId[turn.response.message_id] === "down" ? "border-rose-300 bg-rose-50 text-rose-800" : "border-[#d2cee6] text-[#3e376f] hover:bg-[#f5f3ff]"}`}
                                      >
                                        <span
                                          className="material-symbols-outlined text-[16px]"
                                          aria-hidden="true"
                                        >
                                          thumb_down
                                        </span>
                                      </button>
                                    </>
                                  ) : null}
                                  <button
                                    type="button"
                                    onClick={() => {
                                      void submitQuestionText(
                                        turn.question,
                                        false,
                                      );
                                    }}
                                    disabled={
                                      queryMutation.isPending ||
                                      agentRunMutation.isPending ||
                                      createSessionMutation.isPending ||
                                      !hasIndexedDocuments
                                    }
                                    className="inline-flex items-center gap-1 rounded border border-[#d2cee6] px-2 py-1 text-xs text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                                  >
                                    <span
                                      className="material-symbols-outlined text-[16px]"
                                      aria-hidden="true"
                                    >
                                      refresh
                                    </span>
                                    Regenerate
                                  </button>
                                </div>
                              ) : null}
                            </article>
                          </div>
                        </li>
                      );
                    })}
                    {pendingQuestion ? (
                      <li className="space-y-3">
                        <div className="flex justify-end">
                          <article className="max-w-[80%] rounded-xl rounded-tr-none bg-[#f0ecf9] px-4 py-3 shadow-sm">
                            <p className="sr-only">Question</p>
                            <p className="hide-scrollbar max-h-72 overflow-y-auto pr-1 text-sm break-words whitespace-pre-wrap text-[#1b1b24]">
                              {pendingQuestion}
                            </p>
                          </article>
                        </div>
                        <div className="flex items-start gap-3">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#3525cd] text-white">
                            <span
                              className="material-symbols-outlined text-[18px]"
                              aria-hidden="true"
                              style={{ fontVariationSettings: "'FILL' 1" }}
                            >
                              bolt
                            </span>
                          </div>
                          <article className="rounded-xl rounded-tl-none border border-[#c7c4d8] bg-[#f0ecf9] px-4 py-3 shadow-sm">
                            <p className="text-sm text-[#464555]">
                              {STREAMING_PLACEHOLDER_ENABLED
                                ? "Streaming response..."
                                : "Generating answer..."}
                            </p>
                          </article>
                        </div>
                      </li>
                    ) : null}
                  </ul>
                )}
              </div>

              {composerForbidden ? (
                <div className="border-t border-[#e2dff1] px-4 py-3">
                  <ForbiddenState
                    compact
                    title="Query is not allowed"
                    description="You do not have permission to query the selected documents in this organization."
                    requestId={extractRequestIdFromError(composerError)}
                  />
                </div>
              ) : null}

              {composerError && !composerForbidden ? (
                <div className="border-t border-[#e2dff1] px-4 py-3">
                  <ErrorState
                    title="Unable to complete the query."
                    error={composerError}
                    description={getApiErrorMessage(composerError)}
                    requestId={submitRequestId}
                  />
                </div>
              ) : null}

              <div className="border-t border-[#e2dff1] p-4">
                <form onSubmit={handleSubmit}>
                  <div className="relative overflow-hidden rounded-2xl border border-[#c7c4d8] bg-[#f0ecf9] shadow-sm">
                    {/* Integrated toolbar */}
                    <div className="flex items-center gap-3 border-b border-[#c7c4d8] bg-[#f5f2ff] px-3 py-2 text-[11px] font-semibold text-[#464555]">
                      <div className="flex items-center gap-2">
                        <label htmlFor="top-k-slider" className="uppercase tracking-wider">Top-k</label>
                        <input
                          id="top-k-slider"
                          type="range"
                          min={MIN_TOP_K}
                          max={MAX_TOP_K}
                          value={topK}
                          onChange={(event) => {
                            const parsed = Number.parseInt(event.target.value, 10);
                            if (Number.isFinite(parsed)) setTopK(Math.min(MAX_TOP_K, Math.max(MIN_TOP_K, parsed)));
                          }}
                          className="h-1 w-20 cursor-pointer appearance-none rounded-full bg-[#c7c4d8] accent-[#3525cd]"
                        />
                        <span className="font-mono text-[#3525cd]">{topK}</span>
                        <input id="top-k-input" type="number" min={MIN_TOP_K} max={MAX_TOP_K} value={topK}
                          onChange={(event) => {
                            const parsed = Number.parseInt(event.target.value, 10);
                            if (Number.isFinite(parsed)) setTopK(Math.min(MAX_TOP_K, Math.max(MIN_TOP_K, parsed)));
                          }}
                          className="sr-only"
                          aria-label="Top K"
                        />
                      </div>

                      <span className="h-3 w-px bg-[#c7c4d8]" />

                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <span>Rerank</span>
                        <span className="relative inline-flex items-center">
                          <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} className="peer sr-only" />
                          <span className="h-3.5 w-7 rounded-full bg-[#c7c4d8] transition peer-checked:bg-[#3525cd]" />
                          <span className="absolute left-0.5 h-2.5 w-2.5 rounded-full bg-white transition peer-checked:translate-x-3.5" />
                        </span>
                      </label>

                      <span className="h-3 w-px bg-[#c7c4d8]" />

                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <span>Agentic</span>
                        <span className="relative inline-flex items-center">
                          <input type="checkbox" checked={agenticMode} disabled={!AGENTIC_CHAT_ENABLED}
                            onChange={(e) => setAgenticMode(e.target.checked)} className="peer sr-only" />
                          <span className="h-3.5 w-7 rounded-full bg-[#c7c4d8] transition peer-checked:bg-[#3525cd] peer-disabled:opacity-50" />
                          <span className="absolute left-0.5 h-2.5 w-2.5 rounded-full bg-white transition peer-checked:translate-x-3.5 peer-disabled:opacity-80" />
                        </span>
                      </label>

                      <button
                        type="button"
                        onClick={() => { setIsContextModalOpen(true); setContextSearchQuery(""); setContextPage(1); }}
                        className="ml-auto flex items-center gap-1 text-[#3525cd] hover:text-[#2b1fa8] transition-colors"
                      >
                        <span className="material-symbols-outlined text-sm" aria-hidden="true">folder_open</span>
                        Context ({contextScopeDocumentCount})
                      </button>
                    </div>

                    {/* Textarea + send */}
                    <div className="relative flex items-end bg-white">
                      <textarea
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        onKeyDown={(event) => {
                          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                            event.preventDefault();
                            void submitQuestion();
                          }
                        }}
                        rows={2}
                        placeholder="Type a message or use '/' for commands..."
                        disabled={!hasIndexedDocuments}
                        className="w-full resize-none border-none bg-transparent py-3 pl-3 pr-14 text-sm text-[#2f2a46] outline-none focus:ring-0"
                      />
                      <div className="absolute bottom-2.5 right-3">
                        <button
                          type="submit"
                          disabled={isComposerDisabled}
                          aria-label={
                            createSessionMutation.isPending ? "Starting session…"
                            : agentRunMutation.isPending ? "Running agent…"
                            : queryMutation.isPending ? "Generating answer…"
                            : "Send message"
                          }
                          className="flex items-center justify-center rounded-xl bg-[#3525cd] p-2 text-white hover:shadow-lg active:scale-90 transition-all disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <span className="material-symbols-outlined text-[20px]" aria-hidden="true">arrow_upward</span>
                        </button>
                      </div>
                    </div>
                  </div>

                  {!AGENTIC_CHAT_ENABLED && (
                    <p className="mt-2 text-xs text-[#8a4762]">Agentic Mode is disabled for this deployment.</p>
                  )}
                  {!hasIndexedDocuments && (
                    <p className="mt-2 text-center text-xs text-[#777587]">Chat is disabled until at least one document is indexed.</p>
                  )}
                </form>
              </div>
            </div>
          </section>

          <aside className={`relative flex min-h-0 flex-col overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-sm ${(isKnowledgeHubOpen || activeCitation !== null) ? "" : "hidden"}`}>
            {/* ── Header ── */}
            <div className="flex items-center justify-between border-b border-[#e4e1ee] p-4">
              <div>
                <h2 className="text-lg font-semibold text-[#1b1b24]">Knowledge Hub</h2>
                <p className="text-xs text-[#464555]">Live insights from current context</p>
              </div>
              <button
                type="button"
                onClick={() => setIsKnowledgeHubOpen(false)}
                aria-label="Close Knowledge Hub"
                className="rounded-full p-1.5 text-[#464555] hover:bg-[#f0ecf9] transition-colors"
              >
                <span className="material-symbols-outlined text-[20px]" aria-hidden="true">close</span>
              </button>
            </div>

            {/* ── Scrollable body ── */}
            <div className="hide-scrollbar flex-1 overflow-y-auto">
              {/* Context Map */}
              <div className="p-4">
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-[#464555]">Context Map</span>
                  <button type="button" className="text-[10px] font-bold text-[#3525cd]">EXPAND</button>
                </div>
                <div className="relative h-40 overflow-hidden rounded-xl border border-[#c7c4d8] bg-[#f0ecf9] group">
                  <div className="pointer-events-none absolute inset-0 opacity-20">
                    <svg className="h-full w-full">
                      <line stroke="#3525cd" strokeWidth="1" x1="20%" y1="30%" x2="50%" y2="50%" />
                      <line stroke="#3525cd" strokeWidth="1" x1="50%" y1="50%" x2="80%" y2="20%" />
                      <line stroke="#3525cd" strokeWidth="1" x1="50%" y1="50%" x2="70%" y2="80%" />
                    </svg>
                  </div>
                  <div className="absolute top-[30%] left-[20%] h-3 w-3 rounded-full bg-[#3525cd] shadow-lg" />
                  <div className="absolute top-[50%] left-[50%] flex h-6 w-6 items-center justify-center rounded-full bg-[#3525cd] shadow-lg">
                    <span className="material-symbols-outlined text-xs text-white" style={{ fontVariationSettings: "'FILL' 1" }}>stars</span>
                  </div>
                  <div className="absolute top-[20%] left-[78%] h-2.5 w-2.5 rounded-full bg-[#505f76] shadow-lg" />
                  <div className="absolute top-[78%] left-[68%] h-4 w-4 rounded-full bg-[#a44100] shadow-lg" />
                  <div className="absolute bottom-2 left-2 right-2 rounded border border-[#c7c4d8] bg-white/80 px-2 py-0.5 text-center font-mono text-[9px] text-[#464555] backdrop-blur-sm">
                    CONNECTED: {selectedCitationTurn?.response.citations.length ?? 0} SOURCES
                  </div>
                </div>
              </div>

              {/* Source Documents */}
              <div className="border-t border-[#e4e1ee] bg-[#f5f2ff] p-4">
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-[#464555]">Source Documents</span>
                  <span className="material-symbols-outlined text-sm text-[#464555]" aria-hidden="true">filter_list</span>
                </div>

                {!selectedCitationTurn ? (
                  <p className="text-xs text-[#777587]">Ask a question to see source documents.</p>
                ) : selectedCitationTurn.response.not_found ? (
                  <p className="text-xs text-[#777587]">No citations are shown because the assistant did not find grounded evidence for this response.</p>
                ) : selectedCitationTurn.response.citations.length === 0 ? (
                  <p className="text-xs text-[#777587]">No citations for this response.</p>
                ) : (
                  <div className="space-y-2">
                    {selectedCitationTurn.response.citations.map((citation, ci) => (
                      <button
                        key={`hub:${citation.document_id}:${citation.chunk_id}:${ci}`}
                        type="button"
                        onClick={() => { setActiveCitation(citation); setIsKnowledgeHubOpen(false); }}
                        className="group w-full rounded-lg border border-[#c7c4d8] bg-white p-3 text-left transition-all hover:border-[#3525cd]"
                      >
                        <div className="mb-1 flex items-center justify-between">
                          <span className={`text-[10px] font-bold ${getFileTypeColorClass(citation.filename)}`}>
                            {getFileTypeLabel(citation.filename)}
                          </span>
                          <span className="material-symbols-outlined text-xs text-[#464555] group-hover:text-[#3525cd]" aria-hidden="true">open_in_new</span>
                        </div>
                        <h4
                          className="mb-1 truncate text-sm font-bold text-[#1b1b24]"
                          title={citation.filename ?? "Unknown document"}
                        >
                          {citation.filename ?? "Unknown document"}
                        </h4>
                        <div className="flex items-center gap-2">
                          {citation.page_number ? (
                            <span className="rounded bg-[#f0ecf9] px-2 py-0.5 font-mono text-[9px]">
                              PAGE {citation.page_number}
                            </span>
                          ) : null}
                          <span className="text-[9px] text-[#464555]">
                            score {formatScore(citation.score)}
                          </span>
                        </div>
                      </button>
                    ))}
                    {selectedCitationPipelineHref ? (
                      <Link
                        href={selectedCitationPipelineHref}
                        className="mt-1 flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-[#777587] py-2 text-xs font-bold text-[#464555] transition-all hover:border-[#3525cd] hover:bg-white hover:text-[#3525cd]"
                      >
                        View pipeline run
                      </Link>
                    ) : null}
                  </div>
                )}

                {/* Agent timeline */}
                {selectedAgentRunId ? (
                  <div className="mt-4">
                    <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-[#464555]">Agent timeline</p>
                    {selectedAgentRunQuery.isLoading ? (
                      <LoadingState compact title="Loading timeline..." />
                    ) : selectedAgentRunQuery.isError ? (
                      <ErrorState compact error={selectedAgentRunQuery.error} description={getApiErrorMessage(selectedAgentRunQuery.error)} onRetry={() => { void selectedAgentRunQuery.refetch(); }} />
                    ) : selectedAgentRunQuery.data ? (
                      <div className="space-y-1.5 text-xs text-[#4f4b63]">
                        <div className="flex flex-wrap items-center gap-2 rounded border border-[#ebe8f7] px-2 py-1.5">
                          <span className={agentRunStatusClass(selectedAgentRunQuery.data.status)}>{selectedAgentRunQuery.data.status}</span>
                          <span className="truncate text-[#6a6780]">run {selectedAgentRunQuery.data.run_id.slice(0, 8)}…</span>
                        </div>
                        {selectedAgentRunQuery.data.approvals.length > 0 && (
                          <p className="text-[10px] font-bold uppercase tracking-widest text-[#464555]">Approvals</p>
                        )}
                        {selectedAgentRunQuery.data.approvals.filter((a) => a.status === "pending").map((approval) => (
                          <div key={approval.approval_id} className="rounded border border-amber-200 bg-amber-50 px-2 py-2">
                            <p className="mb-1 text-xs text-amber-800">{approval.request_summary ?? "Approval needed"}</p>
                            {canDecideApprovals && (
                              <div className="flex gap-2">
                                <button type="button" disabled={decideApprovalMutation.isPending}
                                  onClick={() => { void handleApprovalDecision({ runId: selectedAgentRunQuery.data.run_id, approvalId: approval.approval_id, status: "approved" }); }}
                                  className="rounded border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800 disabled:opacity-60">Approve</button>
                                <button type="button" disabled={decideApprovalMutation.isPending}
                                  onClick={() => { void handleApprovalDecision({ runId: selectedAgentRunQuery.data.run_id, approvalId: approval.approval_id, status: "rejected" }); }}
                                  className="rounded border border-rose-300 bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-800 disabled:opacity-60">Reject</button>
                              </div>
                            )}
                          </div>
                        ))}
                        <ol className="space-y-1">
                          {selectedAgentRunQuery.data.steps.map((step) => (
                            <li key={step.step_id} className="rounded border border-[#ebe8f7] px-2 py-1.5">
                              <p className="font-semibold text-[#3f3b58]">{step.sequence}. {step.step_name}</p>
                              <p className="text-[#6a6780]">{step.status}{step.duration_ms !== null ? ` • ${step.duration_ms}ms` : ""}</p>
                            </li>
                          ))}
                        </ol>
                        {decideApprovalMutation.isError && (
                          <p className="rounded border border-rose-200 bg-rose-50 px-2 py-1.5 text-rose-800">
                            {getApiErrorMessage(decideApprovalMutation.error)}
                          </p>
                        )}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {/* Debug details for admins */}
                {showDebugDetails && selectedCitationTurn?.response.debug ? (
                  <details className="mt-4">
                    <summary className="cursor-pointer text-[10px] font-bold uppercase tracking-widest text-[#464555]">Retrieval debug</summary>
                    <div className="mt-2 space-y-1 text-xs text-[#4f4b63]">
                      <dl className="grid grid-cols-2 gap-1 rounded border border-[#ebe8f7] px-2 py-2">
                        {(["retrieval_count","selected_count","rerank_applied","embedding_model","llm_model"] as const).map((key) => (
                          <div key={key} className={key === "llm_model" ? "col-span-2" : ""}>
                            <dt className="font-semibold">{key}</dt>
                            <dd>{String((selectedCitationTurn.response.debug as Record<string,unknown>)[key] ?? "N/A")}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  </details>
                ) : null}
              </div>
            </div>

            {/* ── Metrics footer ── */}
            <div className="border-t border-[#e4e1ee] bg-white p-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-[#c7c4d8] bg-[#f0ecf9] p-2">
                  <p className="mb-1 text-[9px] font-bold uppercase tracking-wider text-[#464555]">Confidence</p>
                  <p className="text-lg font-semibold text-[#3525cd]">
                    {selectedCitationTurn
                      ? selectedCitationTurn.response.confidence_category === "high" ? "High"
                        : selectedCitationTurn.response.confidence_category === "medium" ? "Medium"
                        : "Low"
                      : "—"}
                  </p>
                </div>
                <div className="rounded-lg border border-[#c7c4d8] bg-[#f0ecf9] p-2">
                  <p className="mb-1 text-[9px] font-bold uppercase tracking-wider text-[#464555]">Sources</p>
                  <p className="text-lg font-semibold text-[#3525cd]">
                    {selectedCitationDocumentCount > 0
                      ? String(selectedCitationDocumentCount).padStart(2, "0")
                      : "—"}
                  </p>
                </div>
              </div>
            </div>

            {/* ── Citation Detail overlay ── */}
            {activeCitation ? (
              <div className="absolute inset-0 z-50 flex flex-col bg-white">
                <div className="flex items-center justify-between border-b border-[#e4e1ee] p-4">
                  <div>
                    <h2 className="text-base font-semibold text-[#1b1b24]">Citation Details</h2>
                    <p className="font-mono text-xs text-[#464555]">
                      <span className="truncate" title={activeCitation.filename ?? "Document"}>
                        {activeCitation.filename ?? "Document"}
                      </span>
                      {activeCitation.page_number ? ` • Page ${activeCitation.page_number}` : ""}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setActiveCitation(null)}
                    aria-label="Close citation detail"
                    className="rounded-full p-1.5 text-[#464555] hover:bg-[#f0ecf9] transition-colors"
                  >
                    <span className="material-symbols-outlined text-[20px]" aria-hidden="true">close</span>
                  </button>
                </div>

                <div className="hide-scrollbar flex-1 overflow-y-auto bg-[#f5f2ff] p-4">
                  <div className="min-h-[300px] rounded-lg border border-[#c7c4d8] bg-white p-5 font-serif text-sm leading-relaxed text-[#1b1b24] shadow-md">
                    <div className="mb-4 flex items-end justify-between border-b pb-2 font-sans text-xs italic text-[#464555]">
                      <span className="max-w-[70%] truncate" title={activeCitation.filename ?? "DOCUMENT"}>
                        {activeCitation.filename ?? "DOCUMENT"}
                      </span>
                      {activeCitation.page_number ? <span>PAGE {activeCitation.page_number}</span> : null}
                    </div>
                    <p className="mb-3 text-xs leading-relaxed opacity-40">
                      The passage below was retrieved from the indexed knowledge base as a high-relevance match for your query.
                    </p>
                    {activeCitation.text_snippet ? (
                      <div className="my-3 rounded-r border-l-4 border-[#3525cd] bg-[#e2dfff]/30 p-3">
                        <span className="mr-1 rounded bg-[#3525cd]/10 px-1 font-sans text-xs font-bold text-[#3525cd]">
                          CIT
                        </span>
                        <span className="font-bold">{activeCitation.text_snippet}</span>
                      </div>
                    ) : (
                      <p className="text-xs italic text-[#464555]">Snippet not available for this citation.</p>
                    )}
                    <p className="mt-3 text-xs leading-relaxed opacity-40">
                      Retrieval score:{" "}
                      {formatScore(activeCitation.rerank_score ?? activeCitation.similarity_score ?? activeCitation.score)}.
                    </p>
                  </div>
                </div>

                <div className="border-t border-[#e4e1ee] bg-white p-4">
                  {activeCitation.document_id ? (
                    <Link
                      href={`/documents/${encodeURIComponent(activeCitation.document_id)}?chunk_id=${encodeURIComponent(activeCitation.chunk_id)}&back=${encodeURIComponent("/chat")}`}
                      className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#3525cd] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8]"
                    >
                      <span className="material-symbols-outlined text-[18px]" aria-hidden="true">open_in_new</span>
                      Jump to Source
                    </Link>
                  ) : (
                    <p className="text-center text-xs text-[#777587]">Document link unavailable.</p>
                  )}
                </div>
              </div>
            ) : null}

          </aside>
        </div>
      </section>

      {isContextModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#1f1a3f]/45 p-4">
          <div
            ref={contextModalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="chat-context-modal-title"
            className="max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-[#e2dff1] px-4 py-3">
              <div>
                <h2
                  id="chat-context-modal-title"
                  className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase"
                >
                  Select context
                </h2>
                <p className="mt-1 text-xs text-[#6a6780]">
                  Choose indexed documents to scope retrieval.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setIsContextModalOpen(false);
                  setContextSearchQuery("");
                  setContextPage(1);
                }}
                className="rounded-lg border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
              >
                Close
              </button>
            </div>
            <div className="border-b border-[#ece8f7] px-4 py-3">
              <div className="relative">
                <span
                  className="material-symbols-outlined pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-[18px] text-[#6a6780]"
                  aria-hidden="true"
                >
                  search
                </span>
                <input
                  type="text"
                  value={contextSearchQuery}
                  onChange={(event) => {
                    setContextSearchQuery(event.target.value);
                    setContextPage(1);
                  }}
                  placeholder="Search indexed documents..."
                  className="h-10 w-full rounded-lg border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-sm text-[#2f2a46] ring-[#3525cd]/20 outline-none focus:ring"
                />
              </div>
            </div>
            <div className="hide-scrollbar max-h-[52vh] overflow-y-auto px-4 py-3">
              {indexedDocumentsQuery.isLoading ? (
                <LoadingState compact title="Loading indexed documents..." />
              ) : indexedDocumentsQuery.isError ? (
                <ErrorState
                  compact
                  error={indexedDocumentsQuery.error}
                  description={getApiErrorMessage(indexedDocumentsQuery.error)}
                  onRetry={() => {
                    void indexedDocumentsQuery.refetch();
                  }}
                />
              ) : indexedDocuments.length === 0 ? (
                <EmptyState
                  compact
                  title="No indexed documents available. Upload and index documents first."
                  action={
                    <Link
                      href="/documents"
                      className="text-sm font-semibold text-[#3525cd] hover:underline"
                    >
                      Go to documents upload
                    </Link>
                  }
                />
              ) : searchableIndexedDocuments.length === 0 ? (
                <EmptyState
                  compact
                  title="No documents match your search."
                  description="Try a different filename or file type."
                />
              ) : (
                <ul className="space-y-2">
                  {pagedSearchableIndexedDocuments.map((document) => (
                    <DocumentSelectorItem
                      key={document.document_id}
                      document={document}
                      checked={filteredSelectedDocumentIds.includes(
                        document.document_id,
                      )}
                      onToggle={() => toggleDocument(document.document_id)}
                    />
                  ))}
                </ul>
              )}
            </div>
            {searchableIndexedDocuments.length > CONTEXT_MODAL_PAGE_SIZE ? (
              <div className="flex items-center justify-between border-t border-[#ece8f7] px-4 py-3 text-xs text-[#5f5a74]">
                <p>
                  Showing {contextPageStartIndex}-{contextPageEndIndex} of{" "}
                  {searchableIndexedDocuments.length}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setContextPage((previous) => Math.max(1, previous - 1));
                    }}
                    disabled={boundedContextPage <= 1}
                    className="rounded border border-[#d2cee6] px-2 py-1 font-semibold text-[#3525cd] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Previous
                  </button>
                  <span className="font-mono text-[11px] text-[#4f4b63]">
                    Page {boundedContextPage} of {contextPageCount}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setContextPage((previous) =>
                        Math.min(contextPageCount, previous + 1),
                      );
                    }}
                    disabled={boundedContextPage >= contextPageCount}
                    className="rounded border border-[#d2cee6] px-2 py-1 font-semibold text-[#3525cd] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Next
                  </button>
                </div>
              </div>
            ) : null}
            <div className="flex items-center justify-between border-t border-[#e2dff1] bg-[#faf9ff] px-4 py-3">
              <p className="text-xs text-[#5f5a74]">
                {filteredSelectedDocumentIds.length > 0
                  ? `${filteredSelectedDocumentIds.length} document(s) selected`
                  : "No specific documents selected. All indexed documents will be used."}
              </p>
              <button
                type="button"
                onClick={() => {
                  setIsContextModalOpen(false);
                  setContextSearchQuery("");
                  setContextPage(1);
                }}
                className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function DocumentSelectorItem({
  document,
  checked,
  onToggle,
}: {
  document: DocumentListItemResponse;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <li>
      <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-sm text-[#2f2a46] transition hover:border-[#c9c3e6] hover:bg-white">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="mt-0.5 accent-[#3525cd]"
        />
        <span className="min-w-0">
          <span className="block truncate font-semibold">
            {document.filename}
          </span>
          <span className="mt-1 block text-xs text-[#6a6780]">
            {document.chunk_count} chunks • updated{" "}
            {formatDate(document.updated_at)}
          </span>
        </span>
      </label>
    </li>
  );
}
