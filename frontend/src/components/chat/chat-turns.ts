import type { AgentRunCreateResponse } from "@/lib/api/agent";
import type {
  ChatCitationResponse,
  ChatQueryResponse,
  ChatSessionMessageResponse,
} from "@/lib/api/chat";
import type { ExportTurn } from "@/lib/export-utils";

import { DRAFT_SESSION_KEY, type ChatTurn } from "@/components/chat/chat-types";

export function toObject(value: unknown): Record<string, unknown> {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

export function toStringOrNull(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function toNumberOrNull(value: unknown): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return value;
}

export function toSessionDisplayTitle(
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

export function toConfidenceCategory(
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

export function normalizeAgentCitation(
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

export function activeThreadKey(sessionId: string | null): string {
  return sessionId ?? DRAFT_SESSION_KEY;
}

export function toTurnResponseFromQuery(
  response: ChatQueryResponse,
  scopeLabel: string | null = null,
): ChatTurn["response"] {
  return {
    message_id: response.message_id,
    answer: response.answer,
    confidence_score: response.confidence_score,
    confidence_category: response.confidence_category,
    confidence_explanation: response.confidence_explanation ?? null,
    not_found: response.not_found,
    citation_validation_failed: response.citation_validation_failed ?? false,
    verification_failed: response.verification_failed ?? false,
    agreement_level: response.agreement_level ?? "full",
    conflict_detected: response.conflict_detected ?? false,
    conflict_summary: response.conflict_summary ?? null,
    conflicting_document_ids: response.conflicting_document_ids ?? [],
    preferred_document_ids: response.preferred_document_ids ?? [],
    conflict_pairs: response.conflict_pairs ?? [],
    source_freshness_warning: response.source_freshness_warning ?? false,
    source_freshness_warning_reason:
      response.source_freshness_warning_reason ?? null,
    policy_applied: response.policy_applied ?? false,
    policy_outcome: response.policy_outcome ?? null,
    policy_violated_rules: response.policy_violated_rules ?? [],
    policy_warning_flags: response.policy_warning_flags ?? [],
    policy_disclaimer: response.policy_disclaimer ?? null,
    debug: response.debug ?? null,
    citations: response.citations ?? [],
    trust_metadata: response.trust_metadata ?? null,
    created_at: response.created_at,
    agent_run_id: null,
    agent_run_status: null,
    agent_run_error: null,
    agent_mode: null,
    scope_label: scopeLabel,
  };
}

export function toTurnResponseFromHistoryMessage(
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
    confidence_explanation: null,
    not_found: false,
    citation_validation_failed: false,
    verification_failed: false,
    agreement_level: agreementLevel,
    conflict_detected: conflictDetected,
    conflict_summary: conflictSummary,
    conflicting_document_ids: conflictDetected ? conflictingDocumentIds : [],
    preferred_document_ids: conflictDetected ? preferredDocumentIds : [],
    conflict_pairs: conflictDetected ? conflictPairs : [],
    source_freshness_warning: false,
    source_freshness_warning_reason: null,
    policy_applied: false,
    policy_outcome: null,
    policy_violated_rules: [],
    policy_warning_flags: [],
    policy_disclaimer: null,
    debug: null,
    citations: message.citations ?? [],
    trust_metadata:
      (messageRecord.trust_metadata as
        | import("@/lib/api/trust_metadata").AnswerTrustMetadataResponse
        | null
        | undefined) ?? null,
    created_at: message.created_at,
    agent_run_id: null,
    agent_run_status: null,
    agent_run_error: null,
    agent_mode: null,
    scope_label: null,
  };
}

export function toTurnResponseFromAgentRun(
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
    confidence_explanation: null,
    not_found: Boolean(outcome?.not_found),
    citation_validation_failed: false,
    verification_failed: false,
    agreement_level: "full",
    conflict_detected: false,
    conflict_summary: null,
    conflicting_document_ids: [],
    preferred_document_ids: [],
    conflict_pairs: [],
    source_freshness_warning: false,
    source_freshness_warning_reason: null,
    policy_applied: false,
    policy_outcome: null,
    policy_violated_rules: [],
    policy_warning_flags: [],
    policy_disclaimer: null,
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

export function toExportTurns(turns: ChatTurn[]): ExportTurn[] {
  return turns.map((t) => ({
    question: t.question,
    answer: t.response.answer,
    citations: t.response.citations,
    created_at: t.response.created_at,
  }));
}

export function buildTurnsFromSessionMessages(
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
