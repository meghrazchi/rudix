import type {
  DocumentDetailResponse,
  DocumentLifecycleTimelineStepResponse,
  DocumentStatus,
  DocumentStatusResponse,
  ReindexDocumentRequest,
} from "@/lib/api/documents";
import { isApiClientError } from "@/lib/api/errors";

type TimelineStepState = "completed" | "active" | "pending" | "failed";

type TimelineStep = {
  key: string;
  label: string;
  description: string;
  state: TimelineStepState;
  timestamp: string | null;
  documentId: string | null;
  logs: string[];
  pipelineRunId: string | null;
  pipelineType: string | null;
  durationMs: number | null;
  status: DocumentLifecycleTimelineStepResponse["status"] | null;
  outputs: Record<string, unknown> | null;
};

type DetailTab = "overview" | "chunks" | "errors" | "versions" | "metadata";
type MetadataCopyField = "document-id" | "checksum";

type ErrorRow = {
  key: string;
  type: string;
  severity: "critical" | "warning";
  message: string;
  timestamp: string | null;
  code: string | null;
};

type ReindexMutationInput = {
  payload?: ReindexDocumentRequest;
  label?: string;
  force?: boolean;
};

function buildLifecycleTimeline(
  detail: DocumentDetailResponse,
  labels: LifecycleLabels,
): TimelineStep[] {
  const backendTimeline = Array.isArray(detail.lifecycle_timeline)
    ? detail.lifecycle_timeline.map((step) =>
        fromBackendLifecycleTimelineStep(step, labels),
      )
    : [];
  const steps = backendTimeline.filter((step) => step.state !== "pending");

  const hasGraphStep = steps.some((s) => s.key === "extract_entities");
  const graphExtractionStatus = detail.graph_extraction_status;
  if (
    !hasGraphStep &&
    graphExtractionStatus &&
    graphExtractionStatus !== "skipped"
  ) {
    let state: TimelineStepState = "pending";
    if (graphExtractionStatus === "completed") state = "completed";
    else if (graphExtractionStatus === "failed") state = "failed";
    else if (graphExtractionStatus === "extracting") state = "active";
    if (state !== "pending") {
      steps.push({
        key: "extract_entities",
        label: labels.extract_entities,
        description: "",
        state,
        timestamp: null,
        documentId: detail.document_id,
        logs: [],
        pipelineRunId: null,
        pipelineType: null,
        durationMs: null,
        status:
          graphExtractionStatus === "extracting"
            ? "running"
            : graphExtractionStatus,
        outputs: null,
      });
    }
  }

  const hasReadyForChatStep = steps.some((s) => s.key === "ready_for_chat");
  if (detail.status === "indexed" && !hasReadyForChatStep) {
    steps.push({
      key: "ready_for_chat",
      label: labels.ready_for_chat,
      description: labels.ready_for_chat_description,
      state: "completed",
      timestamp: detail.updated_at ?? null,
      documentId: detail.document_id,
      logs: [],
      pipelineRunId: null,
      pipelineType: null,
      durationMs: null,
      status: "completed",
      outputs: null,
    });
  }

  return steps;
}

function fromBackendLifecycleTimelineStep(
  step: DocumentLifecycleTimelineStepResponse,
  labels: LifecycleLabels,
): TimelineStep {
  let state: TimelineStepState = "pending";
  if (step.status === "completed" || step.status === "skipped") {
    state = "completed";
  } else if (step.status === "running") {
    state = "active";
  } else if (step.status === "failed") {
    state = "failed";
  }

  return {
    key: step.step,
    label: normalizeLifecycleLabel(step.step, step.label, labels),
    description: step.description,
    state,
    timestamp: step.completed_at ?? step.started_at ?? null,
    documentId: step.document_id,
    logs: Array.isArray(step.logs) ? step.logs : [],
    pipelineRunId: step.pipeline_run_id ?? null,
    pipelineType: step.pipeline_type ?? null,
    durationMs: step.duration_ms ?? null,
    status: step.status,
    outputs: step.outputs ?? null,
  };
}

type LifecycleLabels = {
  extract: string;
  detect_ocr: string;
  ocr: string;
  chunk: string;
  embed: string;
  index: string;
  extract_entities: string;
  ready_for_chat: string;
  ready_for_chat_description: string;
};

function normalizeLifecycleLabel(
  stepKey: string,
  label: string,
  labels: LifecycleLabels,
): string {
  if (stepKey === "extract") return labels.extract;
  if (stepKey === "detect_ocr") return labels.detect_ocr;
  if (stepKey === "ocr") return labels.ocr;
  if (stepKey === "chunk") return labels.chunk;
  if (stepKey === "embed") return labels.embed;
  if (stepKey === "index") return labels.index;
  if (stepKey === "extract_entities") return labels.extract_entities;
  if (stepKey === "ready_for_chat") return labels.ready_for_chat;
  return label;
}

type OcrMetadata = {
  required: boolean;
  mode: string;
  status: string;
  languages: string[];
  pagesProcessed: number;
  pagesCompleted: number;
  pagesFailed: number;
  nativeTextPages: number;
  durationMs: number | null;
  warnings: string[];
};

function extractOcrMetadata(timeline: TimelineStep[]): OcrMetadata | null {
  const detectStep = timeline.find((s) => s.key === "detect_ocr");
  const ocrStep = timeline.find((s) => s.key === "ocr");

  if (!detectStep) return null;

  const detectOut = detectStep.outputs;
  const ocrOut = ocrStep?.outputs ?? null;

  const required = Boolean(detectOut?.requires_ocr ?? false);
  if (!required) {
    return {
      required: false,
      mode: String(detectOut?.mode ?? "text"),
      status: "not_required",
      languages: [],
      pagesProcessed: 0,
      pagesCompleted: 0,
      pagesFailed: 0,
      nativeTextPages: Number(detectOut?.native_text_pages ?? 0),
      durationMs: null,
      warnings: [],
    };
  }

  return {
    required,
    mode: String(ocrOut?.mode ?? detectOut?.mode ?? "unknown"),
    status: String(ocrOut?.status ?? "unknown"),
    languages: Array.isArray(ocrOut?.languages)
      ? (ocrOut.languages as string[])
      : [],
    pagesProcessed: Number(ocrOut?.pages_processed ?? 0),
    pagesCompleted: Number(ocrOut?.pages_completed ?? 0),
    pagesFailed: Number(ocrOut?.pages_failed ?? 0),
    nativeTextPages: Number(detectOut?.native_text_pages ?? 0),
    durationMs: ocrOut?.duration_ms != null ? Number(ocrOut.duration_ms) : null,
    warnings: Array.isArray(ocrOut?.warnings)
      ? (ocrOut.warnings as string[])
      : [],
  };
}

function deriveDetailStatus(
  detail: DocumentDetailResponse,
  liveStatus: DocumentStatusResponse | undefined,
): DocumentStatus {
  return liveStatus?.status ?? detail.status;
}

function isSafeNotFoundError(error: unknown): boolean {
  if (!isApiClientError(error)) {
    return false;
  }
  return error.status === 403 || error.status === 404;
}

function buildErrorRows(
  detail: DocumentDetailResponse,
  timeline: TimelineStep[],
  docProcessingLabel: string,
): ErrorRow[] {
  const rows: ErrorRow[] = [];

  if (detail.error_message) {
    rows.push({
      key: "document-error",
      type: detail.error_details?.stage ?? docProcessingLabel,
      severity: "critical",
      message: detail.error_details?.message ?? detail.error_message,
      timestamp: detail.updated_at,
      code: detail.error_details?.code ?? null,
    });
  }

  timeline.forEach((step) => {
    step.logs.forEach((line, index) => {
      const normalizedLine = line.trim();
      if (!normalizedLine) {
        return;
      }
      const isCritical =
        step.state === "failed" || /error|failed|fatal/i.test(normalizedLine);
      rows.push({
        key: `${step.key}-${index}`,
        type: step.label,
        severity: isCritical ? "critical" : "warning",
        message: normalizedLine,
        timestamp: step.timestamp,
        code: null,
      });
    });
  });

  return rows;
}

function severityBadgeClass(value: ErrorRow["severity"]): string {
  if (value === "critical") {
    return "bg-rose-100 text-rose-700";
  }
  return "bg-amber-100 text-amber-700";
}

type RecMessages = {
  retryIndexing: string;
  openPipeline: string;
  smallerChunks: string;
  noErrors: string;
};

function deriveRecommendations(
  detail: DocumentDetailResponse,
  timeline: TimelineStep[],
  rec: RecMessages,
): string[] {
  const recommendations: string[] = [];

  if (detail.error_details?.retryable) {
    recommendations.push(rec.retryIndexing);
  }
  if (
    timeline.some(
      (step) =>
        step.state === "failed" ||
        step.logs.some((line) => /error|failed|timeout/i.test(line)),
    )
  ) {
    recommendations.push(rec.openPipeline);
  }
  if (detail.page_count && detail.page_count > 100) {
    recommendations.push(rec.smallerChunks);
  }
  if (recommendations.length === 0) {
    recommendations.push(rec.noErrors);
  }

  return recommendations;
}

export {
  buildErrorRows,
  buildLifecycleTimeline,
  deriveDetailStatus,
  deriveRecommendations,
  extractOcrMetadata,
  isSafeNotFoundError,
  severityBadgeClass,
};
export type {
  DetailTab,
  ErrorRow,
  LifecycleLabels,
  MetadataCopyField,
  OcrMetadata,
  RecMessages,
  ReindexMutationInput,
  TimelineStep,
  TimelineStepState,
};
