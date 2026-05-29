import type {
  EvaluationQuestionResponse,
  EvaluationRunDetailResponse,
  EvaluationRunResultResponse,
  EvaluationSetResponse,
} from "@/lib/api/evaluations";

export type EvaluationRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "unknown";

export type EvaluationRunListItem = {
  runId: string;
  runName: string;
  datasetId: string;
  datasetName: string;
  status: EvaluationRunStatus;
  statusLabel: string;
  score: number | null;
  regressions: number | null;
  startedBy: string | null;
  passRate: number | null;
  citationAccuracy: number | null;
  retrievalHitRate: number | null;
  latencyMsAverage: number | null;
  costUsdTotal: number | null;
  durationMs: number | null;
  startedAt: string | null;
  completedAt: string | null;
  createdAt: string;
  updatedAt: string;
  isComparisonAvailable: boolean;
  source: "live" | "history";
};

export type EvaluationRunHistoryRecord = {
  runId: string;
  runName: string;
  datasetId: string;
  datasetName: string;
  status: EvaluationRunStatus;
  score: number | null;
  regressions: number | null;
  startedBy: string | null;
  passRate: number | null;
  citationAccuracy: number | null;
  retrievalHitRate: number | null;
  latencyMsAverage: number | null;
  costUsdTotal: number | null;
  durationMs: number | null;
  startedAt: string | null;
  completedAt: string | null;
  createdAt: string;
  updatedAt: string;
  isComparisonAvailable: boolean;
};

export type RunFilters = {
  query: string;
  status: "all" | EvaluationRunStatus;
  datasetId: "all" | string;
  owner: "all" | string;
  dateFrom: string;
  dateTo: string;
  sortBy:
    | "created_desc"
    | "created_asc"
    | "score_desc"
    | "score_asc"
    | "status_asc";
};

export type ResultFilters = {
  query: string;
  status: "all" | "failed" | "completed" | "low_quality";
  sortBy:
    | "created_desc"
    | "latency_desc"
    | "latency_asc"
    | "quality_asc"
    | "quality_desc";
};

export type CitationReference = {
  chunkId: string | null;
  documentId: string | null;
  filename: string | null;
  pageNumber: number | null;
  score: number | null;
  snippet: string | null;
};

export type EvaluationCaseView = {
  result: EvaluationRunResultResponse;
  expectedAnswer: string | null;
  expectedDocumentId: string | null;
  expectedPageNumber: number | null;
  qualityScore: number | null;
  confidenceScore: number | null;
  citations: CitationReference[];
  isLowQuality: boolean;
};

export type RunComparison = {
  available: boolean;
  baselineLabel: string;
  latestLabel: string;
  baselineScore: number | null;
  latestScore: number | null;
  delta: number | null;
  message: string;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function asString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeRate(value: number | null): number | null {
  if (value == null || !Number.isFinite(value)) {
    return null;
  }
  if (value > 1 && value <= 100) {
    return Math.max(0, Math.min(1, value / 100));
  }
  return Math.max(0, Math.min(1, value));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "N/A";
  }

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export function formatDuration(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value < 0) {
    return "N/A";
  }

  const ms = Math.round(value);
  if (ms < 1000) {
    return `${ms} ms`;
  }

  const totalSeconds = Math.round(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

export function formatPercent(value: number | null | undefined): string {
  const normalized = normalizeRate(value ?? null);
  if (normalized == null) {
    return "N/A";
  }
  return `${(normalized * 100).toFixed(1)}%`;
}

export function formatCurrency(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "N/A";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(Math.max(0, value));
}

export function formatInteger(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "N/A";
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(
    Math.round(value),
  );
}

function resolveSummaryNumber(
  summary: Record<string, unknown> | null,
  keys: string[],
): number | null {
  if (!summary) {
    return null;
  }

  for (const key of keys) {
    const value = asNumber(summary[key]);
    if (value != null) {
      return value;
    }
  }

  return null;
}

function normalizeRunStatus(
  status: string | null | undefined,
): EvaluationRunStatus {
  const normalized = status?.trim().toLowerCase() ?? "";
  if (normalized === "queued") {
    return "queued";
  }
  if (normalized === "running") {
    return "running";
  }
  if (normalized === "completed") {
    return "completed";
  }
  if (normalized === "failed") {
    return "failed";
  }
  if (normalized === "cancelled" || normalized === "canceled") {
    return "cancelled";
  }
  return "unknown";
}

export function runStatusLabel(status: EvaluationRunStatus): string {
  if (status === "queued") {
    return "Queued";
  }
  if (status === "running") {
    return "Running";
  }
  if (status === "completed") {
    return "Completed";
  }
  if (status === "failed") {
    return "Failed";
  }
  if (status === "cancelled") {
    return "Cancelled";
  }
  return "Unknown";
}

export function runStatusScreenReaderText(status: EvaluationRunStatus): string {
  if (status === "queued") {
    return "Run is queued";
  }
  if (status === "running") {
    return "Run is currently running";
  }
  if (status === "completed") {
    return "Run completed successfully";
  }
  if (status === "failed") {
    return "Run failed";
  }
  if (status === "cancelled") {
    return "Run was cancelled";
  }
  return "Run status unavailable";
}

function resolveRunScore(
  summary: Record<string, unknown> | null,
): number | null {
  const score =
    resolveSummaryNumber(summary, [
      "overall_score",
      "quality_score",
      "faithfulness_score",
      "answer_relevance_score",
      "citation_accuracy_score",
      "retrieval_hit_rate",
    ]) ?? null;
  return normalizeRate(score);
}

function resolveRunRegressions(
  summary: Record<string, unknown> | null,
): number | null {
  const direct = resolveSummaryNumber(summary, [
    "regressions_count",
    "regression_count",
    "regression_total",
  ]);
  if (direct != null) {
    return Math.max(0, Math.round(direct));
  }

  const delta =
    resolveSummaryNumber(summary, [
      "score_delta",
      "quality_score_delta",
      "baseline_delta",
    ]) ?? null;
  if (delta == null || delta >= 0) {
    return null;
  }

  return 1;
}

function resolveStartedBy(config: Record<string, unknown>): string | null {
  return (
    asString(config.started_by) ??
    asString(config.started_by_email) ??
    asString(config.actor_email) ??
    asString(config.triggered_by) ??
    null
  );
}

function resolveRunName(
  config: Record<string, unknown>,
  runId: string,
): string {
  return (
    asString(config.run_name) ??
    asString(config.name) ??
    asString(config.label) ??
    `Run ${runId.slice(0, 8)}`
  );
}

function resolveDurationMs(
  startedAt: string | null,
  completedAt: string | null,
): number | null {
  if (!startedAt || !completedAt) {
    return null;
  }

  const started = Date.parse(startedAt);
  const completed = Date.parse(completedAt);
  if (!Number.isFinite(started) || !Number.isFinite(completed)) {
    return null;
  }

  return Math.max(0, completed - started);
}

function resolvePassRate(
  summary: Record<string, unknown> | null,
  results: EvaluationRunDetailResponse["results"],
): number | null {
  const success = resolveSummaryNumber(summary, ["question_success_count"]);
  const total =
    resolveSummaryNumber(summary, ["question_total_count"]) ?? results.total;

  if (success == null || total == null || total <= 0) {
    return null;
  }

  return Math.max(0, Math.min(1, success / total));
}

function resolveComparisonAvailable(
  summary: Record<string, unknown> | null,
): boolean {
  if (!summary) {
    return false;
  }

  const comparison = asRecord(summary.comparison);
  if (comparison) {
    return true;
  }

  return (
    resolveSummaryNumber(summary, [
      "baseline_score",
      "score_delta",
      "quality_score_delta",
      "latest_score",
    ]) != null
  );
}

export function buildRunListItemFromDetail(params: {
  run: EvaluationRunDetailResponse;
  dataset: EvaluationSetResponse | null;
  source: "live" | "history";
}): EvaluationRunListItem {
  const summary = asRecord(params.run.summary);
  const config = asRecord(params.run.config) ?? {};
  const runId = params.run.evaluation_run_id;

  return {
    runId,
    runName: resolveRunName(config, runId),
    datasetId: params.run.evaluation_set_id,
    datasetName:
      params.dataset?.name ?? `Set ${params.run.evaluation_set_id.slice(0, 8)}`,
    status: normalizeRunStatus(params.run.status),
    statusLabel: runStatusLabel(normalizeRunStatus(params.run.status)),
    score: resolveRunScore(summary),
    regressions: resolveRunRegressions(summary),
    startedBy: resolveStartedBy(config),
    passRate: resolvePassRate(summary, params.run.results),
    citationAccuracy: normalizeRate(
      resolveSummaryNumber(summary, ["citation_accuracy_score"]),
    ),
    retrievalHitRate: normalizeRate(
      resolveSummaryNumber(summary, ["retrieval_hit_rate", "retrieval_score"]),
    ),
    latencyMsAverage: resolveSummaryNumber(summary, ["latency_ms_average"]),
    costUsdTotal: resolveSummaryNumber(summary, ["cost_usd_total"]),
    durationMs:
      resolveDurationMs(
        params.run.started_at ?? null,
        params.run.completed_at ?? null,
      ) ?? resolveSummaryNumber(summary, ["latency_ms_total"]),
    startedAt: params.run.started_at ?? null,
    completedAt: params.run.completed_at ?? null,
    createdAt: params.run.created_at,
    updatedAt: params.run.updated_at,
    isComparisonAvailable: resolveComparisonAvailable(summary),
    source: params.source,
  };
}

function compareDateDescending(left: string, right: string): number {
  const leftTs = Date.parse(left);
  const rightTs = Date.parse(right);
  const safeLeft = Number.isFinite(leftTs) ? leftTs : 0;
  const safeRight = Number.isFinite(rightTs) ? rightTs : 0;
  return safeRight - safeLeft;
}

function matchesDateRange(value: string, from: string, to: string): boolean {
  if (!from && !to) {
    return true;
  }

  const target = Date.parse(value);
  if (!Number.isFinite(target)) {
    return false;
  }

  const fromTs = from
    ? Date.parse(`${from}T00:00:00.000Z`)
    : Number.NEGATIVE_INFINITY;
  const toTs = to
    ? Date.parse(`${to}T23:59:59.999Z`)
    : Number.POSITIVE_INFINITY;

  return target >= fromTs && target <= toTs;
}

export function filterAndSortRuns(
  runs: EvaluationRunListItem[],
  filters: RunFilters,
): EvaluationRunListItem[] {
  const query = filters.query.trim().toLowerCase();

  const filtered = runs.filter((run) => {
    const runMatchesQuery =
      query.length === 0 ||
      run.runName.toLowerCase().includes(query) ||
      run.runId.toLowerCase().includes(query) ||
      run.datasetName.toLowerCase().includes(query);

    if (!runMatchesQuery) {
      return false;
    }

    if (filters.status !== "all" && run.status !== filters.status) {
      return false;
    }

    if (filters.datasetId !== "all" && run.datasetId !== filters.datasetId) {
      return false;
    }

    if (filters.owner !== "all") {
      const owner = run.startedBy ?? "unavailable";
      if (owner !== filters.owner) {
        return false;
      }
    }

    if (!matchesDateRange(run.createdAt, filters.dateFrom, filters.dateTo)) {
      return false;
    }

    return true;
  });

  return [...filtered].sort((left, right) => {
    if (filters.sortBy === "created_asc") {
      return compareDateDescending(right.createdAt, left.createdAt);
    }
    if (filters.sortBy === "score_desc") {
      const leftScore = left.score ?? -1;
      const rightScore = right.score ?? -1;
      if (rightScore !== leftScore) {
        return rightScore - leftScore;
      }
      return compareDateDescending(left.createdAt, right.createdAt);
    }
    if (filters.sortBy === "score_asc") {
      const leftScore = left.score ?? 2;
      const rightScore = right.score ?? 2;
      if (leftScore !== rightScore) {
        return leftScore - rightScore;
      }
      return compareDateDescending(left.createdAt, right.createdAt);
    }
    if (filters.sortBy === "status_asc") {
      const byStatus = left.statusLabel.localeCompare(right.statusLabel);
      if (byStatus !== 0) {
        return byStatus;
      }
      return compareDateDescending(left.createdAt, right.createdAt);
    }
    return compareDateDescending(left.createdAt, right.createdAt);
  });
}

function extractCitationsFromDetails(
  details: Record<string, unknown>,
): CitationReference[] {
  const directList = Array.isArray(details.citations)
    ? details.citations
    : Array.isArray(asRecord(details.context)?.citations)
      ? (asRecord(details.context)?.citations as unknown[])
      : [];

  const citations: CitationReference[] = [];
  for (const item of directList) {
    const row = asRecord(item);
    if (!row) {
      continue;
    }

    citations.push({
      chunkId: asString(row.chunk_id),
      documentId: asString(row.document_id),
      filename: asString(row.filename),
      pageNumber: asNumber(row.page_number),
      score: asNumber(row.score) ?? asNumber(row.similarity_score),
      snippet: asString(row.text_snippet) ?? asString(row.snippet),
    });
  }

  return citations;
}

function scoreForResult(result: EvaluationRunResultResponse): number | null {
  const values = [
    normalizeRate(result.faithfulness_score ?? null),
    normalizeRate(result.answer_relevance_score ?? null),
    normalizeRate(result.citation_accuracy_score ?? null),
    normalizeRate(result.retrieval_score ?? null),
  ].filter((value): value is number => value != null);

  if (values.length === 0) {
    return null;
  }

  return Math.max(
    0,
    Math.min(1, values.reduce((sum, value) => sum + value, 0) / values.length),
  );
}

function confidenceForResult(
  result: EvaluationRunResultResponse,
): number | null {
  const details = asRecord(result.details);
  const metrics = asRecord(result.metrics);

  return normalizeRate(
    asNumber(metrics?.confidence_score) ??
      asNumber(details?.confidence_score) ??
      asNumber(metrics?.confidence) ??
      asNumber(details?.confidence),
  );
}

function expectedByQuestionId(
  questions: EvaluationQuestionResponse[],
): Map<string, EvaluationQuestionResponse> {
  const map = new Map<string, EvaluationQuestionResponse>();
  for (const question of questions) {
    map.set(question.evaluation_question_id, question);
  }
  return map;
}

export function buildCaseViews(params: {
  results: EvaluationRunResultResponse[];
  questions: EvaluationQuestionResponse[];
  lowScoreThreshold: number;
}): EvaluationCaseView[] {
  const questionMap = expectedByQuestionId(params.questions);

  return params.results.map((result) => {
    const expected = questionMap.get(result.evaluation_question_id);
    const qualityScore = scoreForResult(result);
    const details = asRecord(result.details) ?? {};

    return {
      result,
      expectedAnswer: expected?.expected_answer ?? null,
      expectedDocumentId: expected?.expected_document_id ?? null,
      expectedPageNumber: expected?.expected_page_number ?? null,
      qualityScore,
      confidenceScore: confidenceForResult(result),
      citations: extractCitationsFromDetails(details),
      isLowQuality:
        qualityScore != null &&
        qualityScore < Math.max(0, Math.min(1, params.lowScoreThreshold)),
    };
  });
}

export function filterAndSortCaseViews(
  rows: EvaluationCaseView[],
  filters: ResultFilters,
): EvaluationCaseView[] {
  const query = filters.query.trim().toLowerCase();

  const filtered = rows.filter((row) => {
    const status = row.result.status.trim().toLowerCase();
    const isFailed = status === "failed";
    const isCompleted = status === "completed";

    if (filters.status === "failed" && !isFailed) {
      return false;
    }
    if (filters.status === "completed" && !isCompleted) {
      return false;
    }
    if (filters.status === "low_quality" && !row.isLowQuality) {
      return false;
    }

    if (query.length === 0) {
      return true;
    }

    return (
      row.result.question.toLowerCase().includes(query) ||
      (row.result.generated_answer ?? "").toLowerCase().includes(query) ||
      (row.expectedAnswer ?? "").toLowerCase().includes(query) ||
      row.result.evaluation_result_id.toLowerCase().includes(query)
    );
  });

  return [...filtered].sort((left, right) => {
    if (filters.sortBy === "latency_desc") {
      return (right.result.latency_ms ?? -1) - (left.result.latency_ms ?? -1);
    }
    if (filters.sortBy === "latency_asc") {
      return (
        (left.result.latency_ms ?? Number.MAX_SAFE_INTEGER) -
        (right.result.latency_ms ?? Number.MAX_SAFE_INTEGER)
      );
    }
    if (filters.sortBy === "quality_asc") {
      return (left.qualityScore ?? 2) - (right.qualityScore ?? 2);
    }
    if (filters.sortBy === "quality_desc") {
      return (right.qualityScore ?? -1) - (left.qualityScore ?? -1);
    }

    return compareDateDescending(
      left.result.created_at,
      right.result.created_at,
    );
  });
}

export function buildRunComparison(summaryValue: unknown): RunComparison {
  const summary = asRecord(summaryValue);
  const comparison = asRecord(summary?.comparison);

  const baselineScore = normalizeRate(
    asNumber(comparison?.baseline_score) ??
      resolveSummaryNumber(summary, [
        "baseline_score",
        "comparison_baseline_score",
      ]),
  );
  const latestScore = normalizeRate(
    asNumber(comparison?.latest_score) ??
      resolveSummaryNumber(summary, [
        "latest_score",
        "overall_score",
        "quality_score",
      ]),
  );
  const delta = normalizeRate(
    asNumber(comparison?.score_delta) ??
      resolveSummaryNumber(summary, [
        "score_delta",
        "quality_score_delta",
        "baseline_delta",
      ]),
  );

  if (baselineScore == null && latestScore == null && delta == null) {
    return {
      available: false,
      baselineLabel: "Baseline",
      latestLabel: "Latest",
      baselineScore: null,
      latestScore: null,
      delta: null,
      message:
        "Baseline comparison is not available for this run yet. Configure baseline tracking in the backend to enable this panel.",
    };
  }

  const baselineLabel =
    asString(comparison?.baseline_label) ??
    asString(summary?.baseline_label) ??
    "Baseline";
  const latestLabel =
    asString(comparison?.latest_label) ??
    asString(summary?.latest_label) ??
    "Latest";

  return {
    available: true,
    baselineLabel,
    latestLabel,
    baselineScore,
    latestScore,
    delta,
    message:
      "Comparison metrics are sourced from the run summary payload. Missing values are shown as unavailable.",
  };
}
