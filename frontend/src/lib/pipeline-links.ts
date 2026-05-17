export type PipelineRunType = "document.process" | "chat.answer" | "evaluation.run";

type PipelineQueryReader = Pick<URLSearchParams, "get">;

export type PipelineExplorerLinkParams = {
  runId?: string | null;
  runType?: PipelineRunType | string | null;
  documentId?: string | null;
  chatMessageId?: string | null;
  evaluationRunId?: string | null;
};

export type PipelineExplorerQueryContext = {
  runId: string | null;
  runType: PipelineRunType | null;
  documentId: string | null;
  chatMessageId: string | null;
  evaluationRunId: string | null;
  hasContext: boolean;
};

const PIPELINE_RUN_TYPES: ReadonlySet<PipelineRunType> = new Set([
  "document.process",
  "chat.answer",
  "evaluation.run",
]);

function normalizeNonEmptyString(value: string | null | undefined): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function normalizePipelineRunType(value: string | null | undefined): PipelineRunType | null {
  const normalized = normalizeNonEmptyString(value);
  if (!normalized) {
    return null;
  }
  return PIPELINE_RUN_TYPES.has(normalized as PipelineRunType) ? (normalized as PipelineRunType) : null;
}

export function buildPipelineExplorerHref(params: PipelineExplorerLinkParams): string {
  const query = new URLSearchParams();

  const runId = normalizeNonEmptyString(params.runId);
  const runType = normalizePipelineRunType(params.runType);
  const documentId = normalizeNonEmptyString(params.documentId);
  const chatMessageId = normalizeNonEmptyString(params.chatMessageId);
  const evaluationRunId = normalizeNonEmptyString(params.evaluationRunId);

  if (runId) {
    query.set("run_id", runId);
  }
  if (runType) {
    query.set("run_type", runType);
  }
  if (documentId) {
    query.set("document_id", documentId);
  }
  if (chatMessageId) {
    query.set("chat_message_id", chatMessageId);
  }
  if (evaluationRunId) {
    query.set("evaluation_run_id", evaluationRunId);
  }

  const encoded = query.toString();
  if (!encoded) {
    return "/rag-pipeline";
  }
  return `/rag-pipeline?${encoded}`;
}

export function parsePipelineExplorerQuery(searchParams: PipelineQueryReader): PipelineExplorerQueryContext {
  const runId = normalizeNonEmptyString(searchParams.get("run_id")) ??
    normalizeNonEmptyString(searchParams.get("pipeline_run_id"));
  const runType = normalizePipelineRunType(searchParams.get("run_type")) ??
    normalizePipelineRunType(searchParams.get("pipeline_type"));
  const documentId = normalizeNonEmptyString(searchParams.get("document_id"));
  const chatMessageId = normalizeNonEmptyString(searchParams.get("chat_message_id"));
  const evaluationRunId = normalizeNonEmptyString(searchParams.get("evaluation_run_id"));

  return {
    runId,
    runType,
    documentId,
    chatMessageId,
    evaluationRunId,
    hasContext: Boolean(runId || documentId || chatMessageId || evaluationRunId),
  };
}
