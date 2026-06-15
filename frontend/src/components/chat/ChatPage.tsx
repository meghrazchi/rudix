"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { DocumentPreviewModal } from "@/components/chat/DocumentPreviewModal";
import { FeedbackModal } from "@/components/chat/FeedbackModal";
import { ChatResponseLoadingState } from "@/components/chat/ChatResponseLoadingState";
import { ShareModal } from "@/components/chat/ShareModal";
import { AnswerShareModal } from "@/components/chat/AnswerShareModal";
import { ConflictWarningCard } from "@/components/chat/ConflictIndicators";
import { ChatComposer } from "@/components/chat/ChatComposer";
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
  deleteChatSession,
  listChatSessionMessages,
  listChatSessions,
  queryChat,
  type ChatCitationResponse,
  type ChatConflictPairResponse,
  type ChatDebugResponse,
  type ChatSessionMessageResponse,
  type ChatQueryRequest,
  type ChatQueryResponse,
} from "@/lib/api/chat";
import {
  listDocuments,
  type DocumentListItemResponse,
} from "@/lib/api/documents";
import {
  listCollectionDocuments,
  listCollections,
} from "@/lib/api/collections";
import {
  listAvailableConnectorConnections,
  type ConnectorConnectionSummary,
} from "@/lib/api/connectors";
import {
  deleteMessageFeedback,
  listSessionFeedback,
  submitMessageFeedback,
  type FeedbackReason,
  type MessageFeedbackResponse,
} from "@/lib/api/feedback";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import {
  copyToClipboard,
  downloadMarkdown,
  formatAnswerAsMarkdown,
  formatTranscriptAsMarkdown,
  sanitizeFilename,
  type ExportTurn,
} from "@/lib/export-utils";
import {
  buildPipelineExplorerHref,
  normalizePipelineRunType,
  type PipelineRunType,
} from "@/lib/pipeline-links";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { loadSettingsPreferences } from "@/lib/settings-preferences";
import { useAuthSession } from "@/lib/use-auth-session";
import { useChatWebSocket } from "@/lib/use-chat-websocket";

const DRAFT_SESSION_KEY = "__draft__";

type ChatScopeMode = "all" | "collection" | "documents" | "connectors" | "none";
type AnswerLanguageMode =
  | "auto"
  | "same_as_question"
  | "en"
  | "de"
  | "es"
  | "fr";

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
const SCOPE_DOCUMENT_PICKER_LIMIT = 30;
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
const STREAMING_PLACEHOLDER_ENABLED =
  process.env.NEXT_PUBLIC_CHAT_STREAMING_ENABLED === "true";
const CHAT_WEBSOCKET_ENABLED =
  process.env.NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED === "true";

type PersistedChatSettings = {
  topK: number;
  rerank: boolean;
  selectedDocumentIds?: string[];
  agenticMode?: boolean;
  scopeMode?: ChatScopeMode;
  selectedCollectionIds?: string[];
  selectedConnectorConnectionIds?: string[];
  selectedProviderSourceIds?: string[];
  answerLanguage?: AnswerLanguageMode;
};

type ChatTurn = {
  question: string;
  response: {
    message_id: string;
    answer: string;
    confidence_score: number;
    confidence_category: "low" | "medium" | "high";
    not_found: boolean;
    citation_validation_failed: boolean;
    agreement_level: "full" | "partial" | "conflicting";
    conflict_detected: boolean;
    conflict_summary: string | null;
    conflicting_document_ids: string[];
    preferred_document_ids: string[];
    conflict_pairs: ChatConflictPairResponse[];
    debug: ChatDebugResponse | null;
    citations: ChatCitationResponse[];
    created_at: string;
    agent_run_id: string | null;
    agent_run_status: string | null;
    agent_run_error: AgentRunCreateResponse["run"]["error"] | null;
    agent_mode: AgentRuntimeMode | null;
    scope_label: string | null;
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

function confidenceBadgeClass(): string {
  return "inline-flex items-center gap-1 rounded-full border border-[#d7d4e8] bg-white px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
}

function conflictStatusLabel(
  status: "preferred" | "conflicting" | "neutral" | null | undefined,
): string | null {
  if (status === "preferred") {
    return "Preferred";
  }
  if (status === "conflicting") {
    return "Conflicting";
  }
  return null;
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
    start_offset: toNumberOrNull(citation.start_offset),
    end_offset: toNumberOrNull(citation.end_offset),
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
  scopeLabel: string | null = null,
): ChatTurn["response"] {
  return {
    message_id: response.message_id,
    answer: response.answer,
    confidence_score: response.confidence_score,
    confidence_category: response.confidence_category,
    not_found: response.not_found,
    citation_validation_failed: response.citation_validation_failed ?? false,
    agreement_level: response.agreement_level ?? "full",
    conflict_detected: response.conflict_detected ?? false,
    conflict_summary: response.conflict_summary ?? null,
    conflicting_document_ids: response.conflicting_document_ids ?? [],
    preferred_document_ids: response.preferred_document_ids ?? [],
    conflict_pairs: response.conflict_pairs ?? [],
    debug: response.debug ?? null,
    citations: response.citations ?? [],
    created_at: response.created_at,
    agent_run_id: null,
    agent_run_status: null,
    agent_run_error: null,
    agent_mode: null,
    scope_label: scopeLabel,
  };
}

function toTurnResponseFromHistoryMessage(
  message: ChatSessionMessageResponse,
): ChatTurn["response"] {
  const messageRecord = message as unknown as Record<string, unknown>;
  const agreementLevel =
    messageRecord.agreement_level === "partial" ||
    messageRecord.agreement_level === "conflicting"
      ? messageRecord.agreement_level
      : "full";
  const conflictDetected = Boolean(messageRecord.conflict_detected);
  const conflictSummary =
    typeof messageRecord.conflict_summary === "string"
      ? messageRecord.conflict_summary
      : null;
  const conflictingDocumentIds = Array.isArray(
    messageRecord.conflicting_document_ids,
  )
    ? messageRecord.conflicting_document_ids.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  const preferredDocumentIds = Array.isArray(
    messageRecord.preferred_document_ids,
  )
    ? messageRecord.preferred_document_ids.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  const conflictPairs = Array.isArray(messageRecord.conflict_pairs)
    ? messageRecord.conflict_pairs
        .map((pair) => {
          const record = pair as Record<string, unknown>;
          const documentIdA = toStringOrNull(record.document_id_a) ?? "";
          const documentIdB = toStringOrNull(record.document_id_b) ?? "";
          const topic = toStringOrNull(record.topic) ?? "";
          const severity =
            record.severity === "low" ||
            record.severity === "medium" ||
            record.severity === "high"
              ? record.severity
              : "medium";
          if (!documentIdA || !documentIdB || !topic) {
            return null;
          }
          return {
            document_id_a: documentIdA,
            document_id_b: documentIdB,
            topic,
            severity,
          };
        })
        .filter(
          (
            pair,
          ): pair is {
            document_id_a: string;
            document_id_b: string;
            topic: string;
            severity: "low" | "medium" | "high";
          } => pair !== null,
        )
    : [];

  return {
    message_id: message.message_id,
    answer: message.content,
    confidence_score:
      typeof message.confidence_score === "number"
        ? message.confidence_score
        : 0,
    confidence_category: message.confidence_category ?? "low",
    not_found: false,
    citation_validation_failed: false,
    agreement_level,
    conflict_detected,
    conflict_summary,
    conflicting_document_ids: conflictDetected ? conflictingDocumentIds : [],
    preferred_document_ids: conflictDetected ? preferredDocumentIds : [],
    conflict_pairs: conflictDetected ? conflictPairs : [],
    debug: null,
    citations: message.citations ?? [],
    created_at: message.created_at,
    agent_run_id: null,
    agent_run_status: null,
    agent_run_error: null,
    agent_mode: null,
    scope_label: null,
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
    citation_validation_failed: false,
    agreement_level: "full",
    conflict_detected: false,
    conflict_summary: null,
    conflicting_document_ids: [],
    preferred_document_ids: [],
    conflict_pairs: [],
    debug: null,
    citations,
    created_at: new Date().toISOString(),
    agent_run_id: run.run_id,
    agent_run_status: run.status,
    agent_run_error: run.error ?? null,
    agent_mode: outcome?.mode ?? null,
    scope_label: null,
  };
}

function toExportTurns(turns: ChatTurn[]): ExportTurn[] {
  return turns.map((t) => ({
    question: t.question,
    answer: t.response.answer,
    citations: t.response.citations,
    created_at: t.response.created_at,
  }));
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

    const validLanguageModes: AnswerLanguageMode[] = [
      "auto",
      "same_as_question",
      "en",
      "de",
      "es",
      "fr",
    ];
    const answerLanguage: AnswerLanguageMode = validLanguageModes.includes(
      parsed.answerLanguage as AnswerLanguageMode,
    )
      ? (parsed.answerLanguage as AnswerLanguageMode)
      : "auto";

    return {
      topK: storedTopK,
      rerank: parsed.rerank !== false,
      selectedDocumentIds: [],
      agenticMode: parsed.agenticMode === true,
      scopeMode: "all",
      selectedCollectionIds: [],
      selectedConnectorConnectionIds: [],
      selectedProviderSourceIds: [],
      answerLanguage,
    };
  } catch {
    return null;
  }
}

function getFileIcon(filename: string | null | undefined): string {
  if (!filename) return "draft";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "picture_as_pdf";
  if (["doc", "docx"].includes(ext)) return "description";
  if (["md", "txt"].includes(ext)) return "text_snippet";
  if (["xlsx", "xls"].includes(ext)) return "table_chart";
  if (["csv"].includes(ext)) return "dataset";
  if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext))
    return "image";
  if (["mp4", "mov", "avi", "webm"].includes(ext)) return "videocam";
  if (["mp3", "wav", "ogg"].includes(ext)) return "audio_file";
  if (["zip", "tar", "gz", "rar"].includes(ext)) return "folder_zip";
  if (["json", "xml", "yaml", "yml"].includes(ext)) return "data_object";
  if (["js", "ts", "py", "java", "go", "rs", "cpp", "c", "cs"].includes(ext))
    return "code";
  if (["pptx", "ppt"].includes(ext)) return "slideshow";
  return "draft";
}

function getFileTypeLabel(filename: string | null | undefined): string {
  if (!filename) return "FILE";
  return filename.split(".").pop()?.toUpperCase() ?? "FILE";
}

function middleTruncate(str: string, maxLen = 28): string {
  if (str.length <= maxLen) return str;
  const keep = Math.floor((maxLen - 1) / 2);
  return str.slice(0, keep) + "…" + str.slice(str.length - keep);
}

function getFileTypeColorClass(filename: string | null | undefined): string {
  if (!filename) return "text-[#464555]";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "text-[#3525cd]";
  if (["md", "txt", "doc", "docx"].includes(ext)) return "text-emerald-600";
  if (["xlsx", "xls", "csv"].includes(ext)) return "text-amber-600";
  return "text-[#464555]";
}

function citationProviderLabel(citation: ChatCitationResponse): string | null {
  return citation.source_provider_label ?? citation.source_provider ?? null;
}

function citationTrustLabel(citation: ChatCitationResponse): string | null {
  return citation.source_trust_status ?? null;
}

function formatConnectorSourceRoots(
  providerKey: string,
  authConfig: Record<string, unknown>,
): string[] {
  const rawValues =
    providerKey === "confluence"
      ? authConfig.space_keys
      : providerKey === "google_drive"
        ? [
            ...(Array.isArray(authConfig.folder_ids)
              ? authConfig.folder_ids
              : []),
            ...(Array.isArray(authConfig.drive_ids)
              ? authConfig.drive_ids
              : []),
          ]
        : [];

  if (!Array.isArray(rawValues)) {
    return [];
  }
  return rawValues
    .map((value) => String(value).trim())
    .filter((value) => value.length > 0);
}

function getConnectorProviderLabel(providerKey: string): string {
  if (providerKey === "confluence") return "Confluence";
  if (providerKey === "google_drive") return "Google Drive";
  return providerKey
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function buildConnectorRootChips(
  connection: ConnectorConnectionSummary,
): { id: string; label: string }[] {
  const roots = formatConnectorSourceRoots(
    connection.provider_key,
    connection.auth_config ?? {},
  );
  return roots.map((root) => ({
    id: `${connection.id}:${root}`,
    label: root,
  }));
}

function isPreviewableFile(filename: string | null | undefined): boolean {
  if (!filename) return false;
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return ext === "pdf" || ext === "docx" || ext === "doc";
}

export function ChatPage() {
  const tc = useTranslations("chat.page");
  const chatFeedbackEnabled = getFrontendRuntimeConfig().features.feedback;
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { state } = useAuthSession();
  const lastAppliedSessionIdRef = useRef<string | null>(null);
  const contextModalRef = useRef<HTMLDivElement | null>(null);
  const persistedSettings = useMemo(() => readPersistedChatSettings(), []);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [contextSearchQuery, setContextSearchQuery] = useState("");
  const [documentSearchQuery, setDocumentSearchQuery] = useState("");
  const [contextPage, setContextPage] = useState(1);
  const [isContextModalOpen, setIsContextModalOpen] = useState(false);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>(
    () => persistedSettings?.selectedDocumentIds ?? [],
  );
  const [scopeMode, setScopeMode] = useState<ChatScopeMode>(
    () => persistedSettings?.scopeMode ?? "all",
  );
  const [answerLanguage, setAnswerLanguage] = useState<AnswerLanguageMode>(
    () => persistedSettings?.answerLanguage ?? "auto",
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
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [feedbackByMessageId, setFeedbackByMessageId] = useState<
    Record<string, MessageFeedbackResponse>
  >({});
  const [feedbackModalMessageId, setFeedbackModalMessageId] = useState<
    string | null
  >(null);
  const [activeCitation, setActiveCitation] =
    useState<ChatCitationResponse | null>(null);
  const [previewCitationSet, setPreviewCitationSet] = useState<{
    citations: ChatCitationResponse[];
    initialIndex: number;
  } | null>(null);
  const [isKnowledgeHubOpen, setIsKnowledgeHubOpen] = useState(false);
  const [selectedCollectionIds, setSelectedCollectionIds] = useState<string[]>(
    () => persistedSettings?.selectedCollectionIds ?? [],
  );
  const [selectedConnectorConnectionIds, setSelectedConnectorConnectionIds] =
    useState<string[]>(
      () => persistedSettings?.selectedConnectorConnectionIds ?? [],
    );
  const [selectedProviderSourceIds, setSelectedProviderSourceIds] = useState<
    string[]
  >(() => persistedSettings?.selectedProviderSourceIds ?? []);
  const [sessionSearchQuery, setSessionSearchQuery] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");
  const [confirmDeleteSessionId, setConfirmDeleteSessionId] = useState<
    string | null
  >(null);
  const [openSessionMenuId, setOpenSessionMenuId] = useState<string | null>(
    null,
  );
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [answerShareMessageId, setAnswerShareMessageId] = useState<
    string | null
  >(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);

  const activeOrgId = state.session?.organizationId ?? null;
  const prevOrgIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevOrgIdRef.current === null) {
      prevOrgIdRef.current = activeOrgId;
      return;
    }
    if (activeOrgId !== prevOrgIdRef.current) {
      prevOrgIdRef.current = activeOrgId;
      setScopeMode("all");
      setSelectedCollectionIds([]);
      setSelectedDocumentIds([]);
      setSelectedConnectorConnectionIds([]);
      setSelectedProviderSourceIds([]);
    }
  }, [activeOrgId]);

  const settingsPreferencesQuery = useQuery({
    queryKey: ["settings", "preferences", "chat"],
    queryFn: loadSettingsPreferences,
    retry: false,
  });

  const sessionsQuery = useInfiniteQuery({
    queryKey: queryKeys.chat.sessionsQuery(
      debouncedSearchQuery ? { search: debouncedSearchQuery } : undefined,
    ),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listChatSessions({
        limit: SESSION_LIST_LIMIT,
        offset: Number(pageParam),
        search: debouncedSearchQuery || undefined,
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
      if (chatFeedbackEnabled) {
        try {
          const feedbackResponse = await listSessionFeedback(activeSessionId);
          setFeedbackByMessageId((previous) => {
            const next = { ...previous };
            for (const fb of feedbackResponse.items) {
              next[fb.message_id] = fb;
            }
            return next;
          });
        } catch {
          // non-critical — feedback state remains as-is
        }
      }
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

  const documentPickerQuery = useQuery({
    queryKey: queryKeys.documents.list({
      status: "indexed",
      limit: SCOPE_DOCUMENT_PICKER_LIMIT,
      offset: 0,
      filename_query: documentSearchQuery.trim() || undefined,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: SCOPE_DOCUMENT_PICKER_LIMIT,
        offset: 0,
        filename_query: documentSearchQuery.trim() || undefined,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
    placeholderData: keepPreviousData,
  });

  const indexedDocumentIdSet = useMemo(
    () => new Set(indexedDocuments.map((doc) => doc.document_id)),
    [indexedDocuments],
  );

  const collectionsListQuery = useQuery({
    queryKey: [...queryKeys.collections.all, "chat-picker"],
    queryFn: () => listCollections({ limit: 200 }),
  });
  const collections = collectionsListQuery.data?.items ?? [];

  const connectorConnectionsQuery = useQuery({
    queryKey: [...queryKeys.connectorConnections, "chat-picker"],
    queryFn: () => listAvailableConnectorConnections(),
  });
  const connectorConnections = connectorConnectionsQuery.data?.items ?? [];
  const connectorDocumentCount = useMemo(
    () =>
      connectorConnections.reduce(
        (total, connection) => total + connection.source_count,
        0,
      ),
    [connectorConnections],
  );

  const composerCollections = useMemo(
    () =>
      collections.map((collection) => ({
        collection_id: collection.collection_id,
        name: collection.name,
        description: collection.description ?? null,
      })),
    [collections],
  );

  const composerConnectorConnections = useMemo(
    () =>
      connectorConnections.map((connection) => ({
        id: connection.id,
        display_name: connection.display_name,
        provider_label: getConnectorProviderLabel(connection.provider_key),
        external_account_id: connection.external_account_id ?? null,
        rootChips: buildConnectorRootChips(connection),
      })),
    [connectorConnections],
  );

  const composerIndexedDocuments = useMemo(
    () =>
      (documentPickerQuery.data?.items ?? []).map((document) => ({
        document_id: document.document_id,
        filename: document.filename,
        chunk_count: document.chunk_count,
        updated_at: document.updated_at ?? null,
      })),
    [documentPickerQuery.data?.items],
  );

  const selectedCollectionDocsQuery = useQuery({
    queryKey: [
      ...queryKeys.collections.all,
      "chat-picker-documents",
      ...selectedCollectionIds.slice().sort(),
    ],
    queryFn: async () => {
      const results = await Promise.all(
        selectedCollectionIds.map((collectionId) =>
          listCollectionDocuments(collectionId, { limit: 200 }),
        ),
      );
      return results;
    },
    enabled: scopeMode === "collection" && selectedCollectionIds.length > 0,
  });

  const collectionDocumentIdSet = useMemo(() => {
    if (scopeMode !== "collection" || selectedCollectionIds.length === 0) {
      return null;
    }
    const ids = new Set<string>();
    for (const response of selectedCollectionDocsQuery.data ?? []) {
      for (const doc of response.items ?? []) {
        if (doc.status === "indexed") {
          ids.add(doc.document_id);
        }
      }
    }
    return ids;
  }, [
    scopeMode,
    selectedCollectionIds.length,
    selectedCollectionDocsQuery.data,
  ]);

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

  const hasConnectorScopeSelection =
    selectedConnectorConnectionIds.length > 0 ||
    selectedProviderSourceIds.length > 0;
  const requiresUploadedDocuments =
    scopeMode !== "none" && scopeMode !== "connectors";

  const effectiveDocumentIds = useMemo(() => {
    if (scopeMode === "none") {
      return [];
    }
    if (scopeMode === "collection") {
      if (collectionDocumentIdSet && collectionDocumentIdSet.size > 0) {
        return Array.from(collectionDocumentIdSet);
      }
      return [];
    }
    if (scopeMode === "connectors") {
      return [];
    }
    if (scopeMode === "documents" || scopeMode === "all") {
      return filteredSelectedDocumentIds;
    }
    return [];
  }, [scopeMode, collectionDocumentIdSet, filteredSelectedDocumentIds]);

  const scopeWarning = useMemo<string | null>(() => {
    if (scopeMode === "collection") {
      if (selectedCollectionIds.length === 0)
        return "Select at least one collection to scope retrieval.";
      if (selectedCollectionDocsQuery.isLoading) return null;
      if (
        collectionDocumentIdSet !== null &&
        collectionDocumentIdSet.size === 0
      ) {
        return "The selected collections have no indexed documents.";
      }
    }
    if (scopeMode === "connectors" && !hasConnectorScopeSelection) {
      return "Select at least one connector source to use connector scope.";
    }
    if (scopeMode === "documents" && filteredSelectedDocumentIds.length === 0) {
      return "Select at least one file to scope retrieval.";
    }
    return null;
  }, [
    scopeMode,
    selectedCollectionIds.length,
    selectedCollectionDocsQuery.isLoading,
    collectionDocumentIdSet,
    hasConnectorScopeSelection,
    filteredSelectedDocumentIds.length,
  ]);
  const contextModalOffset = (contextPage - 1) * CONTEXT_MODAL_PAGE_SIZE;
  const contextModalQuery = useQuery({
    queryKey: queryKeys.documents.list({
      status: "indexed",
      limit: CONTEXT_MODAL_PAGE_SIZE,
      offset: contextModalOffset,
      filename_query: contextSearchQuery.trim() || undefined,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: CONTEXT_MODAL_PAGE_SIZE,
        offset: contextModalOffset,
        filename_query: contextSearchQuery.trim() || undefined,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
    placeholderData: keepPreviousData,
  });
  const contextModalTotal = contextModalQuery.data?.total ?? 0;
  const contextPageCount = Math.max(
    1,
    Math.ceil(contextModalTotal / CONTEXT_MODAL_PAGE_SIZE),
  );
  const boundedContextPage = Math.min(contextPage, contextPageCount);
  const contextPageStartIndex =
    contextModalTotal === 0 ? 0 : contextModalOffset + 1;
  const contextPageEndIndex = Math.min(
    contextModalOffset + CONTEXT_MODAL_PAGE_SIZE,
    contextModalTotal,
  );

  const totalIndexedDocuments =
    indexedDocumentsQuery.data?.total ?? indexedDocuments.length;
  const totalDocumentsInAllScope =
    totalIndexedDocuments + connectorDocumentCount;
  const hasAvailableDocuments = totalDocumentsInAllScope > 0;
  const contextScopeItemCount =
    scopeMode === "collection"
      ? selectedCollectionIds.length
      : scopeMode === "connectors"
        ? selectedConnectorConnectionIds.length +
          selectedProviderSourceIds.length
        : effectiveDocumentIds.length > 0
          ? effectiveDocumentIds.length
          : totalDocumentsInAllScope;

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const payload: PersistedChatSettings = {
      topK,
      rerank,
      agenticMode,
      answerLanguage,
    };
    window.localStorage.setItem(
      CHAT_SETTINGS_STORAGE_KEY,
      JSON.stringify(payload),
    );
  }, [agenticMode, answerLanguage, rerank, topK]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearchQuery(sessionSearchQuery.trim());
    }, 300);
    return () => {
      window.clearTimeout(timer);
    };
  }, [sessionSearchQuery]);

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

  useEffect(() => {
    if (!openSessionMenuId) return;
    const close = () => setOpenSessionMenuId(null);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [openSessionMenuId]);

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

  // ── WebSocket chat transport (F277) ────────────────────────────────────────
  const wsChat = useChatWebSocket();

  const scrollToBottom = (smooth = false) => {
    const el = messagesContainerRef.current;
    if (!el) return;
    if (smooth) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  };

  // Jump to the bottom instantly when switching sessions or loading history.
  useEffect(() => {
    scrollToBottom();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId, thread.length]);

  // Smooth-scroll as new content arrives during streaming.
  useEffect(() => {
    if (!pendingQuestion && !wsChat.partialAnswer) return;
    scrollToBottom(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion, wsChat.partialAnswer]);

  // Track the WS-submitted question + scopeLabel so the completion effect can
  // build the ChatTurn with the same data the REST path would have.
  const wsPendingRef = useRef<{
    question: string;
    sessionId: string | null;
    scopeLabel: string | null;
  } | null>(null);

  useEffect(() => {
    if (!CHAT_WEBSOCKET_ENABLED) return;
    if (wsChat.phase !== "completed" || !wsChat.finalResponse) return;
    const response = wsChat.finalResponse;
    const pending = wsPendingRef.current;
    if (!pending) return;

    const resolvedSessionId =
      response.chat_session_id ?? pending.sessionId ?? activeSessionId;
    const nextSessionId = resolvedSessionId ?? DRAFT_SESSION_KEY;
    const previousThreadKey = activeThreadKey(pending.sessionId ?? null);
    const nextTurn: ChatTurn = {
      question: pending.question,
      response: toTurnResponseFromQuery(response, pending.scopeLabel),
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
    wsPendingRef.current = null;
    void invalidateAfterMutation(queryClient, "chat.query");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsChat.phase, wsChat.finalResponse]);

  useEffect(() => {
    if (!CHAT_WEBSOCKET_ENABLED) return;
    if (wsChat.phase !== "error" && wsChat.phase !== "cancelled") return;
    setPendingQuestion(null);
    wsPendingRef.current = null;
  }, [wsChat.phase]);
  // ── End WebSocket ────────────────────────────────────────────────────────

  const queryMutation = useMutation({
    mutationFn: (payload: ChatQueryRequest & { _scopeLabel?: string }) =>
      queryChat(payload),
    onSuccess: async (response, payload) => {
      const resolvedSessionId =
        response.chat_session_id ?? payload.chat_session_id ?? activeSessionId;
      const nextSessionId = resolvedSessionId ?? DRAFT_SESSION_KEY;
      const previousThreadKey = activeThreadKey(
        payload.chat_session_id ?? null,
      );
      const nextTurn: ChatTurn = {
        question: payload.question,
        response: toTurnResponseFromQuery(
          response,
          payload._scopeLabel ?? null,
        ),
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

  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => deleteChatSession(sessionId),
    onSuccess: async (_, deletedSessionId) => {
      if (activeSessionId === deletedSessionId) {
        resetForNewChat();
      }
      setThreadsBySession((previous) => {
        const next = { ...previous };
        delete next[activeThreadKey(deletedSessionId)];
        return next;
      });
      await invalidateAfterMutation(queryClient, "chat.session.delete");
    },
  });

  const feedbackSubmitMutation = useMutation({
    mutationFn: ({
      messageId,
      rating,
      reason,
      comment,
    }: {
      messageId: string;
      rating: "up" | "down";
      reason?: FeedbackReason | null;
      comment?: string | null;
    }) => submitMessageFeedback(messageId, { rating, reason, comment }),
    onSuccess: (data) => {
      setFeedbackByMessageId((previous) => ({
        ...previous,
        [data.message_id]: data,
      }));
    },
  });

  const feedbackDeleteMutation = useMutation({
    mutationFn: (messageId: string) => deleteMessageFeedback(messageId),
    onSuccess: (_, messageId) => {
      setFeedbackByMessageId((previous) => {
        const next = { ...previous };
        delete next[messageId];
        return next;
      });
    },
  });

  const isScopeInvalid = scopeWarning !== null;
  const isComposerDisabled =
    (CHAT_WEBSOCKET_ENABLED ? wsChat.isPending : queryMutation.isPending) ||
    agentRunMutation.isPending ||
    createSessionMutation.isPending ||
    question.trim().length === 0 ||
    indexedDocumentsQuery.isError ||
    (!hasAvailableDocuments && requiresUploadedDocuments) ||
    isScopeInvalid;

  function buildScopeLabel(): string {
    if (scopeMode === "none") return tc("scopeNoRetrieval");
    const parts: string[] = [];
    if (scopeMode === "all") {
      if (filteredSelectedDocumentIds.length > 0) {
        parts.push(
          tc("scopeAllDocumentsSelected", {
            n: filteredSelectedDocumentIds.length,
          }),
        );
      } else {
        parts.push(
          tc("scopeAllDocuments", { count: totalDocumentsInAllScope }),
        );
      }
    }
    if (scopeMode === "collection") {
      const collectionCount = selectedCollectionIds.length;
      parts.push(tc("scopeCollectionsSelected", { n: collectionCount }));
    }
    if (scopeMode === "documents") {
      const fileCount = filteredSelectedDocumentIds.length;
      if (fileCount > 0) {
        parts.push(tc("documentsSelected", { count: fileCount }));
      } else {
        parts.push(tc("selectDocuments"));
      }
    }
    if (scopeMode === "connectors") {
      const connectionCount = selectedConnectorConnectionIds.length;
      const sourceCount = selectedProviderSourceIds.length;
      if (connectionCount > 0) {
        parts.push(tc("scopeConnections", { n: connectionCount }));
      }
      if (sourceCount > 0) {
        parts.push(tc("scopeSourceRoots", { n: sourceCount }));
      }
      if (parts.length === 0) {
        parts.push(tc("scopeConnectorDefault"));
      }
    }
    if (parts.length > 0) {
      return parts.join(" · ");
    }
    return tc("scopeAllDocuments", { count: totalDocumentsInAllScope });
  }

  function buildSourceScopePayload(): ChatQueryRequest["source_scope"] | null {
    if (scopeMode === "none") {
      return null;
    }
    if (scopeMode === "connectors") {
      if (!hasConnectorScopeSelection) {
        return null;
      }
      return {
        mode: "connector_sources",
        connection_ids: selectedConnectorConnectionIds,
        provider_source_ids: selectedProviderSourceIds,
      };
    }
    if (scopeMode === "collection" && selectedCollectionIds.length > 0) {
      return {
        mode: "collections",
        collection_ids: selectedCollectionIds,
      };
    }
    return null;
  }

  const listForbidden =
    isForbiddenError(indexedDocumentsQuery.error) ||
    isForbiddenError(sessionsQuery.error);
  const composerError =
    (CHAT_WEBSOCKET_ENABLED && wsChat.error ? new Error(wsChat.error) : null) ??
    (!CHAT_WEBSOCKET_ENABLED ? queryMutation.error : null) ??
    agentRunMutation.error ??
    createSessionMutation.error;
  const composerForbidden = isForbiddenError(composerError);
  const wsPhaseLabel = CHAT_WEBSOCKET_ENABLED
    ? wsChat.phase === "retrieving"
      ? tc("wsRetrieving")
      : wsChat.phase === "reranking"
        ? tc("wsReranking")
        : wsChat.phase === "generating"
          ? tc("wsGenerating")
          : wsChat.phase === "validating_citations"
            ? tc("wsValidating")
            : wsChat.isPending
              ? tc("wsConnecting")
              : null
    : null;
  const composerSubmitButtonLabel = createSessionMutation.isPending
    ? tc("composerStarting")
    : agentRunMutation.isPending
      ? tc("composerAgentRunning")
      : (CHAT_WEBSOCKET_ENABLED ? wsChat.isPending : queryMutation.isPending)
        ? (wsPhaseLabel ?? tc("composerGenerating"))
        : tc("composerSend");
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

  function toggleCollection(collectionId: string) {
    setSelectedCollectionIds((previous) =>
      previous.includes(collectionId)
        ? previous.filter((value) => value !== collectionId)
        : [...previous, collectionId],
    );
  }

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

  function toggleConnectorConnection(connectionId: string) {
    setScopeMode("connectors");
    setSelectedConnectorConnectionIds((previous) =>
      previous.includes(connectionId)
        ? previous.filter((value) => value !== connectionId)
        : [...previous, connectionId],
    );
  }

  function toggleProviderSource(providerSourceId: string) {
    setScopeMode("connectors");
    setSelectedProviderSourceIds((previous) =>
      previous.includes(providerSourceId)
        ? previous.filter((value) => value !== providerSourceId)
        : [...previous, providerSourceId],
    );
  }

  function applyScopeMode(mode: ChatScopeMode) {
    setScopeMode(mode);
    if (mode !== "documents") setSelectedDocumentIds([]);
    if (mode !== "collection") setSelectedCollectionIds([]);
    if (mode !== "connectors") {
      setSelectedConnectorConnectionIds([]);
      setSelectedProviderSourceIds([]);
    }
  }

  function resetForNewChat() {
    setActiveSessionId(null);
    setSelectedResponseMessageId(null);
    setQuestion("");
    setPendingQuestion(null);
    setSubmitRequestId(null);
    replaceSessionParamInUrl(null);
  }

  const handleDeleteRequest = useCallback((sessionId: string) => {
    setConfirmDeleteSessionId(sessionId);
  }, []);

  const handleDeleteConfirm = useCallback(
    (sessionId: string) => {
      setConfirmDeleteSessionId(null);
      deleteSessionMutation.mutate(sessionId);
    },
    [deleteSessionMutation],
  );

  const handleDeleteCancel = useCallback(() => {
    setConfirmDeleteSessionId(null);
  }, []);

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
      isScopeInvalid ||
      (!hasAvailableDocuments &&
        requiresUploadedDocuments &&
        !indexedDocumentsQuery.isLoading)
    ) {
      return;
    }

    setSubmitRequestId(null);
    setPendingQuestion(trimmedQuestion);
    if (clearComposerOnSubmit) {
      setQuestion("");
    }

    const currentScopeLabel = buildScopeLabel();

    if (AGENTIC_CHAT_ENABLED && agenticMode && !hasConnectorScopeSelection) {
      const previousThreadKey = activeThreadKey(activeSessionId);
      let fallbackToStandardQuery = false;
      const payload: AgentRunCreateRequest = {
        agentic_mode: true,
        request: {
          objective: trimmedQuestion,
          mode: "answer",
          question: trimmedQuestion,
          document_ids:
            scopeMode !== "none" && effectiveDocumentIds.length > 0
              ? effectiveDocumentIds
              : undefined,
          top_k: topK,
          rerank,
        },
      };

      try {
        const response = await agentRunMutation.mutateAsync(payload);
        const nextTurn: ChatTurn = {
          question: trimmedQuestion,
          response: {
            ...toTurnResponseFromAgentRun(response.run),
            scope_label: currentScopeLabel,
          },
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
    if (AGENTIC_CHAT_ENABLED && agenticMode && hasConnectorScopeSelection) {
      setAgenticMode(false);
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

    const backendScopeMode: ChatQueryRequest["scope_mode"] =
      scopeMode === "connectors" ? "all" : scopeMode;

    const chatPayload = {
      question: trimmedQuestion,
      chat_session_id: targetSessionId,
      document_ids:
        requiresUploadedDocuments && effectiveDocumentIds.length > 0
          ? effectiveDocumentIds
          : undefined,
      top_k: topK,
      rerank,
      scope_mode: backendScopeMode,
      source_scope: buildSourceScopePayload() ?? undefined,
      answer_language: answerLanguage !== "auto" ? answerLanguage : undefined,
      _scopeLabel: currentScopeLabel,
    };

    if (CHAT_WEBSOCKET_ENABLED) {
      wsPendingRef.current = {
        question: trimmedQuestion,
        sessionId: targetSessionId,
        scopeLabel: currentScopeLabel,
      };
      wsChat.sendQuery(chatPayload);
    } else {
      queryMutation.mutate(chatPayload, {
        onError: (error) => {
          setSubmitRequestId(extractRequestIdFromError(error));
          if (clearComposerOnSubmit) {
            setQuestion(trimmedQuestion);
          }
          setPendingQuestion(null);
        },
      });
    }
  }

  if (listForbidden) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={tc("accessRestrictedTitle")}
          description={tc("accessRestrictedDesc")}
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
      <section className="flex h-full min-h-0 flex-col gap-4 overflow-hidden px-4 py-4 lg:px-8 lg:py-6">
        <header className="rounded-2xl border border-[#d7d4e8] bg-white px-4 py-4 shadow-sm lg:px-5">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0">
              <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
                {tc("eyebrow")}
              </p>
              <h1 className="truncate text-xl font-semibold text-[#2a2640] lg:text-2xl">
                {tc("title")}
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
                  value={sessionSearchQuery}
                  onChange={(e) => setSessionSearchQuery(e.target.value)}
                  placeholder={tc("searchPlaceholder")}
                  aria-label={tc("searchPlaceholder")}
                  className="h-9 w-60 rounded-full border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-xs text-[#2f2a46] ring-[#3525cd]/20 outline-none focus:ring"
                />
              </div>
              <Link
                href="/documents"
                className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
              >
                {tc("uploadDocuments")}
              </Link>
              <button
                type="button"
                onClick={resetForNewChat}
                className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
              >
                {tc("newChat")}
              </button>
            </div>
          </div>
        </header>

        <div
          className={`grid min-h-0 flex-1 gap-4 overflow-hidden xl:grid-rows-[1fr] ${isKnowledgeHubOpen || activeCitation !== null ? "xl:grid-cols-[280px_minmax(0,1fr)_320px]" : "xl:grid-cols-[280px_minmax(0,1fr)]"}`}
        >
          <aside className="hide-scrollbar min-h-0 space-y-4 overflow-y-auto xl:pr-1">
            <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
              <h2 className="mb-2 text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
                {tc("sessionsTitle")}
              </h2>
              {sessionsQuery.isLoading ? (
                <LoadingState compact title={tc("loadingSessions")} />
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
                    {sessions.map((session) => {
                      const isActive = session.session_id === activeSessionId;
                      const isConfirmingDelete =
                        confirmDeleteSessionId === session.session_id;
                      const displayTitle =
                        sessionDisplayTitleById.get(session.session_id) ??
                        tc("untitledSession");

                      return (
                        <li key={session.session_id}>
                          {isConfirmingDelete ? (
                            <div className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm">
                              <p className="mb-2 font-semibold text-rose-800">
                                {tc("deleteConfirmTitle")}
                              </p>
                              <p className="mb-3 truncate text-xs text-rose-700">
                                {displayTitle}
                              </p>
                              <div className="flex gap-2">
                                <button
                                  type="button"
                                  onClick={() =>
                                    handleDeleteConfirm(session.session_id)
                                  }
                                  disabled={deleteSessionMutation.isPending}
                                  className="flex-1 rounded bg-rose-600 px-2 py-1 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-60"
                                >
                                  {tc("delete")}
                                </button>
                                <button
                                  type="button"
                                  onClick={handleDeleteCancel}
                                  className="flex-1 rounded border border-rose-300 px-2 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-100"
                                >
                                  {tc("cancel")}
                                </button>
                              </div>
                            </div>
                          ) : (
                            <div
                              className={`group relative cursor-pointer rounded-lg border transition ${
                                isActive
                                  ? "border-[#3525cd] bg-[#ece8ff]"
                                  : "border-[#dfdbef] bg-white hover:bg-[#faf9ff]"
                              }`}
                            >
                              <button
                                type="button"
                                onClick={() => {
                                  setActiveSessionId(session.session_id);
                                  setSubmitRequestId(null);
                                  setPendingQuestion(null);
                                  replaceSessionParamInUrl(session.session_id);
                                }}
                                className="w-full cursor-pointer px-3 py-2 pr-8 text-left text-sm"
                              >
                                <p
                                  className={`truncate font-semibold ${isActive ? "text-[#2f2a46]" : "text-[#4f4b63]"}`}
                                >
                                  {displayTitle}
                                </p>
                                <p className="mt-1 text-xs text-[#7a758f]">
                                  {tc("sessionMeta", {
                                    count: session.message_count,
                                    date: formatDate(session.updated_at),
                                  })}
                                </p>
                              </button>
                              <div
                                className="absolute top-1 right-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
                                onMouseDown={(e) => e.stopPropagation()}
                              >
                                <button
                                  type="button"
                                  aria-label="Delete session"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleDeleteRequest(session.session_id);
                                  }}
                                  className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-[#6a6780] hover:text-rose-600"
                                >
                                  <span
                                    className="material-symbols-outlined text-[16px]"
                                    aria-hidden="true"
                                  >
                                    delete
                                  </span>
                                </button>
                              </div>
                            </div>
                          )}
                        </li>
                      );
                    })}
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
                        ? tc("loadingMore")
                        : tc("loadMore", {
                            loaded: sessions.length,
                            total: totalSessions,
                          })}
                    </button>
                  ) : null}
                </>
              ) : (
                <EmptyState
                  compact
                  title={
                    debouncedSearchQuery
                      ? tc("noSessionsSearch", { query: debouncedSearchQuery })
                      : tc("noSessionsYet")
                  }
                />
              )}
            </section>
          </aside>

          <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="flex items-start justify-between gap-2 border-b border-[#e2dff1] px-4 py-3">
                <div className="min-w-0">
                  <h2 className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
                    {tc("conversationTitle")}
                  </h2>
                  <p className="mt-1 text-xs text-[#5f5a74]">
                    {activeSession ? (
                      <>
                        {tc("sessionLabel")}{" "}
                        <span className="font-semibold text-[#2f2a46]">
                          {activeSessionDisplayTitle}
                        </span>
                        {" • "}
                        {tc("messagesCount", {
                          count: activeSession.message_count,
                        })}
                        {" • "}
                        {tc("updatedLabel", {
                          date: formatDate(activeSession.updated_at),
                        })}
                      </>
                    ) : (
                      tc("newChatDraft")
                    )}
                  </p>
                </div>
                {activeSessionId && thread.length > 0 ? (
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      aria-label={tc("copyTranscriptTitle")}
                      title={tc("copyTranscriptTitle")}
                      onClick={() => {
                        const md = formatTranscriptAsMarkdown(
                          toExportTurns(thread),
                          activeSessionDisplayTitle,
                        );
                        void copyToClipboard(md);
                      }}
                      className="inline-flex items-center gap-1 rounded border border-[#d2cee6] px-2 py-1 text-xs text-[#3e376f] hover:bg-[#f5f3ff]"
                    >
                      <span
                        className="material-symbols-outlined text-[14px]"
                        aria-hidden="true"
                      >
                        content_copy
                      </span>
                      {tc("copyTranscript")}
                    </button>
                    <button
                      type="button"
                      aria-label={tc("exportTranscriptTitle")}
                      title={tc("exportTranscriptTitle")}
                      onClick={() => {
                        const md = formatTranscriptAsMarkdown(
                          toExportTurns(thread),
                          activeSessionDisplayTitle,
                        );
                        downloadMarkdown(
                          md,
                          `${sanitizeFilename(activeSessionDisplayTitle ?? "chat")}.md`,
                        );
                      }}
                      className="inline-flex items-center gap-1 rounded border border-[#d2cee6] px-2 py-1 text-xs text-[#3e376f] hover:bg-[#f5f3ff]"
                    >
                      <span
                        className="material-symbols-outlined text-[14px]"
                        aria-hidden="true"
                      >
                        download
                      </span>
                      {tc("exportTranscript")}
                    </button>
                    <button
                      type="button"
                      aria-label={tc("shareSessionTitle")}
                      title={tc("shareSessionTitle")}
                      onClick={() => setIsShareModalOpen(true)}
                      className="inline-flex items-center gap-1 rounded border border-[#d2cee6] px-2 py-1 text-xs text-[#3e376f] hover:bg-[#f5f3ff]"
                    >
                      <span
                        className="material-symbols-outlined text-[14px]"
                        aria-hidden="true"
                      >
                        share
                      </span>
                      {tc("shareSession")}
                    </button>
                  </div>
                ) : null}
              </div>

              <div
                ref={messagesContainerRef}
                className="hide-scrollbar min-h-0 flex-1 overflow-y-auto bg-white p-4"
              >
                {sessionMessagesQuery.isLoading &&
                activeSession &&
                thread.length === 0 &&
                activeSession.message_count > 0 ? (
                  <LoadingState compact title={tc("loadingHistory")} />
                ) : null}

                {sessionMessagesQuery.isError &&
                activeSession &&
                thread.length === 0 &&
                activeSession.message_count > 0 ? (
                  <ErrorState
                    compact
                    title={tc("loadHistoryError")}
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
                  <EmptyState compact title={tc("noMessages")} />
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
                              <p className="sr-only">{tc("questionLabel")}</p>
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
                            <div className="flex max-w-[92%] min-w-0 flex-1 flex-col">
                              <article className="rounded-xl rounded-tl-none border border-[#c7c4d8] bg-white px-4 py-3 shadow-sm">
                                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="group/conf relative">
                                      <span className={confidenceBadgeClass()}>
                                        <span
                                          className="material-symbols-outlined text-xs"
                                          aria-hidden="true"
                                          style={{
                                            fontVariationSettings: "'FILL' 1",
                                          }}
                                        >
                                          verified
                                        </span>
                                        Confidence{" "}
                                        {formatPercent(
                                          turn.response.confidence_score,
                                        )}
                                      </span>
                                      {turn.response.confidence_category ===
                                        "low" && !turn.response.not_found ? (
                                        <span className="pointer-events-none absolute bottom-full left-0 z-10 mb-1.5 w-56 rounded bg-[#2a2640] px-2 py-1.5 text-[10px] leading-snug whitespace-normal text-white opacity-0 transition-opacity group-hover/conf:opacity-100">
                                          Low confidence warning: validate this
                                          answer against the cited source text.
                                        </span>
                                      ) : null}
                                    </span>
                                    {turn.response.scope_label ? (
                                      <span className="inline-flex items-center gap-1 rounded-full border border-[#d7d4e8] bg-[#f0ecf9] px-2 py-0.5 text-[10px] font-semibold text-[#3525cd]">
                                        <span
                                          className="material-symbols-outlined text-[11px]"
                                          aria-hidden="true"
                                        >
                                          filter_alt
                                        </span>
                                        {turn.response.scope_label}
                                      </span>
                                    ) : null}
                                  </div>
                                  <div className="flex items-center gap-2">
                                    {turn.response.agent_run_status ? (
                                      <span
                                        className={agentRunStatusClass(
                                          turn.response.agent_run_status,
                                        )}
                                      >
                                        {tc("agentStatus", {
                                          status:
                                            turn.response.agent_run_status,
                                        })}
                                      </span>
                                    ) : null}
                                    <span className="font-mono text-xs text-[#6a6780]">
                                      {formatDate(turn.response.created_at)}
                                    </span>
                                  </div>
                                </div>

                                {turn.response.citation_validation_failed &&
                                !turn.response.not_found ? (
                                  <p className="mb-3 rounded-lg border border-[#f5c6b0] bg-[#fff8f5] px-3 py-2 text-xs text-[#7a3a20]">
                                    {tc("citationValidationFailed")}
                                  </p>
                                ) : null}

                                <ConflictWarningCard
                                  conflictDetected={
                                    turn.response.conflict_detected
                                  }
                                  agreementLevel={turn.response.agreement_level}
                                  conflictSummary={turn.response.conflict_summary}
                                  preferredDocumentIds={
                                    turn.response.preferred_document_ids
                                  }
                                />

                                {turn.response.not_found ? (
                                  <div className="space-y-2">
                                    <p className="rounded-lg border border-[#d2cee6] bg-[#faf9ff] px-3 py-2 text-sm break-words text-[#2f2a46]">
                                      {tc("notFoundAnswer")}
                                    </p>
                                    <p className="text-xs text-[#6a6780]">
                                      {tc("notFoundHint")}
                                    </p>
                                  </div>
                                ) : (
                                  <>
                                    <p className="hide-scrollbar max-h-80 overflow-y-auto pr-1 text-sm break-words whitespace-pre-wrap text-[#2f2a46]">
                                      {turn.response.answer}
                                    </p>
                                    {turn.response.citations.length > 0 && (
                                      <div className="mt-2 flex flex-wrap gap-1.5">
                                        {turn.response.citations.map(
                                          (citation, ci) => {
                                            const label =
                                              citation.source_title ??
                                              citation.filename ??
                                              tc("documentFallback");
                                            const ext =
                                              citation.filename
                                                ?.split(".")
                                                .pop()
                                                ?.toUpperCase() ?? "FILE";
                                            return (
                                              <div
                                                key={`inline:${citation.document_id}:${citation.chunk_id}:${ci}`}
                                                className="relative flex w-64 shrink-0 items-stretch rounded-lg border border-[#c7c4d8] bg-white transition-colors hover:bg-[#eae6f4]"
                                              >
                                                <button
                                                  type="button"
                                                  onClick={() => {
                                                    setSelectedResponseMessageId(
                                                      turn.response.message_id,
                                                    );
                                                    setIsKnowledgeHubOpen(
                                                      false,
                                                    );
                                                    setActiveCitation(citation);
                                                  }}
                                                  title={label}
                                                  className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 overflow-hidden px-2.5 py-2 text-left"
                                                >
                                                  <span
                                                    className={`material-symbols-outlined shrink-0 text-[22px] ${getFileTypeColorClass(citation.filename)}`}
                                                    aria-hidden="true"
                                                  >
                                                    {getFileIcon(
                                                      citation.filename,
                                                    )}
                                                  </span>
                                                  <span className="min-w-0 flex-1 overflow-hidden">
                                                    <span
                                                      className={`block text-[10px] font-bold uppercase ${getFileTypeColorClass(citation.filename)}`}
                                                    >
                                                      {citationProviderLabel(
                                                        citation,
                                                      )?.toUpperCase() ?? ext}
                                                    </span>
                                                    <span className="block truncate text-xs font-medium text-[#1b1b24]">
                                                      {label}
                                                    </span>
                                                    {conflictStatusLabel(
                                                      citation.conflict_status,
                                                    ) ? (
                                                      <span className="mt-1 inline-flex rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold uppercase text-[#5d58a8]">
                                                        {conflictStatusLabel(
                                                          citation.conflict_status,
                                                        )}
                                                      </span>
                                                    ) : null}
                                                  </span>
                                                </button>
                                                {isPreviewableFile(
                                                  citation.filename,
                                                ) && (
                                                  <button
                                                    type="button"
                                                    aria-label={`Preview ${citation.filename ?? "document"}`}
                                                    onClick={() => {
                                                      const siblings =
                                                        turn.response.citations.filter(
                                                          (c) =>
                                                            c.document_id ===
                                                            citation.document_id,
                                                        );
                                                      const idx =
                                                        siblings.indexOf(
                                                          citation,
                                                        );
                                                      setPreviewCitationSet({
                                                        citations: siblings,
                                                        initialIndex:
                                                          idx >= 0 ? idx : 0,
                                                      });
                                                    }}
                                                    className="shrink-0 self-center border-l border-[#e4e1ee] px-2 text-[#6a6780] transition-colors hover:bg-[#ede9f9] hover:text-[#3525cd]"
                                                  >
                                                    <span
                                                      className="material-symbols-outlined text-[16px]"
                                                      aria-hidden="true"
                                                    >
                                                      open_in_new
                                                    </span>
                                                  </button>
                                                )}
                                              </div>
                                            );
                                          },
                                        )}
                                      </div>
                                    )}
                                    {turn.response.citations[0]
                                      ?.text_snippet && (
                                      <button
                                        type="button"
                                        onClick={() => {
                                          setSelectedResponseMessageId(
                                            turn.response.message_id,
                                          );
                                          setActiveCitation(null);
                                          setIsKnowledgeHubOpen(true);
                                        }}
                                        className="mt-3 w-full cursor-pointer rounded-r border-l-4 border-[#3525cd] bg-white px-3 py-2 text-left text-sm text-[#464555] italic shadow-sm transition-colors hover:bg-[#f5f2ff]"
                                      >
                                        {
                                          turn.response.citations[0]
                                            .text_snippet
                                        }
                                      </button>
                                    )}
                                  </>
                                )}
                                {turn.response.agent_run_error ? (
                                  <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
                                    {tc("agentStopReason", {
                                      reason:
                                        turn.response.agent_run_error.message,
                                    })}
                                  </p>
                                ) : null}
                              </article>
                              <div className="mt-1 flex items-center gap-0.5 px-1">
                                {!turn.response.not_found ? (
                                  <div className="group/copy relative">
                                    <button
                                      type="button"
                                      aria-label="Copy answer"
                                      onClick={() => {
                                        const md = formatAnswerAsMarkdown({
                                          question: turn.question,
                                          answer: turn.response.answer,
                                          citations: turn.response.citations,
                                          created_at: turn.response.created_at,
                                        });
                                        void copyToClipboard(md).then(() => {
                                          setCopiedMessageId(
                                            turn.response.message_id,
                                          );
                                          setTimeout(
                                            () => setCopiedMessageId(null),
                                            2000,
                                          );
                                        });
                                      }}
                                      className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${copiedMessageId === turn.response.message_id ? "text-[#3525cd]" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
                                    >
                                      <span
                                        className="material-symbols-outlined text-[13px]"
                                        aria-hidden="true"
                                      >
                                        {copiedMessageId ===
                                        turn.response.message_id
                                          ? "check"
                                          : "content_copy"}
                                      </span>
                                    </button>
                                    <span className="pointer-events-none absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover/copy:opacity-100">
                                      {copiedMessageId ===
                                      turn.response.message_id
                                        ? tc("copiedTooltip")
                                        : tc("copyTooltip")}
                                    </span>
                                  </div>
                                ) : null}
                                {!turn.response.not_found ? (
                                  <div className="group/answershare relative">
                                    <button
                                      type="button"
                                      aria-label="Share answer"
                                      onClick={() =>
                                        setAnswerShareMessageId(
                                          turn.response.message_id,
                                        )
                                      }
                                      className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-[#9d98b5] transition-colors hover:bg-[#f1f0f5] hover:text-[#6a6780]"
                                    >
                                      <span
                                        className="material-symbols-outlined text-[13px]"
                                        aria-hidden="true"
                                      >
                                        ios_share
                                      </span>
                                    </button>
                                    <span className="pointer-events-none absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover/answershare:opacity-100">
                                      Share answer
                                    </span>
                                  </div>
                                ) : null}
                                {chatFeedbackEnabled ? (
                                  <>
                                    <div className="group/up relative">
                                      <button
                                        type="button"
                                        aria-label="Mark answer helpful"
                                        onClick={() => {
                                          const msgId =
                                            turn.response.message_id;
                                          if (
                                            feedbackByMessageId[msgId]
                                              ?.rating === "up"
                                          ) {
                                            feedbackDeleteMutation.mutate(
                                              msgId,
                                            );
                                          } else {
                                            feedbackSubmitMutation.mutate({
                                              messageId: msgId,
                                              rating: "up",
                                            });
                                          }
                                        }}
                                        className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${feedbackByMessageId[turn.response.message_id]?.rating === "up" ? "text-emerald-600" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
                                      >
                                        <span
                                          className="material-symbols-outlined text-[13px]"
                                          aria-hidden="true"
                                        >
                                          thumb_up
                                        </span>
                                      </button>
                                      <span className="pointer-events-none absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover/up:opacity-100">
                                        {tc("helpfulTooltip")}
                                      </span>
                                    </div>
                                    <div className="group/down relative">
                                      <button
                                        type="button"
                                        aria-label="Report an issue"
                                        onClick={() =>
                                          setFeedbackModalMessageId(
                                            turn.response.message_id,
                                          )
                                        }
                                        className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${feedbackByMessageId[turn.response.message_id]?.rating === "down" ? "text-rose-500" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
                                      >
                                        <span
                                          className="material-symbols-outlined text-[13px]"
                                          aria-hidden="true"
                                        >
                                          thumb_down
                                        </span>
                                      </button>
                                      <span className="pointer-events-none absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover/down:opacity-100">
                                        {tc("notHelpfulTooltip")}
                                      </span>
                                    </div>
                                  </>
                                ) : null}
                                {isLatestTurn ? (
                                  <div className="group/regen relative">
                                    <button
                                      type="button"
                                      aria-label="Regenerate answer"
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
                                        (!hasAvailableDocuments &&
                                          scopeMode !== "none")
                                      }
                                      className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-[#9d98b5] transition-colors hover:bg-[#f1f0f5] hover:text-[#6a6780] disabled:cursor-not-allowed disabled:opacity-40"
                                    >
                                      <span
                                        className="material-symbols-outlined text-[13px]"
                                        aria-hidden="true"
                                      >
                                        refresh
                                      </span>
                                    </button>
                                    <span className="pointer-events-none absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover/regen:opacity-100">
                                      {tc("regenerateTooltip")}
                                    </span>
                                  </div>
                                ) : null}
                              </div>
                            </div>
                          </div>
                        </li>
                      );
                    })}
                    {pendingQuestion ? (
                      <li className="space-y-3">
                        <div className="flex justify-end">
                          <article className="max-w-[80%] rounded-xl rounded-tr-none bg-[#f0ecf9] px-4 py-3 shadow-sm">
                            <p className="sr-only">{tc("questionLabel")}</p>
                            <p className="hide-scrollbar max-h-72 overflow-y-auto pr-1 text-sm break-words whitespace-pre-wrap text-[#1b1b24]">
                              {pendingQuestion}
                            </p>
                          </article>
                        </div>
                        {CHAT_WEBSOCKET_ENABLED && wsChat.partialAnswer ? (
                          <div className="flex justify-start">
                            <article className="max-w-[90%] rounded-xl rounded-tl-none border border-[#e2dff1] bg-white px-4 py-3 shadow-sm">
                              <p className="text-sm break-words whitespace-pre-wrap text-[#2f2a46]">
                                {wsChat.partialAnswer}
                                <span
                                  className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[#3525cd] align-middle"
                                  aria-hidden="true"
                                />
                              </p>
                            </article>
                          </div>
                        ) : (
                          <ChatResponseLoadingState
                            label={
                              CHAT_WEBSOCKET_ENABLED && wsPhaseLabel
                                ? wsPhaseLabel
                                : STREAMING_PLACEHOLDER_ENABLED
                                  ? tc("streamingLabel")
                                  : tc("generatingLabel")
                            }
                          />
                        )}
                      </li>
                    ) : null}
                  </ul>
                )}
              </div>

              {composerForbidden ? (
                <div className="border-t border-[#e2dff1] px-4 py-3">
                  <ForbiddenState
                    compact
                    title={tc("queryForbiddenTitle")}
                    description={tc("queryForbiddenDesc")}
                    requestId={extractRequestIdFromError(composerError)}
                  />
                </div>
              ) : null}

              {composerError && !composerForbidden ? (
                <div className="border-t border-[#e2dff1] px-4 py-3">
                  <ErrorState
                    title={tc("queryErrorTitle")}
                    error={composerError}
                    description={getApiErrorMessage(composerError)}
                    requestId={submitRequestId}
                  />
                </div>
              ) : null}

              <ChatComposer
                agenticChatEnabled={AGENTIC_CHAT_ENABLED}
                agenticMode={agenticMode}
                answerLanguage={answerLanguage}
                collections={composerCollections}
                disabled={isComposerDisabled}
                hasConnectorScopeSelection={hasConnectorScopeSelection}
                hasAvailableDocuments={hasAvailableDocuments}
                isCollectionsLoading={collectionsListQuery.isLoading}
                isConnectorsLoading={connectorConnectionsQuery.isLoading}
                isDocumentsLoading={documentPickerQuery.isLoading}
                connectorConnections={composerConnectorConnections}
                indexedDocuments={composerIndexedDocuments}
                totalIndexedDocuments={totalIndexedDocuments}
                isGenerating={CHAT_WEBSOCKET_ENABLED && wsChat.isPending}
                maxTopK={MAX_TOP_K}
                minTopK={MIN_TOP_K}
                onStop={() => wsChat.cancel()}
                onSubmit={submitQuestion}
                onToggleCollection={toggleCollection}
                onToggleConnectorConnection={toggleConnectorConnection}
                onToggleDocument={toggleDocument}
                question={question}
                requiresUploadedDocuments={requiresUploadedDocuments}
                rerank={rerank}
                scopeMode={scopeMode}
                scopeWarning={scopeWarning}
                selectedCollectionIds={selectedCollectionIds}
                selectedConnectorConnectionIds={selectedConnectorConnectionIds}
                selectedProviderSourceIds={selectedProviderSourceIds}
                selectedDocumentIds={selectedDocumentIds}
                documentSearchQuery={documentSearchQuery}
                setAgenticMode={setAgenticMode}
                setAnswerLanguage={setAnswerLanguage}
                setQuestion={setQuestion}
                setRerank={setRerank}
                setScopeMode={applyScopeMode}
                setDocumentSearchQuery={setDocumentSearchQuery}
                setTopK={setTopK}
                submitButtonLabel={composerSubmitButtonLabel}
                topK={topK}
              />
            </div>
          </section>

          <aside
            className={`relative flex min-h-0 flex-col overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-sm ${isKnowledgeHubOpen || activeCitation !== null ? "" : "hidden"}`}
          >
            {/* ── Header ── */}
            <div className="flex items-center justify-between border-b border-[#e4e1ee] p-4">
              <div>
                <h2 className="text-lg font-semibold text-[#1b1b24]">
                  {tc("knowledgeHubTitle")}
                </h2>
                <p className="text-xs text-[#464555]">
                  {tc("knowledgeHubSubtitle")}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsKnowledgeHubOpen(false)}
                aria-label="Close Knowledge Hub"
                className="cursor-pointer rounded-full p-1.5 text-[#464555] transition-colors hover:bg-[#f0ecf9]"
              >
                <span
                  className="material-symbols-outlined text-[20px]"
                  aria-hidden="true"
                >
                  close
                </span>
              </button>
            </div>

            {/* ── Scrollable body ── */}
            <div className="hide-scrollbar flex-1 overflow-y-auto">
              {/* Context Map */}
              <div className="p-4">
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                    {tc("contextMapTitle")}
                  </span>
                  <button
                    type="button"
                    className="text-[10px] font-bold text-[#3525cd]"
                  >
                    {tc("contextMapExpand")}
                  </button>
                </div>
                <div className="group relative h-40 overflow-hidden rounded-xl border border-[#c7c4d8] bg-[#f0ecf9]">
                  <div className="pointer-events-none absolute inset-0 opacity-20">
                    <svg className="h-full w-full">
                      <line
                        stroke="#3525cd"
                        strokeWidth="1"
                        x1="20%"
                        y1="30%"
                        x2="50%"
                        y2="50%"
                      />
                      <line
                        stroke="#3525cd"
                        strokeWidth="1"
                        x1="50%"
                        y1="50%"
                        x2="80%"
                        y2="20%"
                      />
                      <line
                        stroke="#3525cd"
                        strokeWidth="1"
                        x1="50%"
                        y1="50%"
                        x2="70%"
                        y2="80%"
                      />
                    </svg>
                  </div>
                  <div className="absolute top-[30%] left-[20%] h-3 w-3 rounded-full bg-[#3525cd] shadow-lg" />
                  <div className="absolute top-[50%] left-[50%] flex h-6 w-6 items-center justify-center rounded-full bg-[#3525cd] shadow-lg">
                    <span
                      className="material-symbols-outlined text-xs text-white"
                      style={{ fontVariationSettings: "'FILL' 1" }}
                    >
                      stars
                    </span>
                  </div>
                  <div className="absolute top-[20%] left-[78%] h-2.5 w-2.5 rounded-full bg-[#505f76] shadow-lg" />
                  <div className="absolute top-[78%] left-[68%] h-4 w-4 rounded-full bg-[#a44100] shadow-lg" />
                  <div className="absolute right-2 bottom-2 left-2 rounded border border-[#c7c4d8] bg-white/80 px-2 py-0.5 text-center font-mono text-[9px] text-[#464555] backdrop-blur-sm">
                    {tc("contextMapConnected", {
                      count:
                        selectedCitationTurn?.response.citations.length ?? 0,
                    })}
                  </div>
                </div>
              </div>

              {/* Source Documents */}
              <div className="border-t border-[#e4e1ee] bg-[#f5f2ff] p-4">
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                    {tc("sourceDocsTitle")}
                  </span>
                  <span
                    className="material-symbols-outlined text-sm text-[#464555]"
                    aria-hidden="true"
                  >
                    filter_list
                  </span>
                </div>

                {!selectedCitationTurn ? (
                  <p className="text-xs text-[#777587]">
                    {tc("sourceDocsAsk")}
                  </p>
                ) : selectedCitationTurn.response.conflict_detected ? (
                  <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={agreementLevelClass(
                          selectedCitationTurn.response.agreement_level,
                        )}
                      >
                        {agreementLevelLabel(
                          selectedCitationTurn.response.agreement_level,
                        )}
                      </span>
                      <span className="font-semibold">
                        Source comparison
                      </span>
                    </div>
                    {selectedCitationTurn.response.conflict_summary ? (
                      <p className="mt-1 text-[11px] leading-snug">
                        {selectedCitationTurn.response.conflict_summary}
                      </p>
                    ) : null}
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <div>
                        <p className="mb-2 text-[10px] font-bold tracking-widest text-emerald-800 uppercase">
                          Preferred sources
                        </p>
                        <div className="space-y-2">
                          {selectedCitationTurn.response.citations
                            .filter((citation) =>
                              selectedCitationTurn.response.preferred_document_ids.includes(
                                citation.document_id,
                              ),
                            )
                            .map((citation, ci) => (
                              <button
                                key={`preferred:${citation.document_id}:${citation.chunk_id}:${ci}`}
                                type="button"
                                onClick={() => {
                                  setActiveCitation(citation);
                                  setIsKnowledgeHubOpen(false);
                                }}
                                className="group w-full rounded-lg border border-emerald-200 bg-white p-3 text-left transition-all hover:border-emerald-400"
                              >
                                <div className="mb-1 flex items-center justify-between">
                                  <span
                                    className={`text-[10px] font-bold ${getFileTypeColorClass(citation.filename)}`}
                                  >
                                    {getFileTypeLabel(citation.filename)}
                                  </span>
                                  <span className="text-[9px] font-semibold text-emerald-700 uppercase">
                                    Preferred
                                  </span>
                                </div>
                                <h4
                                  className="truncate text-sm font-bold text-[#1b1b24]"
                                  title={citation.filename ?? tc("unknownDocument")}
                                >
                                  {citation.filename ?? tc("unknownDocument")}
                                </h4>
                                {citation.page_number ? (
                                  <p className="text-[9px] text-[#464555]">
                                    Page {citation.page_number}
                                  </p>
                                ) : null}
                              </button>
                            ))}
                        </div>
                      </div>
                      <div>
                        <p className="mb-2 text-[10px] font-bold tracking-widest text-rose-800 uppercase">
                          Conflicting sources
                        </p>
                        <div className="space-y-2">
                          {selectedCitationTurn.response.citations
                            .filter((citation) =>
                              selectedCitationTurn.response.conflicting_document_ids.includes(
                                citation.document_id,
                              ),
                            )
                            .map((citation, ci) => (
                              <button
                                key={`conflicting:${citation.document_id}:${citation.chunk_id}:${ci}`}
                                type="button"
                                onClick={() => {
                                  setActiveCitation(citation);
                                  setIsKnowledgeHubOpen(false);
                                }}
                                className="group w-full rounded-lg border border-rose-200 bg-white p-3 text-left transition-all hover:border-rose-400"
                              >
                                <div className="mb-1 flex items-center justify-between">
                                  <span
                                    className={`text-[10px] font-bold ${getFileTypeColorClass(citation.filename)}`}
                                  >
                                    {getFileTypeLabel(citation.filename)}
                                  </span>
                                  <span className="text-[9px] font-semibold text-rose-700 uppercase">
                                    Conflicting
                                  </span>
                                </div>
                                <h4
                                  className="truncate text-sm font-bold text-[#1b1b24]"
                                  title={citation.filename ?? tc("unknownDocument")}
                                >
                                  {citation.filename ?? tc("unknownDocument")}
                                </h4>
                                {citation.page_number ? (
                                  <p className="text-[9px] text-[#464555]">
                                    Page {citation.page_number}
                                  </p>
                                ) : null}
                              </button>
                            ))}
                        </div>
                      </div>
                    </div>
                  </div>
                ) : selectedCitationTurn.response.not_found ? (
                  <p className="text-xs text-[#777587]">
                    {tc("sourceDocsNotFound")}
                  </p>
                ) : selectedCitationTurn.response.citations.length === 0 ? (
                  <p className="text-xs text-[#777587]">
                    {tc("sourceDocsNone")}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {selectedCitationTurn.response.citations.map(
                      (citation, ci) => (
                        <button
                          key={`hub:${citation.document_id}:${citation.chunk_id}:${ci}`}
                          type="button"
                          onClick={() => {
                            setActiveCitation(citation);
                            setIsKnowledgeHubOpen(false);
                          }}
                          className="group w-full rounded-lg border border-[#c7c4d8] bg-white p-3 text-left transition-all hover:border-[#3525cd]"
                        >
                          <div className="mb-1 flex items-center justify-between">
                            <span
                              className={`text-[10px] font-bold ${getFileTypeColorClass(citation.filename)}`}
                            >
                              {getFileTypeLabel(citation.filename)}
                            </span>
                            <span
                              className="material-symbols-outlined text-xs text-[#464555] group-hover:text-[#3525cd]"
                              aria-hidden="true"
                            >
                              open_in_new
                            </span>
                          </div>
                          <h4
                            className="mb-1 truncate text-sm font-bold text-[#1b1b24]"
                            title={citation.filename ?? tc("unknownDocument")}
                          >
                            {citation.filename ?? tc("unknownDocument")}
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
                      ),
                    )}
                    {selectedCitationPipelineHref ? (
                      <Link
                        href={selectedCitationPipelineHref}
                        className="mt-1 flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-[#777587] py-2 text-xs font-bold text-[#464555] transition-all hover:border-[#3525cd] hover:bg-white hover:text-[#3525cd]"
                      >
                        {tc("viewPipelineRun")}
                      </Link>
                    ) : null}
                  </div>
                )}

                {/* Agent timeline */}
                {selectedAgentRunId ? (
                  <div className="mt-4">
                    <p className="mb-2 text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                      {tc("agentTimeline")}
                    </p>
                    {selectedAgentRunQuery.isLoading ? (
                      <LoadingState compact title={tc("loadingTimeline")} />
                    ) : selectedAgentRunQuery.isError ? (
                      <ErrorState
                        compact
                        error={selectedAgentRunQuery.error}
                        description={getApiErrorMessage(
                          selectedAgentRunQuery.error,
                        )}
                        onRetry={() => {
                          void selectedAgentRunQuery.refetch();
                        }}
                      />
                    ) : selectedAgentRunQuery.data ? (
                      <div className="space-y-1.5 text-xs text-[#4f4b63]">
                        <div className="flex flex-wrap items-center gap-2 rounded border border-[#ebe8f7] px-2 py-1.5">
                          <span
                            className={agentRunStatusClass(
                              selectedAgentRunQuery.data.status,
                            )}
                          >
                            {selectedAgentRunQuery.data.status}
                          </span>
                          <span className="truncate text-[#6a6780]">
                            run {selectedAgentRunQuery.data.run_id.slice(0, 8)}…
                          </span>
                        </div>
                        {selectedAgentRunQuery.data.approvals.length > 0 && (
                          <p className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                            {tc("approvalsTitle")}
                          </p>
                        )}
                        {selectedAgentRunQuery.data.approvals
                          .filter((a) => a.status === "pending")
                          .map((approval) => (
                            <div
                              key={approval.approval_id}
                              className="rounded border border-amber-200 bg-amber-50 px-2 py-2"
                            >
                              <p className="mb-1 text-xs text-amber-800">
                                {approval.request_summary ??
                                  tc("approvalNeeded")}
                              </p>
                              {canDecideApprovals && (
                                <div className="flex gap-2">
                                  <button
                                    type="button"
                                    disabled={decideApprovalMutation.isPending}
                                    onClick={() => {
                                      void handleApprovalDecision({
                                        runId:
                                          selectedAgentRunQuery.data.run_id,
                                        approvalId: approval.approval_id,
                                        status: "approved",
                                      });
                                    }}
                                    className="rounded border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800 disabled:opacity-60"
                                  >
                                    {tc("approve")}
                                  </button>
                                  <button
                                    type="button"
                                    disabled={decideApprovalMutation.isPending}
                                    onClick={() => {
                                      void handleApprovalDecision({
                                        runId:
                                          selectedAgentRunQuery.data.run_id,
                                        approvalId: approval.approval_id,
                                        status: "rejected",
                                      });
                                    }}
                                    className="rounded border border-rose-300 bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-800 disabled:opacity-60"
                                  >
                                    {tc("reject")}
                                  </button>
                                </div>
                              )}
                            </div>
                          ))}
                        <ol className="space-y-1">
                          {selectedAgentRunQuery.data.steps.map((step) => (
                            <li
                              key={step.step_id}
                              className="rounded border border-[#ebe8f7] px-2 py-1.5"
                            >
                              <p className="font-semibold text-[#3f3b58]">
                                {step.sequence}. {step.step_name}
                              </p>
                              <p className="text-[#6a6780]">
                                {step.status}
                                {step.duration_ms !== null
                                  ? ` • ${step.duration_ms}ms`
                                  : ""}
                              </p>
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

                {/* Fallback warning — visible to all users */}
                {selectedCitationTurn?.response.debug?.fallback_used ? (
                  <div className="mt-3 flex items-start gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    <span className="mt-0.5 shrink-0">⚠</span>
                    <span>
                      {selectedCitationTurn.response.debug.fallback_to
                        ? tc("fallbackWarningWithProvider", {
                            provider:
                              selectedCitationTurn.response.debug.fallback_to,
                          })
                        : tc("fallbackWarning")}
                    </span>
                  </div>
                ) : null}

                {/* Debug details for admins */}
                {showDebugDetails && selectedCitationTurn?.response.debug ? (
                  <details className="mt-4">
                    <summary className="cursor-pointer text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                      {tc("retrievalDebug")}
                    </summary>
                    <div className="mt-2 space-y-1 text-xs text-[#4f4b63]">
                      <dl className="grid grid-cols-2 gap-1 rounded border border-[#ebe8f7] px-2 py-2">
                        {(
                          [
                            "retrieval_count",
                            "selected_count",
                            "rerank_applied",
                            "embedding_model",
                            "llm_model",
                            "llm_provider",
                            "fallback_used",
                            "fallback_from",
                            "fallback_to",
                            "graph_context_enabled",
                            "graph_context_used",
                            "graph_context_unavailable",
                            "graph_context_reason",
                            "graph_seed_entity_count",
                            "graph_related_entity_count",
                            "graph_chunk_count",
                            "graph_max_hops_used",
                            "graph_relation_types_used",
                            "detected_language",
                            "answer_language_used",
                          ] as const
                        ).map((key) => (
                          <div
                            key={key}
                            className={
                              key === "llm_model" ||
                              key === "llm_provider" ||
                              key === "graph_context_reason" ||
                              key === "graph_relation_types_used"
                                ? "col-span-2"
                                : ""
                            }
                          >
                            <dt className="font-semibold">{key}</dt>
                            <dd>
                              {String(
                                (
                                  selectedCitationTurn.response.debug as Record<
                                    string,
                                    unknown
                                  >
                                )[key] ?? "N/A",
                              )}
                            </dd>
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
                  <p className="mb-1 text-[9px] font-bold tracking-wider text-[#464555] uppercase">
                    {tc("confidenceMetric")}
                  </p>
                  <p className="text-lg font-semibold text-[#3525cd]">
                    {selectedCitationTurn
                      ? selectedCitationTurn.response.confidence_category ===
                        "high"
                        ? tc("confidenceHigh")
                        : selectedCitationTurn.response.confidence_category ===
                            "medium"
                          ? tc("confidenceMedium")
                          : tc("confidenceLow")
                      : "—"}
                  </p>
                </div>
                <div className="rounded-lg border border-[#c7c4d8] bg-[#f0ecf9] p-2">
                  <p className="mb-1 text-[9px] font-bold tracking-wider text-[#464555] uppercase">
                    {tc("sourcesMetric")}
                  </p>
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
                <div className="flex items-center gap-2 border-b border-[#e4e1ee] p-4">
                  <div className="min-w-0 flex-1">
                    <h2 className="text-base font-semibold text-[#1b1b24]">
                      {tc("citationDetailsTitle")}
                    </h2>
                    <p className="flex items-center gap-1 font-mono text-xs text-[#464555]">
                      <span
                        className="truncate"
                        title={
                          activeCitation.filename ?? tc("documentFallback")
                        }
                      >
                        {activeCitation.filename ?? tc("documentFallback")}
                      </span>
                      {activeCitation.page_number ? (
                        <span className="shrink-0">
                          {tc("citationPage", {
                            page: activeCitation.page_number,
                          })}
                        </span>
                      ) : null}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setActiveCitation(null)}
                    aria-label="Close citation detail"
                    className="shrink-0 cursor-pointer rounded-full p-1.5 text-[#464555] transition-colors hover:bg-[#f0ecf9]"
                  >
                    <span
                      className="material-symbols-outlined text-[20px]"
                      aria-hidden="true"
                    >
                      close
                    </span>
                  </button>
                </div>

                <div className="hide-scrollbar flex-1 overflow-y-auto bg-[#f5f2ff] p-4">
                  <div className="min-h-[300px] rounded-lg border border-[#c7c4d8] bg-white p-5 font-serif text-sm leading-relaxed text-[#1b1b24] shadow-md">
                    <div className="mb-4 flex items-end justify-between border-b pb-2 font-sans text-xs text-[#464555] italic">
                      <span
                        className="max-w-[70%] truncate"
                        title={
                          activeCitation.source_title ??
                          activeCitation.filename ??
                          "DOCUMENT"
                        }
                      >
                        {activeCitation.source_title ??
                          activeCitation.filename ??
                          "DOCUMENT"}
                      </span>
                      <span className="flex items-center gap-2">
                        {citationProviderLabel(activeCitation) ? (
                          <span className="rounded-full bg-[#f0ecf9] px-2 py-1 text-[10px] font-semibold text-[#5d58a8] uppercase">
                            {citationProviderLabel(activeCitation)}
                          </span>
                        ) : null}
                        {activeCitation.source_trust_status ? (
                          <span className="rounded-full bg-[#e8f6ee] px-2 py-1 text-[10px] font-semibold text-emerald-800 uppercase">
                            {activeCitation.source_trust_status}
                          </span>
                        ) : null}
                        {activeCitation.page_number ? (
                          <span>PAGE {activeCitation.page_number}</span>
                        ) : null}
                      </span>
                    </div>
                    <p className="mb-3 text-xs leading-relaxed opacity-40">
                      {tc("citationPassage")}
                    </p>
                    {activeCitation.source_section ||
                    activeCitation.source_last_synced_at ? (
                      <p className="mb-2 text-[11px] text-[#6a6780]">
                        {activeCitation.source_section ? (
                          <span>
                            {tc("citationSection", {
                              section: activeCitation.source_section,
                            })}
                          </span>
                        ) : null}
                        {activeCitation.source_section &&
                        activeCitation.source_last_synced_at ? (
                          <span> | </span>
                        ) : null}
                        {activeCitation.source_last_synced_at ? (
                          <span>
                            {tc("citationSynced", {
                              date: formatDate(
                                activeCitation.source_last_synced_at,
                              ),
                            })}
                          </span>
                        ) : null}
                      </p>
                    ) : null}
                    {activeCitation.text_snippet ? (
                      <div className="my-3 rounded-r border-l-4 border-[#3525cd] bg-[#e2dfff]/30 p-3">
                        <span className="mr-1 rounded bg-[#3525cd]/10 px-1 font-sans text-xs font-bold text-[#3525cd]">
                          CIT
                        </span>
                        <span className="font-bold">
                          {activeCitation.text_snippet}
                        </span>
                      </div>
                    ) : (
                      <p className="text-xs text-[#464555] italic">
                        {tc("snippetUnavailable")}
                      </p>
                    )}
                    <p className="mt-3 text-xs leading-relaxed opacity-40">
                      {tc("retrievalScore", {
                        score: formatScore(
                          activeCitation.rerank_score ??
                            activeCitation.similarity_score ??
                            activeCitation.score,
                        ),
                      })}
                    </p>
                  </div>
                </div>

                <div className="border-t border-[#e4e1ee] bg-white p-4">
                  {activeCitation.source_deep_link ? (
                    <a
                      href={activeCitation.source_deep_link}
                      target="_blank"
                      rel="noreferrer"
                      className="mb-2 flex w-full items-center justify-center gap-2 rounded-xl border border-[#d2cee6] bg-white px-4 py-3 text-sm font-semibold text-[#3e376f] transition-colors hover:bg-[#f5f3ff]"
                    >
                      <span
                        className="material-symbols-outlined text-[18px]"
                        aria-hidden="true"
                      >
                        open_in_new
                      </span>
                      {tc("openConnectedSource")}
                    </a>
                  ) : null}
                  {activeCitation.document_id ? (
                    <Link
                      href={
                        `/documents/${encodeURIComponent(activeCitation.document_id)}` +
                        `?chunk_id=${encodeURIComponent(activeCitation.chunk_id)}` +
                        (activeCitation.text_snippet
                          ? `&snippet=${encodeURIComponent(activeCitation.text_snippet)}`
                          : "") +
                        (activeCitation.page_number != null
                          ? `&page=${encodeURIComponent(String(activeCitation.page_number))}`
                          : "") +
                        `&back=${encodeURIComponent("/chat")}`
                      }
                      className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#3525cd] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8]"
                    >
                      <span
                        className="material-symbols-outlined text-[18px]"
                        aria-hidden="true"
                      >
                        open_in_new
                      </span>
                      {tc("jumpToSource")}
                    </Link>
                  ) : (
                    <p className="text-center text-xs text-[#777587]">
                      {tc("documentLinkUnavailable")}
                    </p>
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
                  {tc("contextModalTitle")}
                </h2>
                <p className="mt-1 text-xs text-[#6a6780]">
                  {tc("contextModalSubtitle")}
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
                {tc("close")}
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
                  placeholder={tc("contextSearchPlaceholder")}
                  className="h-10 w-full rounded-lg border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-sm text-[#2f2a46] ring-[#3525cd]/20 outline-none focus:ring"
                />
              </div>
            </div>
            <div className="hide-scrollbar max-h-[52vh] overflow-y-auto px-4 py-3">
              <div className="mb-4 rounded-xl border border-[#e8e5f3] bg-[#faf9ff] p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div>
                    <p className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                      {tc("collectionsTitle")}
                    </p>
                    <p className="text-xs text-[#6a6780]">
                      {tc("collectionsSubtitle")}
                    </p>
                  </div>
                  <span className="rounded-full bg-[#ece8ff] px-2 py-1 text-[10px] font-semibold text-[#3525cd]">
                    {tc("numSelected", { n: selectedCollectionIds.length })}
                  </span>
                </div>
                {collectionsListQuery.isLoading ? (
                  <LoadingState compact title={tc("loadingCollections")} />
                ) : collectionsListQuery.isError ? (
                  <ErrorState
                    compact
                    error={collectionsListQuery.error}
                    description={getApiErrorMessage(collectionsListQuery.error)}
                    onRetry={() => {
                      void collectionsListQuery.refetch();
                    }}
                  />
                ) : collections.length === 0 ? (
                  <p className="text-xs text-[#777587]">
                    {tc("noCollections")}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {collections.map((collection) => {
                      const collectionSelected = selectedCollectionIds.includes(
                        collection.collection_id,
                      );
                      return (
                        <button
                          key={collection.collection_id}
                          type="button"
                          onClick={() =>
                            toggleCollection(collection.collection_id)
                          }
                          className={`flex w-full items-start justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${
                            collectionSelected
                              ? "border-[#3525cd] bg-[#ece8ff]"
                              : "border-[#e2dff1] bg-white hover:bg-[#faf9ff]"
                          }`}
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-semibold text-[#2f2a46]">
                              {collection.name}
                            </span>
                            <span className="block text-[11px] text-[#6a6780]">
                              {collection.description ??
                                tc("collectionScopeHint")}
                            </span>
                          </span>
                          <span
                            className={`rounded-full px-2 py-1 text-[10px] font-semibold ${
                              collectionSelected
                                ? "bg-[#ece8ff] text-[#3525cd]"
                                : "bg-[#f1f0f5] text-[#6a6780]"
                            }`}
                          >
                            {collectionSelected
                              ? tc("collectionSelected")
                              : tc("collectionSelect")}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="mb-4 rounded-xl border border-[#e8e5f3] bg-[#faf9ff] p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div>
                    <p className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                      {tc("connectorSourcesTitle")}
                    </p>
                    <p className="text-xs text-[#6a6780]">
                      {tc("connectorSourcesSubtitle")}
                    </p>
                  </div>
                  <span className="rounded-full bg-[#ece8ff] px-2 py-1 text-[10px] font-semibold text-[#3525cd]">
                    {tc("numSelected", {
                      n:
                        selectedConnectorConnectionIds.length +
                        selectedProviderSourceIds.length,
                    })}
                  </span>
                </div>
                {connectorConnectionsQuery.isLoading ? (
                  <LoadingState compact title={tc("loadingConnectors")} />
                ) : connectorConnectionsQuery.isError ? (
                  <ErrorState
                    compact
                    error={connectorConnectionsQuery.error}
                    description={getApiErrorMessage(
                      connectorConnectionsQuery.error,
                    )}
                    onRetry={() => {
                      void connectorConnectionsQuery.refetch();
                    }}
                  />
                ) : connectorConnections.length === 0 ? (
                  <p className="text-xs text-[#777587]">{tc("noConnectors")}</p>
                ) : (
                  <div className="space-y-2">
                    {connectorConnections.map((connection) => {
                      const rootChips = buildConnectorRootChips(connection);
                      const connectionSelected =
                        selectedConnectorConnectionIds.includes(connection.id);
                      return (
                        <div
                          key={connection.id}
                          className="rounded-lg border border-[#e2dff1] bg-white p-3"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <button
                              type="button"
                              onClick={() =>
                                toggleConnectorConnection(connection.id)
                              }
                              className={`flex min-w-0 flex-1 items-start gap-2 text-left transition-colors ${
                                connectionSelected
                                  ? "text-[#3525cd]"
                                  : "text-[#2f2a46]"
                              }`}
                            >
                              <span
                                className={`material-symbols-outlined mt-0.5 text-[18px] ${connectionSelected ? "text-[#3525cd]" : "text-[#6a6780]"}`}
                                aria-hidden="true"
                              >
                                hub
                              </span>
                              <span className="min-w-0">
                                <span className="block text-sm font-semibold">
                                  {connection.display_name}
                                </span>
                                <span className="block text-[11px] text-[#6a6780]">
                                  {getConnectorProviderLabel(
                                    connection.provider_key,
                                  )}
                                  {connection.external_account_id
                                    ? ` · ${connection.external_account_id}`
                                    : ""}
                                </span>
                              </span>
                            </button>
                            <span
                              className={`rounded-full px-2 py-1 text-[10px] font-semibold ${
                                connectionSelected
                                  ? "bg-[#ece8ff] text-[#3525cd]"
                                  : "bg-[#f1f0f5] text-[#6a6780]"
                              }`}
                            >
                              {connectionSelected
                                ? tc("connectionSelected")
                                : tc("connectionSelect")}
                            </span>
                          </div>
                          {rootChips.length > 0 ? (
                            <div className="mt-2 flex flex-wrap gap-2">
                              {rootChips.map((root) => {
                                const selected =
                                  selectedProviderSourceIds.includes(
                                    root.label,
                                  );
                                return (
                                  <button
                                    key={root.id}
                                    type="button"
                                    onClick={() => {
                                      if (!connectionSelected) {
                                        toggleConnectorConnection(
                                          connection.id,
                                        );
                                      }
                                      toggleProviderSource(root.label);
                                    }}
                                    className={`rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${
                                      selected
                                        ? "border-[#3525cd] bg-[#ece8ff] text-[#3525cd]"
                                        : "border-[#d2cee6] bg-[#faf9ff] text-[#5f5a74] hover:border-[#b9b2dd] hover:bg-white"
                                    }`}
                                  >
                                    {root.label}
                                  </button>
                                );
                              })}
                            </div>
                          ) : (
                            <p className="mt-2 text-xs text-[#777587]">
                              {tc("useConnectionForAll")}
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {contextModalQuery.isLoading ? (
                <LoadingState compact title={tc("loadingDocuments")} />
              ) : contextModalQuery.isError ? (
                <ErrorState
                  compact
                  error={contextModalQuery.error}
                  description={getApiErrorMessage(contextModalQuery.error)}
                  onRetry={() => {
                    void contextModalQuery.refetch();
                  }}
                />
              ) : contextModalQuery.data?.items.length === 0 &&
                !contextSearchQuery.trim() ? (
                <EmptyState
                  compact
                  title={tc("noDocumentsAvailable")}
                  action={
                    <Link
                      href="/documents"
                      className="text-sm font-semibold text-[#3525cd] hover:underline"
                    >
                      {tc("goToDocuments")}
                    </Link>
                  }
                />
              ) : contextModalQuery.data?.items.length === 0 ? (
                <EmptyState
                  compact
                  title={tc("noDocumentsMatch")}
                  description={tc("noDocumentsMatchHint")}
                />
              ) : (
                <ul className="space-y-2">
                  {(contextModalQuery.data?.items ?? []).map((document) => (
                    <DocumentSelectorItem
                      key={document.document_id}
                      document={document}
                      checked={filteredSelectedDocumentIds.includes(
                        document.document_id,
                      )}
                      onToggle={() => toggleDocument(document.document_id)}
                      chunksMeta={tc("documentChunks", {
                        count: document.chunk_count,
                        date: formatDate(document.updated_at),
                      })}
                    />
                  ))}
                </ul>
              )}
            </div>
            {contextModalTotal > CONTEXT_MODAL_PAGE_SIZE ? (
              <div className="flex items-center justify-between border-t border-[#ece8f7] px-4 py-3 text-xs text-[#5f5a74]">
                <p>
                  {tc("contextShowingRange", {
                    start: contextPageStartIndex,
                    end: contextPageEndIndex,
                    total: contextModalTotal,
                  })}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setContextPage((previous) => Math.max(1, previous - 1));
                    }}
                    disabled={
                      boundedContextPage <= 1 || contextModalQuery.isFetching
                    }
                    className="rounded border border-[#d2cee6] px-2 py-1 font-semibold text-[#3525cd] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {tc("previous")}
                  </button>
                  <span className="font-mono text-[11px] text-[#4f4b63]">
                    {tc("contextPageOf", {
                      page: boundedContextPage,
                      total: contextPageCount,
                    })}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setContextPage((previous) =>
                        Math.min(contextPageCount, previous + 1),
                      );
                    }}
                    disabled={
                      boundedContextPage >= contextPageCount ||
                      contextModalQuery.isFetching
                    }
                    className="rounded border border-[#d2cee6] px-2 py-1 font-semibold text-[#3525cd] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {tc("next")}
                  </button>
                </div>
              </div>
            ) : null}
            <div className="flex items-center justify-between border-t border-[#e2dff1] bg-[#faf9ff] px-4 py-3">
              {scopeMode === "collection" ? (
                selectedCollectionIds.length > 0 ? (
                  <p className="text-xs text-[#5f5a74]">
                    {tc("collectionsSelected", {
                      n: selectedCollectionIds.length,
                    })}
                  </p>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-[#d7d4e8] bg-[#f0ecf9] px-2.5 py-1 text-xs font-semibold text-[#3525cd]">
                    <span
                      className="material-symbols-outlined text-[14px]"
                      aria-hidden="true"
                    >
                      folder_open
                    </span>
                    {tc("selectCollections")}
                  </span>
                )
              ) : scopeMode === "connectors" ? (
                hasConnectorScopeSelection ? (
                  <p className="text-xs text-[#5f5a74]">
                    {tc("connectorSourcesSelected", {
                      count: contextScopeItemCount,
                    })}
                  </p>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-[#d7d4e8] bg-[#f0ecf9] px-2.5 py-1 text-xs font-semibold text-[#3525cd]">
                    <span
                      className="material-symbols-outlined text-[14px]"
                      aria-hidden="true"
                    >
                      hub
                    </span>
                    {tc("selectConnectorSources")}
                  </span>
                )
              ) : filteredSelectedDocumentIds.length > 0 ? (
                <p className="text-xs text-[#5f5a74]">
                  {tc("documentsSelected", {
                    count: filteredSelectedDocumentIds.length,
                  })}
                </p>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-[#d7d4e8] bg-[#f0ecf9] px-2.5 py-1 text-xs font-semibold text-[#3525cd]">
                  <span
                    className="material-symbols-outlined text-[14px]"
                    aria-hidden="true"
                  >
                    check_circle
                  </span>
                  {tc("allFilesIncluded", { count: contextScopeItemCount })}
                </span>
              )}
              <button
                type="button"
                onClick={() => {
                  setIsContextModalOpen(false);
                  setContextSearchQuery("");
                  setContextPage(1);
                }}
                className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
              >
                {tc("done")}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {previewCitationSet ? (
        <DocumentPreviewModal
          citations={previewCitationSet.citations}
          initialIndex={previewCitationSet.initialIndex}
          onClose={() => setPreviewCitationSet(null)}
        />
      ) : null}

      {isShareModalOpen && activeSessionId ? (
        <ShareModal
          sessionId={activeSessionId}
          sessionTitle={activeSessionDisplayTitle}
          onClose={() => setIsShareModalOpen(false)}
        />
      ) : null}

      {answerShareMessageId ? (
        <AnswerShareModal
          messageId={answerShareMessageId}
          onClose={() => setAnswerShareMessageId(null)}
        />
      ) : null}

      {chatFeedbackEnabled && feedbackModalMessageId ? (
        <FeedbackModal
          existingReason={feedbackByMessageId[feedbackModalMessageId]?.reason}
          existingComment={feedbackByMessageId[feedbackModalMessageId]?.comment}
          isSubmitting={feedbackSubmitMutation.isPending}
          isDeleting={feedbackDeleteMutation.isPending}
          onSubmit={(reason, comment) => {
            feedbackSubmitMutation.mutate(
              {
                messageId: feedbackModalMessageId,
                rating: "down",
                reason,
                comment,
              },
              { onSuccess: () => setFeedbackModalMessageId(null) },
            );
          }}
          onDelete={() => {
            feedbackDeleteMutation.mutate(feedbackModalMessageId, {
              onSuccess: () => setFeedbackModalMessageId(null),
            });
          }}
          onClose={() => setFeedbackModalMessageId(null)}
        />
      ) : null}
    </>
  );
}

function DocumentSelectorItem({
  document,
  checked,
  onToggle,
  chunksMeta,
}: {
  document: DocumentListItemResponse;
  checked: boolean;
  onToggle: () => void;
  chunksMeta: string;
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
            {chunksMeta}
          </span>
        </span>
      </label>
    </li>
  );
}
