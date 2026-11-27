import type { ChatDebugResponse } from "@/lib/api/chat";
import {
  buildPipelineExplorerHref,
  normalizePipelineRunType,
  type PipelineRunType,
} from "@/lib/pipeline-links";

import type { ChatTurn } from "@/components/chat/chat-types";

export function agentRunStatusClass(status: string): string {
  if (status === "completed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "failed" || status === "cancelled") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
}

export function isTerminalAgentRunStatus(status: string): boolean {
  return (
    status === "completed" || status === "failed" || status === "cancelled"
  );
}

export function readDebugString(
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

export function getChatRunType(
  debug: ChatDebugResponse | null,
): PipelineRunType {
  const debugRunType = normalizePipelineRunType(
    readDebugString(debug, "pipeline_type") ??
      readDebugString(debug, "run_type"),
  );
  return debugRunType ?? "chat.answer";
}

export function buildChatPipelineHref(
  response: ChatTurn["response"],
): string | null {
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

export function isAdminLikeRole(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

export function replaceSessionParamInUrl(sessionId: string | null): void {
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
