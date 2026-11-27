import type { InfiniteData } from "@tanstack/react-query";

import type { AgentRunCreateResponse, AgentRuntimeMode } from "@/lib/api/agent";
import type {
  ChatCitationResponse,
  ChatConfidenceExplanationResponse,
  ChatConflictPairResponse,
  ChatDebugResponse,
  ChatSessionListResponse,
} from "@/lib/api/chat";
import type { AnswerTrustMetadataResponse } from "@/lib/api/trust_metadata";

export const DRAFT_SESSION_KEY = "__draft__";

export type ChatScopeMode =
  | "all"
  | "collection"
  | "documents"
  | "connectors"
  | "none";
export type AnswerLanguageMode =
  | "auto"
  | "same_as_question"
  | "en"
  | "de"
  | "es"
  | "fr";
export type ChatSessionListItem = ChatSessionListResponse["items"][number];
export type ChatSessionListInfiniteData = InfiniteData<
  ChatSessionListResponse,
  number
>;

export function parsePositiveIntegerEnv(
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

export const MAX_INDEXED_DOCS = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_MAX_INDEXED_DOCS,
  200,
);
export const SESSION_LIST_LIMIT = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_SESSION_LIST_LIMIT,
  10,
);
export const CONTEXT_MODAL_PAGE_SIZE = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_CONTEXT_MODAL_PAGE_SIZE,
  8,
);
export const SESSION_TITLE_MAX_LENGTH = 120;
export const MIN_TOP_K = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_TOP_K_MIN,
  1,
);
export const MAX_TOP_K = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_TOP_K_MAX,
  20,
);
export const SCOPE_DOCUMENT_PICKER_LIMIT = 30;
export const DEFAULT_TOP_K = Math.min(
  Math.max(
    parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_DEFAULT, 5),
    MIN_TOP_K,
  ),
  MAX_TOP_K,
);
export const AGENT_RUN_POLL_INTERVAL_MS = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_AGENT_RUN_POLL_INTERVAL_MS,
  3_000,
);
export const AGENTIC_CHAT_ENABLED =
  process.env.NEXT_PUBLIC_CHAT_AGENTIC_ENABLED !== "false";
export const DEFAULT_AGENTIC_MODE =
  process.env.NEXT_PUBLIC_CHAT_AGENTIC_DEFAULT === "true";
export const CHAT_SETTINGS_STORAGE_KEY = "rudix.chat.settings.v1";
export const STREAMING_PLACEHOLDER_ENABLED =
  process.env.NEXT_PUBLIC_CHAT_STREAMING_ENABLED === "true";
export const CHAT_WEBSOCKET_ENABLED =
  process.env.NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED === "true";
/** Threads with more turns than this are virtualised (R05-11). */
export const CHAT_VIRTUALIZE_MIN_TURNS = parsePositiveIntegerEnv(
  process.env.NEXT_PUBLIC_CHAT_VIRTUALIZE_MIN_TURNS,
  50,
);
/** Messages per history page, newest page first (R05-11). */
export const CHAT_HISTORY_PAGE_SIZE = Math.min(
  parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_HISTORY_PAGE_SIZE, 100),
  500,
);

export type ChatTurn = {
  question: string;
  response: {
    message_id: string;
    answer: string;
    confidence_score: number;
    confidence_category: "low" | "medium" | "high";
    confidence_explanation: ChatConfidenceExplanationResponse | null;
    not_found: boolean;
    citation_validation_failed: boolean;
    verification_failed: boolean;
    agreement_level: "full" | "partial" | "conflicting";
    conflict_detected: boolean;
    conflict_summary: string | null;
    conflicting_document_ids: string[];
    preferred_document_ids: string[];
    conflict_pairs: ChatConflictPairResponse[];
    source_freshness_warning: boolean;
    source_freshness_warning_reason: string | null;
    policy_applied: boolean;
    policy_outcome: string | null;
    policy_violated_rules: string[];
    policy_warning_flags: string[];
    policy_disclaimer: string | null;
    debug: ChatDebugResponse | null;
    citations: ChatCitationResponse[];
    trust_metadata?: AnswerTrustMetadataResponse | null;
    created_at: string;
    agent_run_id: string | null;
    agent_run_status: string | null;
    agent_run_error: AgentRunCreateResponse["run"]["error"] | null;
    agent_mode: AgentRuntimeMode | null;
    scope_label: string | null;
  };
};
