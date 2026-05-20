"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  createAgentRun,
  getAgentRun,
  type AgentRunCreateRequest,
  type AgentRunCreateResponse,
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
import { listDocuments, type DocumentListItemResponse } from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { buildPipelineExplorerHref, normalizePipelineRunType, type PipelineRunType } from "@/lib/pipeline-links";
import { loadSettingsPreferences } from "@/lib/settings-preferences";
import { useAuthSession } from "@/lib/use-auth-session";

const DRAFT_SESSION_KEY = "__draft__";

function parsePositiveIntegerEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

const MAX_INDEXED_DOCS = parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_MAX_INDEXED_DOCS, 200);
const SESSION_LIST_LIMIT = parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_SESSION_LIST_LIMIT, 50);
const MIN_TOP_K = parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_MIN, 1);
const MAX_TOP_K = parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_MAX, 20);
const DEFAULT_TOP_K = Math.min(
  Math.max(parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_DEFAULT, 5), MIN_TOP_K),
  MAX_TOP_K,
);
const AGENT_RUN_POLL_INTERVAL_MS = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_AGENT_RUN_POLL_INTERVAL_MS,
  3_000,
);
const AGENTIC_CHAT_ENABLED = process.env.NEXT_PUBLIC_CHAT_AGENTIC_ENABLED !== "false";
const DEFAULT_AGENTIC_MODE = process.env.NEXT_PUBLIC_CHAT_AGENTIC_DEFAULT === "true";
const CHAT_SETTINGS_STORAGE_KEY = "rudix.chat.settings.v1";
const CHAT_FEEDBACK_ENABLED = process.env.NEXT_PUBLIC_CHAT_FEEDBACK_ENABLED === "true";
const STREAMING_PLACEHOLDER_ENABLED = process.env.NEXT_PUBLIC_CHAT_STREAMING_ENABLED === "true";

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

function confidenceBadgeClass(confidence: ChatQueryResponse["confidence_category"]): string {
  if (confidence === "high") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (confidence === "medium") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
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
  return status === "completed" || status === "failed" || status === "cancelled";
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

function toConfidenceCategory(value: unknown, score: number): "low" | "medium" | "high" {
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

function normalizeAgentCitation(citation: Record<string, unknown>): ChatCitationResponse {
  return {
    document_id: toStringOrNull(citation.document_id) ?? "",
    chunk_id: toStringOrNull(citation.chunk_id) ?? "",
    filename: toStringOrNull(citation.filename),
    page_number: toNumberOrNull(citation.page_number),
    score: toNumberOrNull(citation.score),
    similarity_score: toNumberOrNull(citation.similarity_score),
    rerank_score: toNumberOrNull(citation.rerank_score),
    rerank_rank: toNumberOrNull(citation.rerank_rank),
    text_snippet: toStringOrNull(citation.text_snippet) ?? toStringOrNull(citation.snippet),
  };
}

function readDebugString(debug: ChatDebugResponse | null, key: string): string | null {
  if (!debug) {
    return null;
  }
  const value = (debug as Record<string, unknown>)[key];
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function getChatRunType(debug: ChatDebugResponse | null): PipelineRunType {
  const debugRunType = normalizePipelineRunType(
    readDebugString(debug, "pipeline_type") ?? readDebugString(debug, "run_type"),
  );
  return debugRunType ?? "chat.answer";
}

function buildChatPipelineHref(response: ChatTurn["response"]): string | null {
  const chatMessageId = response.message_id.trim();
  const runId = readDebugString(response.debug, "pipeline_run_id") ?? readDebugString(response.debug, "run_id");
  const runType = getChatRunType(response.debug);
  const firstCitationDocumentId = response.citations.find((citation) => Boolean(citation.document_id))?.document_id ?? null;

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

function toTurnResponseFromQuery(response: ChatQueryResponse): ChatTurn["response"] {
  return {
    message_id: response.message_id,
    answer: response.answer,
    confidence_score: response.confidence_score,
    confidence_category: response.confidence_category,
    not_found: response.not_found,
    debug: response.debug ?? null,
    citations: response.citations,
    created_at: response.created_at,
    agent_run_id: null,
    agent_run_status: null,
    agent_run_error: null,
    agent_mode: null,
  };
}

function toTurnResponseFromHistoryMessage(message: ChatSessionMessageResponse): ChatTurn["response"] {
  return {
    message_id: message.message_id,
    answer: message.content,
    confidence_score: typeof message.confidence_score === "number" ? message.confidence_score : 0,
    confidence_category: message.confidence_category ?? "low",
    not_found: false,
    debug: null,
    citations: message.citations,
    created_at: message.created_at,
    agent_run_id: null,
    agent_run_status: null,
    agent_run_error: null,
    agent_mode: null,
  };
}

function toTurnResponseFromAgentRun(run: AgentRunCreateResponse["run"]): ChatTurn["response"] {
  const outcome = run.outcome ?? null;
  const confidence = toObject(outcome?.confidence ?? {});
  const score = toNumberOrNull(confidence.score) ?? 0;
  const answer =
    toStringOrNull(outcome?.answer) ??
    toStringOrNull(run.error?.message) ??
    "No answer was generated.";

  const citations = Array.isArray(outcome?.citations)
    ? outcome.citations.map((citation) => normalizeAgentCitation(toObject(citation)))
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

function buildTurnsFromSessionMessages(messages: ChatSessionMessageResponse[]): ChatTurn[] {
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
  window.history.replaceState(window.history.state, "", `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`);
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
      ? parsed.selectedDocumentIds.filter((value): value is string => typeof value === "string")
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

function CitationPanel({ citations }: { citations: ChatCitationResponse[] }) {
  if (citations.length === 0) {
    return (
      <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-xs text-[#68647b]">
        No citations were returned for this answer.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {citations.map((citation) => (
        <li
          key={`${citation.document_id}:${citation.chunk_id}`}
          className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3"
        >
          <details open>
            <summary className="cursor-pointer list-none text-xs font-semibold text-[#3f3b58]">
              <span>
                {citation.filename ?? "Unknown document"}
                {citation.page_number ? ` • page ${citation.page_number}` : ""}
                {" • "}
                score {formatScore(citation.score)}
              </span>
            </summary>
            <div className="mt-2 space-y-2">
              <p className="text-sm whitespace-pre-wrap break-words text-[#2f2a46]">
                {citation.text_snippet ?? "Snippet unavailable."}
              </p>
              <dl className="grid grid-cols-2 gap-2 text-xs text-[#5f5a74]">
                <div>
                  <dt className="font-semibold text-[#4f4b63]">Similarity</dt>
                  <dd>{formatScore(citation.similarity_score)}</dd>
                </div>
                <div>
                  <dt className="font-semibold text-[#4f4b63]">Rerank score</dt>
                  <dd>{formatScore(citation.rerank_score)}</dd>
                </div>
                <div>
                  <dt className="font-semibold text-[#4f4b63]">Rerank rank</dt>
                  <dd>{citation.rerank_rank ?? "N/A"}</dd>
                </div>
                <div>
                  <dt className="font-semibold text-[#4f4b63]">Chunk ID</dt>
                  <dd className="break-all">{citation.chunk_id}</dd>
                </div>
              </dl>
              {citation.document_id ? (
                <Link
                  href={`/documents/${encodeURIComponent(citation.document_id)}?chunk_id=${encodeURIComponent(citation.chunk_id)}&back=${encodeURIComponent("/chat")}`}
                  className="inline-flex rounded border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
                >
                  Open document detail
                </Link>
              ) : null}
            </div>
          </details>
        </li>
      ))}
    </ul>
  );
}

export function ChatPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { state } = useAuthSession();
  const lastAppliedSessionIdRef = useRef<string | null>(null);
  const lastAppliedDocumentIdRef = useRef<string | null>(null);
  const didLoadPersistedSettingsRef = useRef(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>(() =>
    readPersistedChatSettings()?.selectedDocumentIds ?? [],
  );
  const [topK, setTopK] = useState(DEFAULT_TOP_K);
  const [rerank, setRerank] = useState(true);
  const [agenticMode, setAgenticMode] = useState(DEFAULT_AGENTIC_MODE);
  const [threadsBySession, setThreadsBySession] = useState<Record<string, ChatTurn[]>>({});
  const [selectedResponseMessageId, setSelectedResponseMessageId] = useState<string | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [submitRequestId, setSubmitRequestId] = useState<string | null>(null);
  const [feedbackByMessageId, setFeedbackByMessageId] = useState<Record<string, "up" | "down">>({});

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
      const loadedCount = allPages.reduce((total, page) => total + page.items.length, 0);
      if (loadedCount >= lastPage.total) {
        return undefined;
      }
      return loadedCount;
    },
  });

  const sessions = useMemo(() => {
    const allItems = sessionsQuery.data?.pages.flatMap((page) => page.items) ?? [];
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
    activeSessionId !== null && (threadsBySession[activeThreadKey(activeSessionId)] ?? []).length === 0;

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
    queryFn: () =>
      listChatSessionMessages(activeSessionId ?? "", {
        limit: 500,
        offset: 0,
      }),
    enabled: shouldLoadActiveSessionHistory,
  });

  useEffect(() => {
    if (!activeSessionId || !sessionMessagesQuery.data) {
      return;
    }

    const threadKey = activeThreadKey(activeSessionId);
    const hydratedTurns = buildTurnsFromSessionMessages(sessionMessagesQuery.data.items);
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
  }, [activeSessionId, sessionMessagesQuery.data]);

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
    () => indexedDocumentsQuery.data?.items.filter((item) => item.status === "indexed") ?? [],
    [indexedDocumentsQuery.data?.items],
  );

  const indexedDocumentIdSet = useMemo(
    () => new Set(indexedDocuments.map((item) => item.document_id)),
    [indexedDocuments],
  );

  const filteredSelectedDocumentIds = useMemo(
    () => selectedDocumentIds.filter((documentId) => indexedDocumentIdSet.has(documentId)),
    [selectedDocumentIds, indexedDocumentIdSet],
  );

  const hasIndexedDocuments = indexedDocuments.length > 0;

  useEffect(() => {
    const persisted = readPersistedChatSettings();
    if (persisted) {
      setTopK(persisted.topK);
      setRerank(persisted.rerank);
      setSelectedDocumentIds(persisted.selectedDocumentIds);
      setAgenticMode(persisted.agenticMode === true);
    }
    didLoadPersistedSettingsRef.current = true;
  }, []);

  useEffect(() => {
    if (!didLoadPersistedSettingsRef.current || typeof window === "undefined") {
      return;
    }
    const payload: PersistedChatSettings = {
      topK,
      rerank,
      selectedDocumentIds: filteredSelectedDocumentIds,
      agenticMode,
    };
    window.localStorage.setItem(CHAT_SETTINGS_STORAGE_KEY, JSON.stringify(payload));
  }, [agenticMode, filteredSelectedDocumentIds, rerank, topK]);

  useEffect(() => {
    const documentIdFromQuery = searchParams.get("document_id");
    if (!documentIdFromQuery) {
      lastAppliedDocumentIdRef.current = null;
      return;
    }
    if (lastAppliedDocumentIdRef.current === documentIdFromQuery) {
      return;
    }
    if (!indexedDocumentIdSet.has(documentIdFromQuery)) {
      return;
    }
    setSelectedDocumentIds((previous) => {
      if (previous.includes(documentIdFromQuery)) {
        return previous;
      }
      return [documentIdFromQuery, ...previous.filter((value) => indexedDocumentIdSet.has(value))];
    });
    lastAppliedDocumentIdRef.current = documentIdFromQuery;
  }, [indexedDocumentIdSet, searchParams]);

  useEffect(() => {
    if (filteredSelectedDocumentIds.length === selectedDocumentIds.length) {
      return;
    }
    setSelectedDocumentIds(filteredSelectedDocumentIds);
  }, [filteredSelectedDocumentIds, selectedDocumentIds.length]);

  const activeSession = sessions.find((item) => item.session_id === activeSessionId) ?? null;
  const thread = threadsBySession[activeThreadKey(activeSessionId)] ?? [];
  const selectedCitationTurn =
    thread.find((turn) => turn.response.message_id === selectedResponseMessageId) ??
    thread[thread.length - 1] ??
    null;
  const selectedCitationPipelineHref = selectedCitationTurn
    ? buildChatPipelineHref(selectedCitationTurn.response)
    : null;
  const selectedAgentRunId = selectedCitationTurn?.response.agent_run_id ?? null;
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

  useEffect(() => {
    if (thread.length === 0) {
      if (selectedResponseMessageId !== null) {
        setSelectedResponseMessageId(null);
      }
      return;
    }
    const hasSelected = thread.some((turn) => turn.response.message_id === selectedResponseMessageId);
    if (hasSelected) {
      return;
    }
    setSelectedResponseMessageId(thread[thread.length - 1].response.message_id);
  }, [selectedResponseMessageId, thread]);

  const queryMutation = useMutation({
    mutationFn: (payload: ChatQueryRequest) => queryChat(payload),
    onSuccess: async (response, payload) => {
      const nextSessionId = response.chat_session_id;
      const previousThreadKey = activeThreadKey(payload.chat_session_id ?? null);
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

      setActiveSessionId(nextSessionId);
      setSelectedResponseMessageId(nextTurn.response.message_id);
      replaceSessionParamInUrl(nextSessionId);
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

  const createSessionMutation = useMutation({
    mutationFn: () => createChatSession(),
  });

  const isComposerDisabled =
    queryMutation.isPending ||
    agentRunMutation.isPending ||
    createSessionMutation.isPending ||
    question.trim().length === 0 ||
    indexedDocumentsQuery.isLoading ||
    indexedDocumentsQuery.isError ||
    !hasIndexedDocuments;

  const listForbidden = isForbiddenError(indexedDocumentsQuery.error) || isForbiddenError(sessionsQuery.error);
  const composerError = queryMutation.error ?? agentRunMutation.error ?? createSessionMutation.error;
  const composerForbidden = isForbiddenError(composerError);
  const showDebugDetails = isAdminLikeRole(state.session?.role ?? null) || Boolean(settingsPreferencesQuery.data?.developerMode);

  function toggleDocument(documentId: string) {
    setSelectedDocumentIds((previous) => {
      const validPrevious = previous.filter((value) => indexedDocumentIdSet.has(value));
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

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitQuestion();
  }

  async function submitQuestion() {
    const trimmedQuestion = question.trim();
    await submitQuestionText(trimmedQuestion, true);
  }

  async function submitQuestionText(questionText: string, clearComposerOnSubmit: boolean) {
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
      const payload: AgentRunCreateRequest = {
        agentic_mode: true,
        request: {
          objective: trimmedQuestion,
          mode: "answer",
          question: trimmedQuestion,
          document_ids: filteredSelectedDocumentIds.length > 0 ? filteredSelectedDocumentIds : undefined,
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
      } catch (error) {
        setSubmitRequestId(extractRequestIdFromError(error));
        if (clearComposerOnSubmit) {
          setQuestion(trimmedQuestion);
        }
        setPendingQuestion(null);
      }
      return;
    }

    let targetSessionId = activeSessionId;
    if (!targetSessionId) {
      try {
        const createdSession = await createSessionMutation.mutateAsync();
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

    queryMutation.mutate({
      question: trimmedQuestion,
      chat_session_id: targetSessionId,
      document_ids:
        filteredSelectedDocumentIds.length > 0
          ? filteredSelectedDocumentIds
          : undefined,
      top_k: topK,
      rerank,
    }, {
      onError: (error) => {
        setSubmitRequestId(extractRequestIdFromError(error));
        if (clearComposerOnSubmit) {
          setQuestion(trimmedQuestion);
        }
        setPendingQuestion(null);
      },
    });
  }

  if (listForbidden) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Chat access is restricted"
          description="Your role does not have permission to query documents in this organization."
          requestId={extractRequestIdFromError(indexedDocumentsQuery.error ?? sessionsQuery.error)}
          compact={false}
        />
      </section>
    );
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Chat</p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">Document-grounded Q&A</h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Ask questions against indexed documents with configurable retrieval and rerank settings.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
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

      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)_340px]">
        <aside className="space-y-4">
          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Sessions</h2>
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
                        className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                          session.session_id === activeSessionId
                            ? "border-[#3525cd] bg-[#f4f2ff] text-[#2f2a46]"
                            : "border-[#e4e1f2] bg-white text-[#4f4b63] hover:bg-[#faf9ff]"
                        }`}
                      >
                        <p className="font-semibold">{session.title ?? "Untitled session"}</p>
                        <p className="mt-1 text-xs">
                          {session.message_count} messages • updated {formatDate(session.updated_at)}
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
              <EmptyState compact title="No sessions yet. Ask your first question to start one." />
            )}
          </section>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Retrieval settings</h2>
            <label className="mb-3 flex items-start gap-2 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-sm text-[#2f2a46]">
              <input
                type="checkbox"
                checked={agenticMode}
                disabled={!AGENTIC_CHAT_ENABLED}
                onChange={(event) => setAgenticMode(event.target.checked)}
                className="mt-0.5"
              />
              <span>
                Agentic mode
                <span className="mt-1 block text-xs text-[#6a6780]">
                  Run plan-act-observe execution with a step timeline and explicit budget handling.
                </span>
                {!AGENTIC_CHAT_ENABLED ? (
                  <span className="mt-1 block text-xs text-[#8a4762]">
                    Agentic mode is disabled for this deployment.
                  </span>
                ) : null}
              </span>
            </label>
            <label className="mb-3 grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
              Top K
              <input
                type="number"
                min={MIN_TOP_K}
                max={MAX_TOP_K}
                value={topK}
                onChange={(event) => {
                  const parsed = Number.parseInt(event.target.value, 10);
                  if (!Number.isFinite(parsed)) {
                    return;
                  }
                  setTopK(Math.min(MAX_TOP_K, Math.max(MIN_TOP_K, parsed)));
                }}
                className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
              />
            </label>

            <label className="flex items-start gap-2 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-sm text-[#2f2a46]">
              <input
                type="checkbox"
                checked={rerank}
                onChange={(event) => setRerank(event.target.checked)}
                className="mt-0.5"
              />
              <span>
                Enable rerank
                <span className="mt-1 block text-xs text-[#6a6780]">
                  Improves answer quality with an additional ranking pass.
                </span>
              </span>
            </label>
          </section>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Document selector</h2>
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
                <Link href="/documents" className="text-sm font-semibold text-[#3525cd] hover:underline">
                  Go to documents upload
                </Link>
                }
              />
            ) : (
              <ul className="max-h-72 space-y-2 overflow-auto pr-1">
                {indexedDocuments.map((document) => (
                  <DocumentSelectorItem
                    key={document.document_id}
                    document={document}
                    checked={filteredSelectedDocumentIds.includes(document.document_id)}
                    onToggle={() => toggleDocument(document.document_id)}
                  />
                ))}
              </ul>
            )}
          </section>
        </aside>

        <section className="space-y-4">
          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Ask a question</h2>
            <form onSubmit={handleSubmit} className="space-y-3">
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                    event.preventDefault();
                    void submitQuestion();
                  }
                }}
                rows={4}
                placeholder="Ask a question about your selected documents..."
                disabled={!hasIndexedDocuments}
                className="w-full rounded-lg border border-[#d2cee6] px-3 py-2 text-sm text-[#2f2a46] outline-none ring-[#3525cd]/20 focus:ring"
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-[#6a6780]">
                  {!hasIndexedDocuments
                    ? "Chat is disabled until at least one document is indexed."
                    : filteredSelectedDocumentIds.length > 0
                    ? `${filteredSelectedDocumentIds.length} document(s) selected`
                    : "All indexed accessible documents are in scope"}
                  {AGENTIC_CHAT_ENABLED && agenticMode ? " • agentic mode enabled" : ""}
                </p>
                <button
                  type="submit"
                  disabled={isComposerDisabled}
                  className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {createSessionMutation.isPending
                    ? "Starting session..."
                    : agentRunMutation.isPending
                      ? "Running agent..."
                    : queryMutation.isPending
                      ? "Generating answer..."
                      : "Ask"}
                </button>
              </div>
              {thread.length > 0 ? (
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => {
                      const latestTurn = thread[thread.length - 1];
                      if (!latestTurn) {
                        return;
                      }
                      void submitQuestionText(latestTurn.question, false);
                    }}
                    disabled={
                      queryMutation.isPending ||
                      agentRunMutation.isPending ||
                      createSessionMutation.isPending ||
                      !hasIndexedDocuments
                    }
                    className="rounded-md border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Regenerate last answer
                  </button>
                </div>
              ) : null}
              <p className="text-xs text-[#6a6780]">Shortcut: Ctrl/Cmd + Enter to submit.</p>
            </form>
          </section>

          {composerForbidden ? (
            <ForbiddenState
              compact
              title="Query is not allowed"
              description="You do not have permission to query the selected documents in this organization."
              requestId={extractRequestIdFromError(composerError)}
            />
          ) : null}

          {composerError && !composerForbidden ? (
            <ErrorState
              title="Unable to complete the query."
              error={composerError}
              description={getApiErrorMessage(composerError)}
              requestId={submitRequestId}
            />
          ) : null}

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Conversation</h2>
            <div className="mb-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-xs text-[#5f5a74]">
              {activeSession ? (
                <p>
                  Session: <span className="font-semibold text-[#2f2a46]">{activeSession.title ?? "Untitled session"}</span>
                  {" • "}
                  {activeSession.message_count} messages
                  {" • "}
                  updated {formatDate(activeSession.updated_at)}
                </p>
              ) : (
                <p>
                  New chat draft. Start with a question to create a session.
                </p>
              )}
            </div>
            {sessionMessagesQuery.isLoading && activeSession && thread.length === 0 && activeSession.message_count > 0 ? (
              <LoadingState compact title="Loading session history..." />
            ) : null}

            {sessionMessagesQuery.isError && activeSession && thread.length === 0 && activeSession.message_count > 0 ? (
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

            {thread.length === 0 && !pendingQuestion && !sessionMessagesQuery.isLoading ? (
              <EmptyState compact title="No messages yet. Submit a question to start the conversation." />
            ) : (
              <ul className="space-y-4">
                {thread.map((turn) => (
                  <li key={turn.response.message_id} className="space-y-2">
                    <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
                      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Question</p>
                      <p className="text-sm whitespace-pre-wrap break-words text-[#2f2a46]">{turn.question}</p>
                    </article>

                    <article className="rounded-xl border border-[#d7d4e8] bg-white p-3">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <p className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Answer</p>
                        <span className={confidenceBadgeClass(turn.response.confidence_category)}>
                          Confidence {formatPercent(turn.response.confidence_score)}
                        </span>
                        {turn.response.agent_run_status ? (
                          <span className={agentRunStatusClass(turn.response.agent_run_status)}>
                            Agent run {turn.response.agent_run_status}
                          </span>
                        ) : null}
                        <span className="text-xs text-[#6a6780]">{formatDate(turn.response.created_at)}</span>
                        <button
                          type="button"
                          onClick={() => setSelectedResponseMessageId(turn.response.message_id)}
                          className={`ml-auto rounded border px-2 py-1 text-[11px] font-semibold ${
                            selectedCitationTurn?.response.message_id === turn.response.message_id
                              ? "border-[#3525cd] bg-[#f4f2ff] text-[#2f2a46]"
                              : "border-[#d2cee6] text-[#3e376f] hover:bg-[#f5f3ff]"
                          }`}
                        >
                          View context
                        </button>
                      </div>

                      {turn.response.confidence_category === "low" && !turn.response.not_found ? (
                        <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                          Low confidence warning: validate this answer against the cited source text.
                        </p>
                      ) : null}

                      {turn.response.not_found ? (
                        <div className="space-y-2">
                          <p className="rounded-lg border border-[#d2cee6] bg-[#faf9ff] px-3 py-2 text-sm break-words text-[#2f2a46]">
                            No grounded answer was found in the selected documents.
                          </p>
                          <p className="text-xs text-[#6a6780]">
                            Try refining your question, changing document scope, or adjusting retrieval settings.
                          </p>
                        </div>
                      ) : (
                        <p className="text-sm whitespace-pre-wrap break-words text-[#2f2a46]">
                          {turn.response.answer}
                        </p>
                      )}
                      {turn.response.agent_run_error ? (
                        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
                          Agent stop reason: {turn.response.agent_run_error.message}
                        </p>
                      ) : null}
                      {CHAT_FEEDBACK_ENABLED ? (
                        <div className="mt-3 flex items-center gap-2">
                          <span className="text-xs text-[#6a6780]">Was this answer helpful?</span>
                          <button
                            type="button"
                            aria-label="Mark answer helpful"
                            onClick={() => {
                              setFeedbackByMessageId((previous) => {
                                const next = { ...previous };
                                if (next[turn.response.message_id] === "up") {
                                  delete next[turn.response.message_id];
                                } else {
                                  next[turn.response.message_id] = "up";
                                }
                                return next;
                              });
                            }}
                            className={`rounded border px-2 py-1 text-xs ${feedbackByMessageId[turn.response.message_id] === "up" ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-[#d2cee6] text-[#3e376f] hover:bg-[#f5f3ff]"}`}
                          >
                            Helpful
                          </button>
                          <button
                            type="button"
                            aria-label="Mark answer not helpful"
                            onClick={() => {
                              setFeedbackByMessageId((previous) => {
                                const next = { ...previous };
                                if (next[turn.response.message_id] === "down") {
                                  delete next[turn.response.message_id];
                                } else {
                                  next[turn.response.message_id] = "down";
                                }
                                return next;
                              });
                            }}
                            className={`rounded border px-2 py-1 text-xs ${feedbackByMessageId[turn.response.message_id] === "down" ? "border-rose-300 bg-rose-50 text-rose-800" : "border-[#d2cee6] text-[#3e376f] hover:bg-[#f5f3ff]"}`}
                          >
                            Not helpful
                          </button>
                        </div>
                      ) : null}
                    </article>
                  </li>
                ))}
                {pendingQuestion ? (
                  <li className="space-y-2">
                    <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
                      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Question</p>
                      <p className="text-sm whitespace-pre-wrap break-words text-[#2f2a46]">{pendingQuestion}</p>
                    </article>
                    <article className="rounded-xl border border-[#d7d4e8] bg-white p-3">
                      <p className="text-sm text-[#68647b]">
                        {STREAMING_PLACEHOLDER_ENABLED ? "Streaming response..." : "Generating answer..."}
                      </p>
                    </article>
                  </li>
                ) : null}
              </ul>
            )}
          </section>
        </section>

        <aside className="space-y-4 xl:sticky xl:top-4 xl:self-start">
          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Context & citations</h2>
            {!selectedCitationTurn ? (
              <p className="text-sm text-[#68647b]">
                Select an answer in the conversation to inspect citations and retrieval context.
              </p>
            ) : (
              <div className="space-y-3">
                <div className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3">
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Selected answer</p>
                  <p className="text-xs text-[#5f5a74]">
                    Confidence {formatPercent(selectedCitationTurn.response.confidence_score)}
                    {" • "}
                    {formatDate(selectedCitationTurn.response.created_at)}
                  </p>
                  <p className="mt-2 text-sm text-[#2f2a46]">{selectedCitationTurn.question}</p>
                  {selectedCitationPipelineHref ? (
                    <Link
                      href={selectedCitationPipelineHref}
                      className="mt-2 inline-flex rounded border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
                    >
                      View pipeline run
                    </Link>
                  ) : null}
                </div>
                {selectedCitationTurn.response.not_found ? (
                  <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-xs text-[#68647b]">
                    No citations are shown because the assistant did not find grounded evidence for this response.
                  </p>
                ) : (
                  <CitationPanel citations={selectedCitationTurn.response.citations} />
                )}

                {showDebugDetails ? (
                  <section className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3">
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                      Retrieval debug
                    </h3>
                    {selectedCitationTurn.response.debug ? (
                      <div className="space-y-2 text-xs text-[#4f4b63]">
                        <dl className="grid grid-cols-2 gap-2">
                          <div>
                            <dt className="font-semibold">retrieval_count</dt>
                            <dd>{selectedCitationTurn.response.debug.retrieval_count}</dd>
                          </div>
                          <div>
                            <dt className="font-semibold">selected_count</dt>
                            <dd>{selectedCitationTurn.response.debug.selected_count}</dd>
                          </div>
                          <div>
                            <dt className="font-semibold">rerank_applied</dt>
                            <dd>{selectedCitationTurn.response.debug.rerank_applied ? "true" : "false"}</dd>
                          </div>
                          <div>
                            <dt className="font-semibold">embedding_model</dt>
                            <dd>{selectedCitationTurn.response.debug.embedding_model ?? "N/A"}</dd>
                          </div>
                          <div className="col-span-2">
                            <dt className="font-semibold">llm_model</dt>
                            <dd>{selectedCitationTurn.response.debug.llm_model ?? "N/A"}</dd>
                          </div>
                        </dl>
                        <div>
                          <p className="mb-1 font-semibold">latencies_ms</p>
                          {Object.keys(selectedCitationTurn.response.debug.latencies_ms).length === 0 ? (
                            <p className="text-[#6a6780]">No latency details available.</p>
                          ) : (
                            <ul className="space-y-1">
                              {Object.entries(selectedCitationTurn.response.debug.latencies_ms).map(([key, value]) => (
                                <li key={key} className="flex items-center justify-between gap-2 rounded border border-[#ebe8f7] px-2 py-1">
                                  <span>{key}</span>
                                  <span>{value} ms</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-[#6a6780]">Debug details are unavailable for this message.</p>
                    )}
                  </section>
                ) : null}

                <section className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3">
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                    Agent timeline
                  </h3>
                  {!selectedAgentRunId ? (
                    <EmptyState
                      compact
                      title="No agent run for this answer."
                      description="Enable agentic mode and ask a question to inspect step timeline details."
                    />
                  ) : selectedAgentRunQuery.isLoading ? (
                    <LoadingState compact title="Loading run timeline..." />
                  ) : selectedAgentRunQuery.isError ? (
                    <ErrorState
                      compact
                      title="Unable to load agent timeline"
                      error={selectedAgentRunQuery.error}
                      description={getApiErrorMessage(selectedAgentRunQuery.error)}
                      requestId={extractRequestIdFromError(selectedAgentRunQuery.error)}
                      onRetry={() => {
                        void selectedAgentRunQuery.refetch();
                      }}
                    />
                  ) : selectedAgentRunQuery.data ? (
                    <div className="space-y-2 text-xs text-[#4f4b63]">
                      <div className="flex flex-wrap items-center gap-2 rounded border border-[#ebe8f7] px-2 py-2">
                        <span className={agentRunStatusClass(selectedAgentRunQuery.data.status)}>
                          {selectedAgentRunQuery.data.status}
                        </span>
                        <span>run {selectedAgentRunQuery.data.run_id}</span>
                      </div>
                      <dl className="grid grid-cols-2 gap-2 rounded border border-[#ebe8f7] px-2 py-2">
                        <div>
                          <dt className="font-semibold">Max steps</dt>
                          <dd>{String(selectedAgentRunQuery.data.budget.max_steps ?? selectedAgentRunQuery.data.max_steps ?? "N/A")}</dd>
                        </div>
                        <div>
                          <dt className="font-semibold">Steps used</dt>
                          <dd>{selectedAgentRunQuery.data.steps.length}</dd>
                        </div>
                        <div>
                          <dt className="font-semibold">Max tool calls</dt>
                          <dd>{String(selectedAgentRunQuery.data.budget.max_tool_calls ?? "N/A")}</dd>
                        </div>
                        <div>
                          <dt className="font-semibold">Tool calls used</dt>
                          <dd>{selectedAgentRunQuery.data.tool_calls.length}</dd>
                        </div>
                      </dl>
                      {selectedAgentRunQuery.data.error_message ? (
                        <p className="rounded border border-rose-200 bg-rose-50 px-2 py-2 text-rose-800">
                          Stop reason: {selectedAgentRunQuery.data.error_message}
                        </p>
                      ) : null}
                      {selectedAgentRunQuery.data.steps.length === 0 ? (
                        <EmptyState compact title="No timeline steps were persisted." />
                      ) : (
                        <ol className="space-y-1">
                          {selectedAgentRunQuery.data.steps.map((step) => (
                            <li key={step.step_id} className="rounded border border-[#ebe8f7] px-2 py-2">
                              <p className="font-semibold text-[#3f3b58]">
                                {step.sequence}. {step.step_name}
                              </p>
                              <p className="text-[#6a6780]">
                                status {step.status}
                                {step.duration_ms !== null ? ` • ${step.duration_ms} ms` : ""}
                              </p>
                              {step.error_message ? (
                                <p className="mt-1 text-rose-700">{step.error_message}</p>
                              ) : null}
                            </li>
                          ))}
                        </ol>
                      )}
                    </div>
                  ) : (
                    <EmptyState compact title="Run detail unavailable." />
                  )}
                </section>
              </div>
            )}
          </section>
        </aside>
      </div>
    </section>
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
      <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-sm text-[#2f2a46]">
        <input type="checkbox" checked={checked} onChange={onToggle} className="mt-0.5" />
        <span>
          <span className="block font-semibold">{document.filename}</span>
          <span className="mt-1 block text-xs text-[#6a6780]">
            {document.chunk_count} chunks • updated {formatDate(document.updated_at)}
          </span>
        </span>
      </label>
    </li>
  );
}
