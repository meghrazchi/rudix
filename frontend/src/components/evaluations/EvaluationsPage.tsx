"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import {
  createEvaluationQuestion,
  createEvaluationSet,
  getEvaluationRun,
  listEvaluationQuestions,
  listEvaluationSets,
  runEvaluation,
  type EvaluationQuestionResponse,
  type EvaluationRunDetailResponse,
} from "@/lib/api/evaluations";
import { listDocuments } from "@/lib/api/documents";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";

const EVALUATION_SET_LIMIT = 100;
const EVALUATION_QUESTION_LIMIT = 200;
const EVALUATION_RESULTS_LIMIT = 200;

const MIN_TOP_K = 1;
const MAX_TOP_K = 50;
const DEFAULT_TOP_K = 5;
const LOW_SCORE_THRESHOLD = 0.5;
const DEFAULT_RUN_POLL_INTERVAL_MS = 4_000;

type ResultFilterMode = "all" | "problematic";

type SummaryMetric = {
  title: string;
  value: string;
  caption: string;
};

type TimelinePoint = {
  label: string;
  score: number;
};

type EvaluationSetLatestRunSummary = {
  status: string;
  completedAt: string | null;
  qualityScore: number | null;
};

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

function parseScoreThresholdEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(0, Math.min(1, parsed));
}

function parseDefaultTopK(): number {
  const parsed = parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_EVALUATION_TOP_K_DEFAULT, DEFAULT_TOP_K);
  return Math.max(MIN_TOP_K, Math.min(MAX_TOP_K, parsed));
}

function parseRunPollIntervalMs(): number {
  return parsePositiveIntegerEnv(
    process.env.NEXT_PUBLIC_EVALUATION_RUN_POLL_INTERVAL_MS,
    DEFAULT_RUN_POLL_INTERVAL_MS,
  );
}

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "N/A";
  }

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatInteger(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "N/A";
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatMilliseconds(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "N/A";
  }
  return `${Math.max(0, value).toFixed(0)} ms`;
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "N/A";
  }
  let normalized = value;
  if (normalized > 1 && normalized <= 100) {
    normalized /= 100;
  }
  normalized = Math.max(0, Math.min(1, normalized));
  return `${(normalized * 100).toFixed(1)}%`;
}

function formatCurrency(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "N/A";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.max(0, value));
}

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

function resolveStatusBadgeClass(status: string): string {
  if (status === "completed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "running" || status === "queued") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
}

function resolveSummaryValue(
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

function summarizeRunMetrics(run: EvaluationRunDetailResponse | null): SummaryMetric[] {
  const summary = run?.summary ?? null;
  const summaryRecord = summary ? asRecord(summary) : null;

  const totalQuestions = resolveSummaryValue(summaryRecord, ["question_total_count"]) ?? run?.results.total ?? null;
  const successQuestions = resolveSummaryValue(summaryRecord, ["question_success_count"]);
  const failedQuestions = resolveSummaryValue(summaryRecord, ["question_failure_count"]);
  const retrievalHitRate = resolveSummaryValue(summaryRecord, ["retrieval_hit_rate", "retrieval_score"]);
  const contextPrecision = resolveSummaryValue(summaryRecord, ["context_precision"]);
  const contextRecall = resolveSummaryValue(summaryRecord, ["context_recall"]);
  const faithfulness = resolveSummaryValue(summaryRecord, ["faithfulness_score"]);
  const answerRelevance = resolveSummaryValue(summaryRecord, ["answer_relevance_score"]);
  const citationAccuracy = resolveSummaryValue(summaryRecord, ["citation_accuracy_score"]);
  const refusalAccuracy = resolveSummaryValue(summaryRecord, ["refusal_accuracy"]);
  const averageLatency = resolveSummaryValue(summaryRecord, ["latency_ms_average"]);
  const totalCost = resolveSummaryValue(summaryRecord, ["cost_usd_total"]);

  return [
    {
      title: "Questions",
      value: formatInteger(totalQuestions),
      caption: successQuestions != null && failedQuestions != null
        ? `${formatInteger(successQuestions)} succeeded / ${formatInteger(failedQuestions)} failed`
        : "Total evaluated questions",
    },
    {
      title: "Retrieval hit rate",
      value: formatPercent(retrievalHitRate),
      caption: "Questions with at least one relevant chunk retrieved",
    },
    {
      title: "Context precision",
      value: formatPercent(contextPrecision),
      caption: "Selected chunks that were relevant",
    },
    {
      title: "Context recall",
      value: formatPercent(contextRecall),
      caption: "Coverage of expected relevant context",
    },
    {
      title: "Faithfulness",
      value: formatPercent(faithfulness),
      caption: "Groundedness quality score",
    },
    {
      title: "Answer relevance",
      value: formatPercent(answerRelevance),
      caption: "Question-to-answer alignment",
    },
    {
      title: "Citation accuracy",
      value: formatPercent(citationAccuracy),
      caption: "Citation correctness score",
    },
    {
      title: "Refusal accuracy",
      value: formatPercent(refusalAccuracy),
      caption: "Correct refusal behavior when answer is unavailable",
    },
    {
      title: "Average latency",
      value: formatMilliseconds(averageLatency),
      caption: "Latency per successful question",
    },
    {
      title: "Estimated cost",
      value: formatCurrency(totalCost),
      caption: "Total run cost estimate",
    },
  ];
}

function computeResultQualityScore(item: EvaluationRunDetailResponse["results"]["items"][number]): number | null {
  const values = [
    item.faithfulness_score,
    item.answer_relevance_score,
    item.citation_accuracy_score,
    item.retrieval_score,
  ].filter((value): value is number => typeof value === "number" && Number.isFinite(value));

  if (values.length === 0) {
    return null;
  }

  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.max(0, Math.min(1, average));
}

function formatQuestionTags(question: EvaluationQuestionResponse): string {
  if (question.tags.length === 0) {
    return "-";
  }
  return question.tags.join(", ");
}

function buildTimelineFromSummary(summary: Record<string, unknown> | null): TimelinePoint[] {
  if (!summary) {
    return [];
  }

  const candidates = [
    summary.quality_over_time,
    summary.quality_timeline,
    summary.series,
    summary.score_timeline,
  ];

  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) {
      continue;
    }

    const points: TimelinePoint[] = [];
    for (const item of candidate) {
      const row = asRecord(item);
      if (!row) {
        continue;
      }

      const score =
        asNumber(row.score) ??
        asNumber(row.quality_score) ??
        asNumber(row.answer_relevance_score) ??
        asNumber(row.faithfulness_score) ??
        asNumber(row.value);
      if (score == null) {
        continue;
      }

      const rawLabel =
        (typeof row.label === "string" && row.label.trim()) ||
        (typeof row.timestamp === "string" && row.timestamp.trim()) ||
        (typeof row.date === "string" && row.date.trim()) ||
        `Point ${points.length + 1}`;

      points.push({
        label: rawLabel,
        score: Math.max(0, Math.min(1, score)),
      });
    }

    if (points.length > 0) {
      return points;
    }
  }

  return [];
}

function parseTagsCsv(rawTags: string): string[] {
  const parts = rawTags
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);

  return Array.from(new Set(parts));
}

function parseMetadataJson(rawMetadata: string): Record<string, unknown> | undefined {
  const normalized = rawMetadata.trim();
  if (!normalized) {
    return undefined;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(normalized);
  } catch {
    throw new Error("Metadata must be valid JSON.");
  }

  const record = asRecord(parsed);
  if (!record) {
    throw new Error("Metadata must be a JSON object.");
  }

  return record;
}

function parseMetricOptionsJson(rawMetricOptions: string): Record<string, boolean | number | string> | undefined {
  const normalized = rawMetricOptions.trim();
  if (!normalized) {
    return undefined;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(normalized);
  } catch {
    throw new Error("Metric options must be valid JSON.");
  }

  const record = asRecord(parsed);
  if (!record) {
    throw new Error("Metric options must be a JSON object.");
  }

  const normalizedOptions: Record<string, boolean | number | string> = {};
  for (const [key, value] of Object.entries(record)) {
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      normalizedOptions[key] = value;
      continue;
    }
    throw new Error(`Metric option "${key}" must be a string, number, or boolean.`);
  }

  return normalizedOptions;
}

function KpiCard({ title, value, caption }: SummaryMetric) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <p className="mb-1 text-xs font-bold uppercase tracking-[0.16em] text-[#6f6a8d]">{title}</p>
      <p className="text-2xl font-extrabold text-[#2a2640]">{value}</p>
      <p className="mt-2 text-xs text-[#6a6780]">{caption}</p>
    </article>
  );
}

function MetricSparkline({ points }: { points: TimelinePoint[] }) {
  if (points.length === 0) {
    return (
      <p className="rounded-lg border border-[#ebe8f7] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
        Quality trend data is not available for this run yet.
      </p>
    );
  }

  return (
    <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {points.map((point) => (
        <li
          key={`${point.label}:${point.score}`}
          className="rounded-lg border border-[#ebe8f7] bg-[#faf9ff] p-2"
        >
          <p className="mb-1 truncate text-xs font-semibold text-[#5f5a74]" title={point.label}>
            {point.label}
          </p>
          <div className="h-2 overflow-hidden rounded bg-[#dfdcf3]">
            <div
              className="h-full rounded bg-[#3525cd]"
              style={{ width: `${Math.round(point.score * 100)}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-[#68647b]">{formatPercent(point.score)}</p>
        </li>
      ))}
    </ul>
  );
}

type EvaluationsPageProps = {
  initialRunId?: string | null;
};

export function EvaluationsPage({ initialRunId = null }: EvaluationsPageProps) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { state } = useAuthSession();

  const role = state.session?.role ?? null;
  const canCreateSet = role === "owner" || role === "admin";
  const canManageQuestions = role === "owner" || role === "admin";
  const canRun = role === "owner" || role === "admin";

  const lowScoreThreshold = parseScoreThresholdEnv(
    process.env.NEXT_PUBLIC_EVALUATION_LOW_SCORE_THRESHOLD,
    LOW_SCORE_THRESHOLD,
  );

  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
  const [latestRunBySet, setLatestRunBySet] = useState<Record<string, string>>({});
  const [latestRunSummaryBySet, setLatestRunSummaryBySet] = useState<Record<string, EvaluationSetLatestRunSummary>>({});
  const [isCreateSetModalOpen, setIsCreateSetModalOpen] = useState(false);
  const [isRunModalOpen, setIsRunModalOpen] = useState(false);

  const [setName, setSetName] = useState("");
  const [setDescription, setSetDescription] = useState("");
  const [setFormError, setSetFormError] = useState<string | null>(null);

  const [questionText, setQuestionText] = useState("");
  const [expectedAnswer, setExpectedAnswer] = useState("");
  const [expectedDocumentId, setExpectedDocumentId] = useState<string>("");
  const [expectedPageNumber, setExpectedPageNumber] = useState("");
  const [questionTags, setQuestionTags] = useState("");
  const [questionMetadata, setQuestionMetadata] = useState("");
  const [questionFormError, setQuestionFormError] = useState<string | null>(null);

  const [runTopK, setRunTopK] = useState(parseDefaultTopK);
  const [runRerank, setRunRerank] = useState(true);
  const [runModelName, setRunModelName] = useState("");
  const [runMetricOptions, setRunMetricOptions] = useState("");
  const [runDocumentIds, setRunDocumentIds] = useState<string[]>([]);
  const [runFormError, setRunFormError] = useState<string | null>(null);

  const [resultFilterMode, setResultFilterMode] = useState<ResultFilterMode>("all");
  const runPollIntervalMs = parseRunPollIntervalMs();

  const evaluationSetsQuery = useQuery({
    queryKey: queryKeys.evaluations.sets,
    queryFn: () =>
      listEvaluationSets({
        limit: EVALUATION_SET_LIMIT,
        offset: 0,
      }),
  });

  const evaluationSetItems = useMemo(
    () => evaluationSetsQuery.data?.items ?? [],
    [evaluationSetsQuery.data?.items],
  );
  const selectedEvaluationSetId = useMemo(() => {
    if (evaluationSetItems.length === 0) {
      return null;
    }

    if (
      selectedSetId &&
      evaluationSetItems.some((item) => item.evaluation_set_id === selectedSetId)
    ) {
      return selectedSetId;
    }

    return evaluationSetItems[0].evaluation_set_id;
  }, [evaluationSetItems, selectedSetId]);

  const routeRunIdRaw = initialRunId ?? searchParams.get("runId");
  const routeRunId = routeRunIdRaw && routeRunIdRaw.trim().length > 0 ? routeRunIdRaw.trim() : null;
  const activeRunId = routeRunId ?? (
    selectedEvaluationSetId
      ? (latestRunBySet[selectedEvaluationSetId] ?? null)
      : null
  );

  const documentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      limit: EVALUATION_QUESTION_LIMIT,
      offset: 0,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        limit: EVALUATION_QUESTION_LIMIT,
        offset: 0,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
  });

  const questionsQuery = useQuery({
    queryKey: queryKeys.evaluations.setQuestions(selectedEvaluationSetId ?? "", {
      limit: EVALUATION_QUESTION_LIMIT,
      offset: 0,
    }),
    queryFn: () => {
      if (!selectedEvaluationSetId) {
        throw new Error("Evaluation set is required");
      }
      return listEvaluationQuestions(selectedEvaluationSetId, {
        limit: EVALUATION_QUESTION_LIMIT,
        offset: 0,
      });
    },
    enabled: Boolean(selectedEvaluationSetId),
  });

  const runDetailQuery = useQuery({
    queryKey: queryKeys.evaluations.run(activeRunId ?? "", {
      limit: EVALUATION_RESULTS_LIMIT,
      offset: 0,
    }),
    queryFn: () => {
      if (!activeRunId) {
        throw new Error("Evaluation run is required");
      }
      return getEvaluationRun(activeRunId, {
        limit: EVALUATION_RESULTS_LIMIT,
        offset: 0,
      });
    },
    enabled: Boolean(activeRunId),
    refetchInterval: (query) => {
      const payload = query.state.data as EvaluationRunDetailResponse | undefined;
      if (!payload) {
        return runPollIntervalMs;
      }
      return payload.status === "queued" || payload.status === "running" ? runPollIntervalMs : false;
    },
  });

  const accessibleDocuments = useMemo(
    () => documentsQuery.data?.items ?? [],
    [documentsQuery.data?.items],
  );
  const accessibleDocumentIdSet = useMemo(
    () => new Set(accessibleDocuments.map((document) => document.document_id)),
    [accessibleDocuments],
  );
  const indexedDocuments = useMemo(
    () => accessibleDocuments.filter((document) => document.status === "indexed"),
    [accessibleDocuments],
  );
  const indexedDocumentIdSet = useMemo(
    () => new Set(indexedDocuments.map((document) => document.document_id)),
    [indexedDocuments],
  );

  const filteredRunDocumentIds = useMemo(
    () => runDocumentIds.filter((documentId) => indexedDocumentIdSet.has(documentId)),
    [runDocumentIds, indexedDocumentIdSet],
  );

  const safeExpectedDocumentId =
    expectedDocumentId && accessibleDocumentIdSet.has(expectedDocumentId) ? expectedDocumentId : "";

  const createSetMutation = useMutation({
    mutationFn: createEvaluationSet,
    onSuccess: async (created) => {
      setSetName("");
      setSetDescription("");
      setSetFormError(null);
      setIsCreateSetModalOpen(false);
      setSelectedSetId(created.evaluation_set_id);
      await queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.sets });
    },
    onError: (error) => {
      setSetFormError(getApiErrorMessage(error));
    },
  });

  const createQuestionMutation = useMutation({
    mutationFn: async () => {
      if (!selectedEvaluationSetId) {
        throw new Error("Evaluation set is required");
      }

      const normalizedQuestion = questionText.trim();
      if (!normalizedQuestion) {
        throw new Error("Question is required.");
      }

      const parsedPageNumber = expectedPageNumber.trim();
      let pageNumber: number | null | undefined = undefined;
      if (parsedPageNumber.length > 0) {
        const parsed = Number.parseInt(parsedPageNumber, 10);
        if (!Number.isFinite(parsed) || parsed < 1) {
          throw new Error("Expected page must be a positive integer.");
        }
        pageNumber = parsed;
      }

      const tags = parseTagsCsv(questionTags);
      const metadata = parseMetadataJson(questionMetadata);

      return createEvaluationQuestion(selectedEvaluationSetId, {
        question: normalizedQuestion,
        expected_answer: expectedAnswer.trim() || null,
        expected_document_id: safeExpectedDocumentId || null,
        expected_page_number: pageNumber,
        tags,
        metadata,
      });
    },
    onSuccess: async () => {
      setQuestionText("");
      setExpectedAnswer("");
      setExpectedDocumentId("");
      setExpectedPageNumber("");
      setQuestionTags("");
      setQuestionMetadata("");
      setQuestionFormError(null);
      if (selectedEvaluationSetId) {
        await queryClient.invalidateQueries({
          queryKey: queryKeys.evaluations.setQuestions(selectedEvaluationSetId, {
            limit: EVALUATION_QUESTION_LIMIT,
            offset: 0,
          }),
        });
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.sets });
    },
    onError: (error) => {
      setQuestionFormError(getApiErrorMessage(error));
    },
  });

  const runMutation = useMutation({
    mutationFn: async () => {
      if (!selectedEvaluationSetId) {
        throw new Error("Select an evaluation set before running.");
      }
      if (!canRun) {
        throw new Error("Only owner/admin can queue evaluation runs.");
      }

      const selectedTopK = Math.max(MIN_TOP_K, Math.min(MAX_TOP_K, runTopK));
      const selectedDocumentIds = runDocumentIds.filter((documentId) =>
        accessibleDocumentIdSet.has(documentId),
      );
      if (selectedDocumentIds.length !== runDocumentIds.length) {
        throw new Error("One or more selected documents are no longer accessible. Refresh and retry.");
      }
      const metricOptions = parseMetricOptionsJson(runMetricOptions);
      const modelName = runModelName.trim() || null;

      return runEvaluation({
        evaluation_set_id: selectedEvaluationSetId,
        config: {
          top_k: selectedTopK,
          rerank: runRerank,
          model_name: modelName,
          selected_document_ids: selectedDocumentIds,
          metric_options: metricOptions,
        },
      });
    },
    onSuccess: async (result) => {
      if (selectedEvaluationSetId) {
        setLatestRunBySet((previous) => ({
          ...previous,
          [selectedEvaluationSetId]: result.evaluation_run_id,
        }));
      }

      setRunFormError(null);
      setIsRunModalOpen(false);
      await queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.sets });
      router.push(`/evaluations/runs/${encodeURIComponent(result.evaluation_run_id)}`);
    },
    onError: (error) => {
      if (isApiClientError(error) && error.status === 409) {
        setRunFormError("An evaluation run is already active for this set. Open the existing run or wait for completion.");
        return;
      }
      setRunFormError(getApiErrorMessage(error));
    },
  });

  const selectedSet =
    evaluationSetItems.find((item) => item.evaluation_set_id === selectedEvaluationSetId) ?? null;

  const runDetails = runDetailQuery.data ?? null;
  const summaryMetrics = useMemo(() => summarizeRunMetrics(runDetails), [runDetails]);

  const latestRunQualityScore = useMemo(() => {
    const summary = asRecord(runDetails?.summary);
    return (
      asNumber(summary?.faithfulness_score) ??
      asNumber(summary?.answer_relevance_score) ??
      asNumber(summary?.citation_accuracy_score) ??
      null
    );
  }, [runDetails?.summary]);

  const summaryTimeline = buildTimelineFromSummary(asRecord(runDetails?.summary));
  const timelinePoints: TimelinePoint[] = summaryTimeline;

  const results = runDetails?.results.items ?? [];
  const problematicResults = results.filter((item) => {
    if (item.status === "failed") {
      return true;
    }
    const score = computeResultQualityScore(item);
    return score != null && score < lowScoreThreshold;
  });

  const filteredResults = resultFilterMode === "problematic" ? problematicResults : results;
  const runNotFound =
    runDetailQuery.isError &&
    isApiClientError(runDetailQuery.error) &&
    runDetailQuery.error.status === 404;
  const runProgress = useMemo(() => {
    if (!runDetails) {
      return null;
    }

    const total = Math.max(runDetails.results.total, runDetails.results.items.length, 0);
    const completed = runDetails.results.items.filter((item) => item.status === "completed").length;
    const failed = runDetails.results.items.filter((item) => item.status === "failed").length;
    const terminalCount = completed + failed;
    const ratio = total > 0 ? Math.max(0, Math.min(1, terminalCount / total)) : runDetails.status === "completed" ? 1 : 0;
    return {
      total,
      completed,
      failed,
      terminalCount,
      ratio,
    };
  }, [runDetails]);

  useEffect(() => {
    if (!selectedEvaluationSetId || !runDetails) {
      return;
    }
    setLatestRunSummaryBySet((previous) => ({
      ...previous,
      [selectedEvaluationSetId]: {
        status: runDetails.status,
        completedAt: runDetails.completed_at,
        qualityScore: latestRunQualityScore,
      },
    }));
  }, [latestRunQualityScore, runDetails, selectedEvaluationSetId]);

  useEffect(() => {
    if (!routeRunId || !runDetails?.evaluation_set_id) {
      return;
    }
    if (
      evaluationSetItems.some(
        (item) => item.evaluation_set_id === runDetails.evaluation_set_id,
      )
    ) {
      setSelectedSetId(runDetails.evaluation_set_id);
    }
  }, [evaluationSetItems, routeRunId, runDetails?.evaluation_set_id]);

  const listForbidden = isForbiddenError(evaluationSetsQuery.error) || isForbiddenError(questionsQuery.error);
  if (listForbidden) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Evaluation access is restricted"
          description="Your role does not have permission to view evaluation resources in this organization."
          requestId={extractRequestIdFromError(evaluationSetsQuery.error ?? questionsQuery.error)}
        />
      </section>
    );
  }

  const emptySetState =
    !evaluationSetsQuery.isLoading &&
    !evaluationSetsQuery.isError &&
    (evaluationSetsQuery.data?.items.length ?? 0) === 0;

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Evaluations</p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">Evaluation page and dashboard</h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Create evaluation sets, manage questions, run benchmarks, and inspect low-scoring or failed answers.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/documents"
              className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
            >
              Upload document
            </Link>
            <Link
              href="/chat"
              className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
            >
              New chat
            </Link>
            <Link
              href="/rag-pipeline"
              className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
            >
              Pipeline explorer
            </Link>
          </div>
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
        <aside className="space-y-4">
          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Evaluation sets</h2>
              {canCreateSet ? (
                <button
                  type="button"
                  onClick={() => {
                    setSetFormError(null);
                    setIsCreateSetModalOpen(true);
                  }}
                  className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#2b1fa8]"
                >
                  Create evaluation set
                </button>
              ) : null}
            </div>
            {!canCreateSet ? (
              <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                Your role can view evaluation sets but only owner/admin can create new sets.
              </p>
            ) : (
              <p className="mb-4 text-xs text-[#6a6780]">
                Create and organize evaluation sets for your active organization.
              </p>
            )}

            {evaluationSetsQuery.isLoading ? (
              <p className="text-sm text-[#68647b]">Loading evaluation sets...</p>
            ) : evaluationSetsQuery.isError ? (
              <div className="space-y-2">
                <p className="text-sm text-rose-700">{getApiErrorMessage(evaluationSetsQuery.error)}</p>
                <button
                  type="button"
                  onClick={() => void evaluationSetsQuery.refetch()}
                  className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-50"
                >
                  Retry
                </button>
              </div>
            ) : emptySetState ? (
              <p className="text-sm text-[#68647b]">No evaluation sets yet. Create one to start question benchmarking.</p>
            ) : (
              <ul className="max-h-[380px] space-y-2 overflow-auto pr-1">
                {evaluationSetItems.map((item) => {
                  const latestSummary = latestRunSummaryBySet[item.evaluation_set_id];
                  return (
                    <li key={item.evaluation_set_id}>
                      <button
                        type="button"
                        onClick={() => setSelectedSetId(item.evaluation_set_id)}
                        className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                          item.evaluation_set_id === selectedEvaluationSetId
                            ? "border-[#3525cd] bg-[#f4f2ff] text-[#2f2a46]"
                            : "border-[#e4e1f2] bg-white text-[#4f4b63] hover:bg-[#faf9ff]"
                        }`}
                      >
                        <p className="font-semibold">{item.name}</p>
                        {item.description ? (
                          <p className="mt-1 line-clamp-2 text-xs text-[#6a6780]">{item.description}</p>
                        ) : (
                          <p className="mt-1 text-xs text-[#6a6780]">No description.</p>
                        )}
                        <p className="mt-1 text-xs">{item.question_count} questions</p>
                        <p className="text-xs text-[#6a6780]">Created: {formatDate(item.created_at)}</p>
                        <p className="text-xs text-[#6a6780]">Updated: {formatDate(item.updated_at)}</p>
                        {latestSummary ? (
                          <p className="mt-1 text-xs text-[#4f4b63]">
                            Latest run: {latestSummary.status}
                            {latestSummary.qualityScore != null
                              ? ` • quality ${formatPercent(latestSummary.qualityScore)}`
                              : ""}
                            {latestSummary.completedAt
                              ? ` • ${formatDate(latestSummary.completedAt)}`
                              : ""}
                          </p>
                        ) : (
                          <p className="mt-1 text-xs text-[#6a6780]">Latest run: Not available yet.</p>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Run controls</h2>
            {selectedSet ? (
              <div className="space-y-3">
                <p className="text-sm text-[#4f4b63]">
                  Selected set: <span className="font-semibold text-[#2f2a46]">{selectedSet.name}</span>
                </p>
                <p className="text-xs text-[#6a6780]">
                  Configure top-k retrieval, rerank behavior, optional model override, metric options, and document scope in the run modal.
                </p>
                {activeRunId ? (
                  <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-xs text-[#5f5a74]">
                    Active run detail: <span className="font-semibold text-[#2f2a46]">{activeRunId}</span>
                  </p>
                ) : null}

                {!canRun ? (
                  <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    Your role can inspect results but only owner/admin can run evaluations.
                  </p>
                ) : null}

                <button
                  type="button"
                  onClick={() => {
                    setRunFormError(null);
                    setIsRunModalOpen(true);
                  }}
                  disabled={!canRun || !selectedEvaluationSetId}
                  className="w-full rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Run evaluation
                </button>
              </div>
            ) : (
              <p className="text-sm text-[#68647b]">Select an evaluation set to configure and run it.</p>
            )}
          </section>
        </aside>

        <div className="space-y-4">
          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Question management</h2>

            {!selectedEvaluationSetId ? (
              <p className="text-sm text-[#68647b]">Select a set before adding or reviewing questions.</p>
            ) : (
              <>
                {canManageQuestions ? (
                  <form
                    className="mb-4 grid gap-2 rounded-lg border border-[#ebe8f7] bg-[#faf9ff] p-3 lg:grid-cols-2"
                    onSubmit={(event) => {
                      event.preventDefault();
                      setQuestionFormError(null);
                      createQuestionMutation.mutate();
                    }}
                  >
                    <label className="grid gap-1 lg:col-span-2">
                      <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Question</span>
                      <textarea
                        value={questionText}
                        onChange={(event) => setQuestionText(event.target.value)}
                        rows={2}
                        className="rounded-lg border border-[#d2cee6] px-2 py-1.5 text-sm text-[#2a2640]"
                        placeholder="What is the retention policy for invoices?"
                      />
                    </label>

                    <label className="grid gap-1 lg:col-span-2">
                      <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Expected answer</span>
                      <textarea
                        value={expectedAnswer}
                        onChange={(event) => setExpectedAnswer(event.target.value)}
                        rows={2}
                        className="rounded-lg border border-[#d2cee6] px-2 py-1.5 text-sm text-[#2a2640]"
                        placeholder="Optional expected answer for quality scoring"
                      />
                    </label>

                    <label className="grid gap-1">
                      <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Expected document</span>
                      <select
                        value={safeExpectedDocumentId}
                        onChange={(event) => setExpectedDocumentId(event.target.value)}
                        className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
                      >
                        <option value="">Not specified</option>
                        {accessibleDocuments.map((document) => (
                          <option key={document.document_id} value={document.document_id}>
                            {document.filename}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="grid gap-1">
                      <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Expected page</span>
                      <input
                        value={expectedPageNumber}
                        onChange={(event) => setExpectedPageNumber(event.target.value)}
                        className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
                        placeholder="Optional"
                      />
                    </label>

                    <label className="grid gap-1 lg:col-span-2">
                      <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Tags (comma separated)</span>
                      <input
                        value={questionTags}
                        onChange={(event) => setQuestionTags(event.target.value)}
                        className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
                        placeholder="invoice, policy, legal"
                      />
                    </label>

                    <label className="grid gap-1 lg:col-span-2">
                      <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                        Metadata (JSON object)
                      </span>
                      <textarea
                        value={questionMetadata}
                        onChange={(event) => setQuestionMetadata(event.target.value)}
                        rows={3}
                        className="rounded-lg border border-[#d2cee6] px-2 py-1.5 text-sm text-[#2a2640]"
                        placeholder='{"difficulty":"medium","owner":"qa-team"}'
                      />
                    </label>

                    {questionFormError ? <p className="text-xs text-rose-700 lg:col-span-2">{questionFormError}</p> : null}

                    <button
                      type="submit"
                      disabled={createQuestionMutation.isPending}
                      className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60 lg:col-span-2"
                    >
                      {createQuestionMutation.isPending ? "Adding question..." : "Add question"}
                    </button>
                  </form>
                ) : (
                  <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    Your role can view questions but only owner/admin can add new questions.
                  </p>
                )}

                {questionsQuery.isLoading ? (
                  <p className="text-sm text-[#68647b]">Loading questions...</p>
                ) : questionsQuery.isError ? (
                  <div className="space-y-2">
                    <p className="text-sm text-rose-700">{getApiErrorMessage(questionsQuery.error)}</p>
                    <button
                      type="button"
                      onClick={() => void questionsQuery.refetch()}
                      className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-50"
                    >
                      Retry
                    </button>
                  </div>
                ) : (questionsQuery.data?.items.length ?? 0) === 0 ? (
                  <p className="text-sm text-[#68647b]">No questions yet. Add at least one question before running evaluations.</p>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-[#ebe8f7]">
                    <table className="min-w-full divide-y divide-[#ebe8f7] bg-white text-sm">
                      <thead className="bg-[#faf9ff]">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Question</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Expected page</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Tags</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#f0edf9]">
                        {questionsQuery.data?.items.map((question) => (
                          <tr key={question.evaluation_question_id}>
                            <td className="px-3 py-2 text-[#2f2a46]">
                              <p className="font-medium">{question.question}</p>
                              {question.expected_answer ? (
                                <p className="mt-1 text-xs text-[#6a6780]">
                                  Expected answer: {question.expected_answer}
                                </p>
                              ) : null}
                            </td>
                            <td className="px-3 py-2 text-[#2f2a46]">{question.expected_page_number ?? "-"}</td>
                            <td className="px-3 py-2 text-[#2f2a46]">{formatQuestionTags(question)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </section>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Evaluation run dashboard</h2>
              {runDetails ? (
                <span className={resolveStatusBadgeClass(runDetails.status)}>Run status: {runDetails.status}</span>
              ) : null}
            </div>

            {!activeRunId ? (
              <p className="text-sm text-[#68647b]">
                No run selected yet. Start an evaluation run to populate status, summary, and question-level metrics.
              </p>
            ) : runDetailQuery.isLoading ? (
              <p className="text-sm text-[#68647b]">Loading evaluation run details...</p>
            ) : runDetailQuery.isError ? (
              <div className="space-y-2">
                {isForbiddenError(runDetailQuery.error) ? (
                  <ForbiddenState
                    compact
                    title="Run details are restricted"
                    description="You do not have permission to inspect this evaluation run."
                    requestId={extractRequestIdFromError(runDetailQuery.error)}
                  />
                ) : runNotFound ? (
                  <div className="rounded-lg border border-[#ebe8f7] bg-[#faf9ff] p-3 text-sm text-[#4d4963]">
                    <p className="font-semibold text-[#2f2a46]">Run not found or inaccessible.</p>
                    <p className="mt-1">
                      The evaluation run may belong to another organization or may no longer exist.
                    </p>
                    <Link
                      href="/evaluations"
                      className="mt-2 inline-flex rounded border border-[#cbc5e6] bg-white px-2 py-1 text-xs font-semibold text-[#3e376f] hover:bg-[#f4f2ff]"
                    >
                      Back to evaluations
                    </Link>
                  </div>
                ) : (
                  <>
                    <p className="text-sm text-rose-700">{getApiErrorMessage(runDetailQuery.error)}</p>
                    <button
                      type="button"
                      onClick={() => void runDetailQuery.refetch()}
                      className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-50"
                    >
                      Retry
                    </button>
                  </>
                )}
              </div>
            ) : runDetails ? (
              <div className="space-y-4">
                <dl className="grid gap-2 rounded-lg border border-[#ebe8f7] bg-[#faf9ff] p-3 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Run ID</dt>
                    <dd className="font-medium text-[#2f2a46]">{runDetails.evaluation_run_id}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Evaluation set</dt>
                    <dd className="font-medium text-[#2f2a46]">{selectedSet?.name ?? runDetails.evaluation_set_id}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Started at</dt>
                    <dd className="font-medium text-[#2f2a46]">{formatDate(runDetails.started_at ?? runDetails.created_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Completed at</dt>
                    <dd className="font-medium text-[#2f2a46]">{formatDate(runDetails.completed_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Created at</dt>
                    <dd className="font-medium text-[#2f2a46]">{formatDate(runDetails.created_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Updated at</dt>
                    <dd className="font-medium text-[#2f2a46]">{formatDate(runDetails.updated_at)}</dd>
                  </div>
                </dl>

                {(runDetails.status === "queued" || runDetails.status === "running") && runProgress ? (
                  <section className="rounded-lg border border-[#ebe8f7] bg-[#faf9ff] p-3">
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-[#5f5a74]">Run progress</h3>
                    <p className="text-sm text-[#4d4963]">
                      {runDetails.status === "queued"
                        ? "Run is queued and waiting for workers."
                        : "Run is processing question-level evaluation results."}
                    </p>
                    <p className="mt-1 text-xs text-[#6a6780]">
                      Auto-refreshing every {Math.max(1, Math.round(runPollIntervalMs / 1000))}s.
                    </p>
                    <div className="mt-2 h-2 overflow-hidden rounded bg-[#dfdcf3]">
                      <div
                        className="h-full rounded bg-[#3525cd]"
                        style={{ width: `${Math.round(runProgress.ratio * 100)}%` }}
                      />
                    </div>
                    <p className="mt-1 text-xs text-[#6a6780]">
                      {formatInteger(runProgress.terminalCount)} / {formatInteger(runProgress.total)} completed
                      {runProgress.failed > 0 ? ` (${formatInteger(runProgress.failed)} failed)` : ""}
                    </p>
                  </section>
                ) : null}

                <section className="rounded-lg border border-[#ebe8f7] bg-[#faf9ff] p-3">
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-[#5f5a74]">Run configuration</h3>
                  <pre className="max-h-64 overflow-auto rounded border border-[#e4e1f2] bg-white p-2 text-xs text-[#2f2a46]">
                    {JSON.stringify(runDetails.config ?? {}, null, 2)}
                  </pre>
                </section>

                {runDetails.failure_reason ? (
                  <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                    <span className="font-semibold">Failure:</span> {runDetails.failure_reason}
                    {runDetails.failure_type ? (
                      <span className="ml-2 text-xs uppercase tracking-wide text-rose-700">
                        ({runDetails.failure_type})
                      </span>
                    ) : null}
                  </p>
                ) : null}

                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {summaryMetrics.map((metric) => (
                    <KpiCard key={metric.title} {...metric} />
                  ))}
                </div>

                <section className="rounded-lg border border-[#ebe8f7] bg-[#faf9ff] p-3">
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-[#5f5a74]">
                    Quality over time
                  </h3>
                  <MetricSparkline points={timelinePoints} />
                </section>

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-xs font-bold uppercase tracking-wide text-[#5f5a74]">
                    Question-level results
                  </h3>
                  <div className="flex items-center gap-2 text-xs">
                    <button
                      type="button"
                      onClick={() => setResultFilterMode("all")}
                      className={`rounded border px-2 py-1 font-semibold ${
                        resultFilterMode === "all"
                          ? "border-[#3525cd] bg-[#f4f2ff] text-[#3525cd]"
                          : "border-[#d2cee6] bg-white text-[#5f5a74]"
                      }`}
                    >
                      All ({results.length})
                    </button>
                    <button
                      type="button"
                      onClick={() => setResultFilterMode("problematic")}
                      className={`rounded border px-2 py-1 font-semibold ${
                        resultFilterMode === "problematic"
                          ? "border-[#3525cd] bg-[#f4f2ff] text-[#3525cd]"
                          : "border-[#d2cee6] bg-white text-[#5f5a74]"
                      }`}
                    >
                      Failed/low ({problematicResults.length})
                    </button>
                  </div>
                </div>

                {filteredResults.length === 0 ? (
                  <p className="rounded-lg border border-[#ebe8f7] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
                    No results match the selected filter.
                  </p>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-[#ebe8f7]">
                    <table className="min-w-full divide-y divide-[#ebe8f7] bg-white text-sm">
                      <thead className="bg-[#faf9ff]">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Question</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Status</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Quality</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Faithfulness</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Citation</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Relevance</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Latency</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Failure</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#f0edf9]">
                        {filteredResults.map((item) => {
                          const qualityScore = computeResultQualityScore(item);
                          const isProblematic = item.status === "failed" || (qualityScore != null && qualityScore < lowScoreThreshold);
                          return (
                            <tr
                              key={item.evaluation_result_id}
                              className={isProblematic ? "bg-rose-50/50" : "bg-white"}
                            >
                              <td className="px-3 py-2 text-[#2f2a46]">
                                <p className="font-medium">{item.question}</p>
                                {item.generated_answer ? (
                                  <p className="mt-1 max-w-[420px] truncate text-xs text-[#6a6780]" title={item.generated_answer}>
                                    {item.generated_answer}
                                  </p>
                                ) : null}
                              </td>
                              <td className="px-3 py-2 text-[#2f2a46]">
                                <span className={resolveStatusBadgeClass(item.status)}>{item.status}</span>
                              </td>
                              <td className="px-3 py-2 text-[#2f2a46]">{formatPercent(qualityScore)}</td>
                              <td className="px-3 py-2 text-[#2f2a46]">{formatPercent(item.faithfulness_score)}</td>
                              <td className="px-3 py-2 text-[#2f2a46]">{formatPercent(item.citation_accuracy_score)}</td>
                              <td className="px-3 py-2 text-[#2f2a46]">{formatPercent(item.answer_relevance_score)}</td>
                              <td className="px-3 py-2 text-[#2f2a46]">{formatMilliseconds(item.latency_ms)}</td>
                              <td className="px-3 py-2 text-[#2f2a46]">
                                {item.failure_reason ? (
                                  <span className="text-rose-700" title={item.failure_reason}>{item.failure_reason}</span>
                                ) : (
                                  "-"
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ) : null}
          </section>
        </div>
      </div>
      {isRunModalOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[#17172a]/55 px-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="run-evaluation-title"
            className="w-full max-w-2xl rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-xl"
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 id="run-evaluation-title" className="text-lg font-bold text-[#2a2640]">
                  Run evaluation
                </h2>
                <p className="text-sm text-[#68647b]">
                  Queue a run for <span className="font-semibold text-[#2f2a46]">{selectedSet?.name ?? "selected set"}</span>.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  if (runMutation.isPending) {
                    return;
                  }
                  setRunFormError(null);
                  setIsRunModalOpen(false);
                }}
                disabled={runMutation.isPending}
                className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Close
              </button>
            </div>

            <form
              className="space-y-3"
              onSubmit={(event: FormEvent<HTMLFormElement>) => {
                event.preventDefault();
                setRunFormError(null);
                runMutation.mutate();
              }}
            >
              <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                Top K
                <input
                  type="number"
                  min={MIN_TOP_K}
                  max={MAX_TOP_K}
                  value={runTopK}
                  onChange={(event) => {
                    const parsed = Number.parseInt(event.target.value, 10);
                    if (!Number.isFinite(parsed)) {
                      return;
                    }
                    setRunTopK(Math.max(MIN_TOP_K, Math.min(MAX_TOP_K, parsed)));
                  }}
                  className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
                />
              </label>

              <label className="flex items-start gap-2 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-sm text-[#2f2a46]">
                <input
                  type="checkbox"
                  checked={runRerank}
                  onChange={(event) => setRunRerank(event.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  Enable rerank
                  <span className="mt-1 block text-xs text-[#6a6780]">
                    Use a second-pass ranking to improve relevance.
                  </span>
                </span>
              </label>

              <label className="grid gap-1">
                <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Model name (optional)</span>
                <input
                  value={runModelName}
                  onChange={(event) => setRunModelName(event.target.value)}
                  className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
                  placeholder="Optional backend-supported model identifier"
                />
              </label>

              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Selected documents</p>
                {documentsQuery.isLoading ? (
                  <p className="text-xs text-[#68647b]">Loading indexed documents...</p>
                ) : documentsQuery.isError ? (
                  <p className="text-xs text-rose-700">{getApiErrorMessage(documentsQuery.error)}</p>
                ) : indexedDocuments.length === 0 ? (
                  <p className="text-xs text-[#68647b]">No indexed documents available.</p>
                ) : (
                  <ul className="max-h-40 space-y-1 overflow-auto rounded border border-[#ebe8f7] bg-[#faf9ff] p-2">
                    {indexedDocuments.map((document) => {
                      const checked = filteredRunDocumentIds.includes(document.document_id);
                      return (
                        <li key={document.document_id}>
                          <label className="flex items-center gap-2 text-xs text-[#2f2a46]">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => {
                                setRunDocumentIds((previous) => {
                                  const validPrevious = previous.filter((value) =>
                                    indexedDocumentIdSet.has(value),
                                  );
                                  if (validPrevious.includes(document.document_id)) {
                                    return validPrevious.filter(
                                      (value) => value !== document.document_id,
                                    );
                                  }
                                  return [...validPrevious, document.document_id];
                                });
                              }}
                            />
                            <span className="truncate" title={document.filename}>{document.filename}</span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              <label className="grid gap-1">
                <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                  Metric options (JSON object)
                </span>
                <textarea
                  value={runMetricOptions}
                  onChange={(event) => setRunMetricOptions(event.target.value)}
                  rows={3}
                  className="rounded-lg border border-[#d2cee6] px-2 py-1.5 text-sm text-[#2a2640]"
                  placeholder='{"faithfulness":true,"latency_budget_ms":800}'
                />
              </label>

              {runFormError ? <p className="text-xs text-rose-700">{runFormError}</p> : null}

              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    if (runMutation.isPending) {
                      return;
                    }
                    setRunFormError(null);
                    setIsRunModalOpen(false);
                  }}
                  disabled={runMutation.isPending}
                  className="rounded border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!canRun || runMutation.isPending || !selectedEvaluationSetId}
                  className="rounded bg-[#3525cd] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {runMutation.isPending ? "Queueing run..." : "Queue run"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
      {isCreateSetModalOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[#17172a]/55 px-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-evaluation-set-title"
            className="w-full max-w-lg rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-xl"
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 id="create-evaluation-set-title" className="text-lg font-bold text-[#2a2640]">
                  Create evaluation set
                </h2>
                <p className="text-sm text-[#68647b]">
                  Name your benchmark set and optionally add context for collaborators.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSetFormError(null);
                  setIsCreateSetModalOpen(false);
                }}
                disabled={createSetMutation.isPending}
                className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Close
              </button>
            </div>

            <form
              className="space-y-3"
              onSubmit={(event: FormEvent<HTMLFormElement>) => {
                event.preventDefault();
                if (!canCreateSet) {
                  setSetFormError("Only owner/admin can create evaluation sets.");
                  return;
                }

                const normalizedName = setName.trim();
                if (!normalizedName) {
                  setSetFormError("Set name is required.");
                  return;
                }

                setSetFormError(null);
                createSetMutation.mutate({
                  name: normalizedName,
                  description: setDescription.trim() || null,
                });
              }}
            >
              <label className="grid gap-1">
                <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Set name</span>
                <input
                  value={setName}
                  onChange={(event) => setSetName(event.target.value)}
                  className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
                  placeholder="Regression suite"
                />
              </label>

              <label className="grid gap-1">
                <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Description</span>
                <textarea
                  value={setDescription}
                  onChange={(event) => setSetDescription(event.target.value)}
                  rows={3}
                  className="rounded-lg border border-[#d2cee6] px-2 py-1.5 text-sm text-[#2a2640]"
                  placeholder="Optional context for what this evaluation set validates"
                />
              </label>

              {setFormError ? <p className="text-xs text-rose-700">{setFormError}</p> : null}

              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setSetFormError(null);
                    setIsCreateSetModalOpen(false);
                  }}
                  disabled={createSetMutation.isPending}
                  className="rounded border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createSetMutation.isPending}
                  className="rounded bg-[#3525cd] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {createSetMutation.isPending ? "Creating..." : "Create set"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </section>
  );
}
