"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  CreateEvaluationSetDialog,
  StartEvaluationRunDialog,
} from "@/components/evaluations/evaluation-dialogs";
import { DatasetBuilderPanel } from "@/components/evaluations/dataset-builder";
import {
  readEvaluationRunHistory,
  upsertEvaluationRunHistory,
} from "@/components/evaluations/evaluation-history-storage";
import {
  type AddQuestionDraft,
  type DatasetQuestionFilters,
  EvaluationSetsSection,
} from "@/components/evaluations/evaluation-sets-section";
import {
  EvaluationCasesSection,
  EvaluationRunDetailSection,
  EvaluationRunDetailSkeleton,
} from "@/components/evaluations/evaluation-run-detail";
import { RunComparisonPanel } from "@/components/evaluations/run-comparison";
import {
  buildCaseViews,
  buildRunComparison,
  buildRunListItemFromDetail,
  filterAndSortCaseViews,
  filterAndSortRuns,
  runStatusLabel,
  type EvaluationRunHistoryRecord,
  type EvaluationRunListItem,
  type ResultFilters,
  type RunFilters,
} from "@/components/evaluations/evaluation-view-model";
import {
  type EvaluationKpiItem,
  type EvaluationSetOverviewRow,
  EvaluationInsightsRow,
  EvaluationKpiGrid,
  EvaluationSetsOverviewTable,
  EvaluationsPageHeader,
  RecentRunsPanel,
  EvaluationRunsFilterBar,
  EvaluationRunsTable,
  RunsTableSkeleton,
  resolveKpiTrendLabel,
} from "@/components/evaluations/evaluation-ui";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { OnboardingCtaBanner } from "@/components/onboarding/OnboardingCtaBanner";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import {
  createEvaluationQuestion,
  createEvaluationSet,
  getEvaluationRun,
  listEvaluationQuestions,
  listEvaluationSets,
  runEvaluation,
} from "@/lib/api/evaluations";
import { listChunkingProfiles } from "@/lib/api/chunking-profiles";
import { listDocuments } from "@/lib/api/documents";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { listModelProfiles } from "@/lib/api/model-profiles";
import { queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useOverlayFocus } from "@/lib/use-overlay-focus";
import { useAuthSession } from "@/lib/use-auth-session";

const EVALUATION_SET_LIMIT = 100;
const EVALUATION_QUESTION_LIMIT = 200;
const EVALUATION_RESULTS_PAGE_SIZE = 20;
const LOW_SCORE_THRESHOLD = 0.5;
const RUN_POLL_INTERVAL_MS = 4_000;
const MIN_TOP_K = 1;
const MAX_TOP_K = 50;

type EvaluationsPageProps = {
  initialRunId?: string | null;
};

function parseTagsCsv(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((part) => part.trim())
        .filter((part) => part.length > 0),
    ),
  );
}

function parseMetricOptionsJson(
  value: string,
): Record<string, boolean | number | string> | undefined {
  if (!value.trim()) {
    return undefined;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("Metric options must be valid JSON.");
  }

  if (typeof parsed !== "object" || parsed == null || Array.isArray(parsed)) {
    throw new Error("Metric options must be a JSON object.");
  }

  const output: Record<string, boolean | number | string> = {};
  for (const [key, item] of Object.entries(parsed)) {
    if (
      typeof item === "string" ||
      typeof item === "number" ||
      typeof item === "boolean"
    ) {
      output[key] = item;
      continue;
    }
    throw new Error(
      `Metric option \"${key}\" must be a string, number, or boolean.`,
    );
  }

  return output;
}

type RegressionThresholdDraft = {
  retrievalHitRateMin: string;
  citationAccuracyScoreMin: string;
  faithfulnessScoreMin: string;
  maxNotFoundRate: string;
};

function regressionThresholdDefaults(): RegressionThresholdDraft {
  return {
    retrievalHitRateMin: "",
    citationAccuracyScoreMin: "",
    faithfulnessScoreMin: "",
    maxNotFoundRate: "",
  };
}

function parseRegressionThresholdValue(
  label: string,
  value: string,
): number | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  const parsed = Number.parseFloat(normalized);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) {
    throw new Error(`${label} must be a number between 0 and 1.`);
  }
  return parsed;
}

function parseRegressionThresholds(value: RegressionThresholdDraft):
  | {
      retrieval_hit_rate_min?: number;
      citation_accuracy_score_min?: number;
      faithfulness_score_min?: number;
      max_not_found_rate?: number;
    }
  | undefined {
  const retrievalHitRateMin = parseRegressionThresholdValue(
    "Retrieval hit rate threshold",
    value.retrievalHitRateMin,
  );
  const citationAccuracyScoreMin = parseRegressionThresholdValue(
    "Citation accuracy threshold",
    value.citationAccuracyScoreMin,
  );
  const faithfulnessScoreMin = parseRegressionThresholdValue(
    "Faithfulness threshold",
    value.faithfulnessScoreMin,
  );
  const maxNotFoundRate = parseRegressionThresholdValue(
    "Not-found rate threshold",
    value.maxNotFoundRate,
  );

  const payload = {
    ...(retrievalHitRateMin != null
      ? { retrieval_hit_rate_min: retrievalHitRateMin }
      : {}),
    ...(citationAccuracyScoreMin != null
      ? { citation_accuracy_score_min: citationAccuracyScoreMin }
      : {}),
    ...(faithfulnessScoreMin != null
      ? { faithfulness_score_min: faithfulnessScoreMin }
      : {}),
    ...(maxNotFoundRate != null ? { max_not_found_rate: maxNotFoundRate } : {}),
  };

  return Object.keys(payload).length > 0 ? payload : undefined;
}

function normalizePage(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    throw new Error("Expected page must be a positive integer.");
  }
  return parsed;
}

function runFiltersDefaults(): RunFilters {
  return {
    query: "",
    status: "all",
    datasetId: "all",
    owner: "all",
    dateFrom: "",
    dateTo: "",
    sortBy: "created_desc",
  };
}

function resultFiltersDefaults(): ResultFilters {
  return {
    query: "",
    status: "all",
    sortBy: "created_desc",
  };
}

function questionFiltersDefaults(): DatasetQuestionFilters {
  return {
    query: "",
    sortBy: "created_desc",
  };
}

function questionDraftDefaults(): AddQuestionDraft {
  return {
    question: "",
    expectedAnswer: "",
    expectedPage: "",
    tags: "",
  };
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

function normalizeRate(value: number | null): number | null {
  if (value == null || !Number.isFinite(value)) {
    return null;
  }
  if (value > 1 && value <= 100) {
    return Math.max(0, Math.min(1, value / 100));
  }
  return Math.max(0, Math.min(1, value));
}

function metricFromSummary(
  summary: Record<string, unknown> | null | undefined,
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

function setStatusToneFromScore(
  score: number | null,
): EvaluationSetOverviewRow["statusTone"] {
  if (score == null || !Number.isFinite(score)) {
    return "muted";
  }
  const normalized = normalizeRate(score);
  if (normalized == null) {
    return "muted";
  }
  if (normalized >= 0.85) {
    return "good";
  }
  if (normalized >= 0.7) {
    return "warn";
  }
  return "bad";
}

function kpiToneFromScore(
  score: number | null,
): NonNullable<EvaluationKpiItem["tone"]> {
  const tone = setStatusToneFromScore(score);
  if (tone === "muted") {
    return "default";
  }
  return tone;
}

function setStatusLabel(
  run: EvaluationRunListItem | undefined,
): EvaluationSetOverviewRow["statusLabel"] {
  if (!run) {
    return "No Data";
  }
  if (run.status === "failed") {
    return "Critical";
  }
  if (run.status === "queued") {
    return "Queued";
  }
  if (run.status === "running") {
    return "Running";
  }
  if (run.score != null) {
    const normalized = normalizeRate(run.score);
    if (normalized != null && normalized >= 0.85) {
      return "Stable";
    }
    if (normalized != null && normalized >= 0.7) {
      return "Degraded";
    }
    if (normalized != null) {
      return "Critical";
    }
  }
  return run.statusLabel;
}

function nextRunEtaLabel(): string {
  const now = new Date();
  const next = new Date(now);
  next.setHours(
    now.getHours() + 3,
    now.getMinutes() + 24,
    now.getSeconds() + 12,
  );
  const diffMs = Math.max(0, next.getTime() - now.getTime());
  const totalSeconds = Math.floor(diffMs / 1000);
  const hours = Math.floor(totalSeconds / 3600)
    .toString()
    .padStart(2, "0");
  const minutes = Math.floor((totalSeconds % 3600) / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

export function EvaluationsPage({ initialRunId = null }: EvaluationsPageProps) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { state } = useAuthSession();

  const runModalRef = useRef<HTMLDivElement | null>(null);
  const createSetModalRef = useRef<HTMLDivElement | null>(null);

  const role = state.session?.role ?? null;
  const canCreateSet = role === "owner" || role === "admin";
  const canManageQuestions =
    role === "owner" || role === "admin" || role === "member";
  const canRun = role === "owner" || role === "admin";
  const canAdmin = role === "owner" || role === "admin";

  const [selectedSetPreferenceId, setSelectedSetPreferenceId] = useState<
    string | null
  >(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [compareRunId, setCompareRunId] = useState<string | null>(null);
  const [resultOffsetByRunId, setResultOffsetByRunId] = useState<
    Record<string, number>
  >({});
  const [runHistory] = useState<EvaluationRunHistoryRecord[]>(() =>
    readEvaluationRunHistory(),
  );

  const [runFilters, setRunFilters] = useState<RunFilters>(runFiltersDefaults);
  const [resultFilters, setResultFilters] = useState<ResultFilters>(
    resultFiltersDefaults,
  );
  const [datasetSearch, setDatasetSearch] = useState("");
  const [questionFilters, setQuestionFilters] =
    useState<DatasetQuestionFilters>(questionFiltersDefaults);

  const [isRunDialogOpen, setIsRunDialogOpen] = useState(false);
  const [isCreateSetDialogOpen, setIsCreateSetDialogOpen] = useState(false);

  const [createSetName, setCreateSetName] = useState("");
  const [createSetDescription, setCreateSetDescription] = useState("");
  const [createSetError, setCreateSetError] = useState<string | null>(null);

  const [addQuestionDraft, setAddQuestionDraft] = useState<AddQuestionDraft>(
    questionDraftDefaults,
  );
  const [addQuestionError, setAddQuestionError] = useState<string | null>(null);

  const [runTopK, setRunTopK] = useState(5);
  const [runRerank, setRunRerank] = useState(true);
  const [runModelName, setRunModelName] = useState("");
  const [runMetricOptions, setRunMetricOptions] = useState("");
  const [runModelProfileId, setRunModelProfileId] = useState("");
  const [runDocumentIds, setRunDocumentIds] = useState<string[]>([]);
  const [runChunkingProfileIds, setRunChunkingProfileIds] = useState<string[]>(
    [],
  );
  const [runRegressionThresholds, setRunRegressionThresholds] =
    useState<RegressionThresholdDraft>(regressionThresholdDefaults);
  const [runError, setRunError] = useState<string | null>(null);

  useOverlayFocus({
    isOpen: isRunDialogOpen,
    containerRef: runModalRef,
    onClose: () => setIsRunDialogOpen(false),
  });
  useOverlayFocus({
    isOpen: isCreateSetDialogOpen,
    containerRef: createSetModalRef,
    onClose: () => setIsCreateSetDialogOpen(false),
  });

  const setsQuery = useQuery({
    queryKey: queryKeys.evaluations.sets,
    queryFn: () =>
      listEvaluationSets({ limit: EVALUATION_SET_LIMIT, offset: 0 }),
  });

  const setItems = useMemo(
    () => setsQuery.data?.items ?? [],
    [setsQuery.data?.items],
  );

  const selectedSetId = useMemo(() => {
    if (setItems.length === 0) {
      return null;
    }
    if (
      selectedSetPreferenceId &&
      setItems.some(
        (setItem) => setItem.evaluation_set_id === selectedSetPreferenceId,
      )
    ) {
      return selectedSetPreferenceId;
    }
    return setItems[0].evaluation_set_id;
  }, [selectedSetPreferenceId, setItems]);

  const selectedSet =
    setItems.find((setItem) => setItem.evaluation_set_id === selectedSetId) ??
    null;

  const routeRunIdRaw = initialRunId ?? searchParams.get("runId");
  const routeRunId =
    routeRunIdRaw && routeRunIdRaw.trim() ? routeRunIdRaw.trim() : null;

  const latestRunBySet = useMemo(() => {
    const map = new Map<string, string>();
    const sorted = [...runHistory].sort((left, right) => {
      const leftTs = Date.parse(left.updatedAt);
      const rightTs = Date.parse(right.updatedAt);
      return (
        (Number.isFinite(rightTs) ? rightTs : 0) -
        (Number.isFinite(leftTs) ? leftTs : 0)
      );
    });
    for (const row of sorted) {
      if (!map.has(row.datasetId)) {
        map.set(row.datasetId, row.runId);
      }
    }
    return map;
  }, [runHistory]);

  const activeRunId =
    routeRunId ??
    selectedRunId ??
    (selectedSetId ? (latestRunBySet.get(selectedSetId) ?? null) : null);

  const resultOffset = resultOffsetByRunId[activeRunId ?? "__none__"] ?? 0;

  const questionsQuery = useQuery({
    queryKey: queryKeys.evaluations.setQuestions(selectedSetId ?? "", {
      limit: EVALUATION_QUESTION_LIMIT,
      offset: 0,
    }),
    queryFn: () => {
      if (!selectedSetId) {
        throw new Error("Evaluation set is required.");
      }
      return listEvaluationQuestions(selectedSetId, {
        limit: EVALUATION_QUESTION_LIMIT,
        offset: 0,
      });
    },
    enabled: Boolean(selectedSetId),
  });

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

  const modelProfilesQuery = useQuery({
    queryKey: queryKeys.modelProfiles.list,
    queryFn: listModelProfiles,
    staleTime: 60_000,
  });

  const chunkingProfilesQuery = useQuery({
    queryKey: queryKeys.admin.chunkingProfiles,
    queryFn: listChunkingProfiles,
    enabled: canRun,
  });

  const runDetailQuery = useQuery({
    queryKey: queryKeys.evaluations.run(activeRunId ?? "", {
      limit: EVALUATION_RESULTS_PAGE_SIZE,
      offset: resultOffset,
    }),
    queryFn: () => {
      if (!activeRunId) {
        throw new Error("Evaluation run is required.");
      }
      return getEvaluationRun(activeRunId, {
        limit: EVALUATION_RESULTS_PAGE_SIZE,
        offset: resultOffset,
      });
    },
    enabled: Boolean(activeRunId),
    refetchInterval: (query) => {
      const run = query.state.data;
      if (!run) {
        return RUN_POLL_INTERVAL_MS;
      }
      return run.status === "queued" || run.status === "running"
        ? RUN_POLL_INTERVAL_MS
        : false;
    },
  });

  const createSetMutation = useMutation({
    mutationFn: createEvaluationSet,
    onSuccess: async (created) => {
      setCreateSetName("");
      setCreateSetDescription("");
      setCreateSetError(null);
      setIsCreateSetDialogOpen(false);
      setSelectedSetPreferenceId(created.evaluation_set_id);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.sets,
      });
    },
    onError: (error) => setCreateSetError(getApiErrorMessage(error)),
  });

  const addQuestionMutation = useMutation({
    mutationFn: async () => {
      if (!selectedSetId) {
        throw new Error("Select an evaluation set first.");
      }
      if (!addQuestionDraft.question.trim()) {
        throw new Error("Question is required.");
      }

      const expectedPage = normalizePage(addQuestionDraft.expectedPage);
      const tags = parseTagsCsv(addQuestionDraft.tags);

      return createEvaluationQuestion(selectedSetId, {
        question: addQuestionDraft.question.trim(),
        expected_answer: addQuestionDraft.expectedAnswer.trim() || null,
        expected_page_number: expectedPage,
        expected_document_id: null,
        tags,
      });
    },
    onSuccess: async () => {
      setAddQuestionDraft(questionDraftDefaults());
      setAddQuestionError(null);
      if (selectedSetId) {
        await queryClient.invalidateQueries({
          queryKey: queryKeys.evaluations.setQuestions(selectedSetId, {
            limit: EVALUATION_QUESTION_LIMIT,
            offset: 0,
          }),
        });
      }
      await queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.sets,
      });
    },
    onError: (error) => setAddQuestionError(getApiErrorMessage(error)),
  });

  const runMutation = useMutation({
    mutationFn: async () => {
      if (!selectedSetId) {
        throw new Error("Select an evaluation set before running.");
      }
      if (!canRun) {
        throw new Error("Only owner/admin can queue evaluation runs.");
      }

      const metricOptions = parseMetricOptionsJson(runMetricOptions);
      const regressionThresholds = parseRegressionThresholds(
        runRegressionThresholds,
      );
      const modelName = runModelName.trim() || null;
      const topK = Math.max(MIN_TOP_K, Math.min(MAX_TOP_K, runTopK));
      const selectedChunkingProfileIds = Array.from(
        new Set(runChunkingProfileIds),
      );
      if (selectedChunkingProfileIds.length > 6) {
        throw new Error(
          "Choose at most 6 chunking profiles per evaluation run.",
        );
      }

      return runEvaluation({
        evaluation_set_id: selectedSetId,
        config: {
          top_k: topK,
          rerank: runRerank,
          model_name: modelName,
          model_profile_id: runModelProfileId.trim() || undefined,
          selected_document_ids: runDocumentIds,
          metric_options: metricOptions,
          chunking_profile_id:
            selectedChunkingProfileIds.length === 1
              ? selectedChunkingProfileIds[0]
              : undefined,
          comparison_targets:
            selectedChunkingProfileIds.length > 1
              ? selectedChunkingProfileIds.map((profileId) => ({
                  chunking_profile_id: profileId,
                }))
              : undefined,
          regression_thresholds: regressionThresholds,
        },
      });
    },
    onSuccess: async (result) => {
      setRunError(null);
      setIsRunDialogOpen(false);
      setSelectedRunId(result.evaluation_run_id);
      setResultOffsetByRunId((previous) => ({
        ...previous,
        [result.evaluation_run_id]: 0,
      }));
      await queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.sets,
      });
      router.push(
        `/evaluations/runs/${encodeURIComponent(result.evaluation_run_id)}`,
      );
    },
    onError: (error) => {
      if (isApiClientError(error) && error.status === 409) {
        setRunError(
          "An evaluation run is already active for this set. Open the existing run or wait for completion.",
        );
        return;
      }
      setRunError(getApiErrorMessage(error));
    },
  });

  const indexedDocuments = useMemo(
    () =>
      (documentsQuery.data?.items ?? []).filter(
        (document) => document.status === "indexed",
      ),
    [documentsQuery.data?.items],
  );

  const runDetail = runDetailQuery.data ?? null;

  useEffect(() => {
    if (!runDetail) {
      return;
    }

    const dataset =
      setItems.find(
        (setItem) => setItem.evaluation_set_id === runDetail.evaluation_set_id,
      ) ?? null;
    const item = buildRunListItemFromDetail({
      run: runDetail,
      dataset,
      source: "live",
    });

    const historyRow: EvaluationRunHistoryRecord = {
      runId: item.runId,
      runName: item.runName,
      datasetId: item.datasetId,
      datasetName: item.datasetName,
      status: item.status,
      score: item.score,
      regressions: item.regressions,
      startedBy: item.startedBy,
      passRate: item.passRate,
      citationAccuracy: item.citationAccuracy,
      retrievalHitRate: item.retrievalHitRate,
      latencyMsAverage: item.latencyMsAverage,
      costUsdTotal: item.costUsdTotal,
      durationMs: item.durationMs,
      startedAt: item.startedAt,
      completedAt: item.completedAt,
      createdAt: item.createdAt,
      updatedAt: item.updatedAt,
      isComparisonAvailable: item.isComparisonAvailable,
    };

    upsertEvaluationRunHistory(historyRow);
  }, [runDetail, setItems]);

  const mergedRuns = useMemo(() => {
    const historyRows: EvaluationRunListItem[] = runHistory.map((row) => ({
      runId: row.runId,
      runName: row.runName,
      datasetId: row.datasetId,
      datasetName: row.datasetName,
      status: row.status,
      statusLabel: runStatusLabel(row.status),
      score: row.score,
      regressions: row.regressions,
      startedBy: row.startedBy,
      passRate: row.passRate,
      citationAccuracy: row.citationAccuracy,
      retrievalHitRate: row.retrievalHitRate,
      latencyMsAverage: row.latencyMsAverage,
      costUsdTotal: row.costUsdTotal,
      durationMs: row.durationMs,
      startedAt: row.startedAt,
      completedAt: row.completedAt,
      createdAt: row.createdAt,
      updatedAt: row.updatedAt,
      isComparisonAvailable: row.isComparisonAvailable,
      source: "history",
    }));

    const map = new Map<string, EvaluationRunListItem>();
    for (const row of historyRows) {
      map.set(row.runId, row);
    }

    if (runDetail) {
      const dataset =
        setItems.find(
          (setItem) =>
            setItem.evaluation_set_id === runDetail.evaluation_set_id,
        ) ?? null;
      map.set(
        runDetail.evaluation_run_id,
        buildRunListItemFromDetail({
          run: runDetail,
          dataset,
          source: "live",
        }),
      );
    }

    return [...map.values()];
  }, [runDetail, runHistory, setItems]);

  const filteredRuns = useMemo(
    () => filterAndSortRuns(mergedRuns, runFilters),
    [mergedRuns, runFilters],
  );

  const questions = useMemo(
    () => questionsQuery.data?.items ?? [],
    [questionsQuery.data?.items],
  );
  const caseRows = useMemo(
    () =>
      buildCaseViews({
        results: runDetail?.results.items ?? [],
        questions,
        lowScoreThreshold: LOW_SCORE_THRESHOLD,
      }),
    [questions, runDetail?.results.items],
  );

  const filteredCaseRows = useMemo(
    () => filterAndSortCaseViews(caseRows, resultFilters),
    [caseRows, resultFilters],
  );

  const activeRunSummaryItem =
    mergedRuns.find((run) => run.runId === activeRunId) ??
    filteredRuns[0] ??
    null;

  const runsSortedByUpdated = useMemo(
    () =>
      [...mergedRuns].sort(
        (left, right) =>
          Date.parse(right.updatedAt || right.createdAt) -
          Date.parse(left.updatedAt || left.createdAt),
      ),
    [mergedRuns],
  );

  const latestRunByDataset = useMemo(() => {
    const map = new Map<string, EvaluationRunListItem>();
    for (const run of runsSortedByUpdated) {
      if (!map.has(run.datasetId)) {
        map.set(run.datasetId, run);
      }
    }
    return map;
  }, [runsSortedByUpdated]);

  const previousRunForActiveSet = useMemo(() => {
    if (!activeRunSummaryItem) {
      return null;
    }
    const candidates = runsSortedByUpdated.filter(
      (candidate) =>
        candidate.datasetId === activeRunSummaryItem.datasetId &&
        candidate.runId !== activeRunSummaryItem.runId,
    );
    return candidates[0] ?? null;
  }, [activeRunSummaryItem, runsSortedByUpdated]);

  const retrievalDelta =
    activeRunSummaryItem?.retrievalHitRate != null &&
    previousRunForActiveSet?.retrievalHitRate != null
      ? activeRunSummaryItem.retrievalHitRate -
        previousRunForActiveSet.retrievalHitRate
      : null;
  const citationDelta =
    activeRunSummaryItem?.citationAccuracy != null &&
    previousRunForActiveSet?.citationAccuracy != null
      ? activeRunSummaryItem.citationAccuracy -
        previousRunForActiveSet.citationAccuracy
      : null;
  const passRateDelta =
    activeRunSummaryItem?.passRate != null &&
    previousRunForActiveSet?.passRate != null
      ? activeRunSummaryItem.passRate - previousRunForActiveSet.passRate
      : null;
  const faithfulnessDelta =
    runDetail?.summary != null && previousRunForActiveSet?.runId != null
      ? null
      : null;

  const kpiItems: EvaluationKpiItem[] = [
    {
      id: "retrieval-hit-rate",
      label: "Hit Rate @ 10",
      value:
        activeRunSummaryItem?.retrievalHitRate != null
          ? `${((normalizeRate(activeRunSummaryItem.retrievalHitRate) ?? 0) * 100).toFixed(1)}%`
          : "N/A",
      helper: "Retrieved relevant chunks for evaluated questions",
      trendLabel: resolveKpiTrendLabel(retrievalDelta),
      trendTone:
        retrievalDelta == null
          ? "muted"
          : retrievalDelta > 0
            ? "good"
            : retrievalDelta < 0
              ? "bad"
              : "muted",
      sparkline: retrievalDelta != null && retrievalDelta < 0 ? "drop" : "rise",
      tone: kpiToneFromScore(activeRunSummaryItem?.retrievalHitRate ?? null),
      unavailable: activeRunSummaryItem?.retrievalHitRate == null,
    },
    {
      id: "citation-accuracy",
      label: "Precision",
      value:
        activeRunSummaryItem?.citationAccuracy != null
          ? (normalizeRate(activeRunSummaryItem.citationAccuracy) ?? 0).toFixed(
              2,
            )
          : "N/A",
      helper: "Citation-grounding precision",
      trendLabel: resolveKpiTrendLabel(citationDelta),
      trendTone:
        citationDelta == null
          ? "muted"
          : citationDelta > 0
            ? "good"
            : citationDelta < 0
              ? "bad"
              : "muted",
      sparkline: "flat",
      tone: kpiToneFromScore(activeRunSummaryItem?.citationAccuracy ?? null),
      unavailable: activeRunSummaryItem?.citationAccuracy == null,
    },
    {
      id: "pass-rate",
      label: "Recall",
      value:
        activeRunSummaryItem?.passRate != null
          ? (normalizeRate(activeRunSummaryItem.passRate) ?? 0).toFixed(2)
          : "N/A",
      helper: "Case success coverage",
      trendLabel: resolveKpiTrendLabel(passRateDelta),
      trendTone:
        passRateDelta == null
          ? "muted"
          : passRateDelta > 0
            ? "good"
            : passRateDelta < 0
              ? "bad"
              : "muted",
      sparkline: passRateDelta != null && passRateDelta < 0 ? "drop" : "rise",
      tone: kpiToneFromScore(activeRunSummaryItem?.passRate ?? null),
      unavailable: activeRunSummaryItem?.passRate == null,
    },
    {
      id: "faithfulness",
      label: "Faithfulness",
      value:
        runDetail?.summary != null
          ? `${((normalizeRate(metricFromSummary(runDetail.summary, ["faithfulness_score"])) ?? 0) * 100).toFixed(1)}%`
          : "N/A",
      helper: "Grounding faithfulness score",
      trendLabel: resolveKpiTrendLabel(faithfulnessDelta),
      trendTone: "muted",
      sparkline: "wave",
      tone: kpiToneFromScore(
        runDetail?.summary != null
          ? normalizeRate(
              metricFromSummary(runDetail.summary, ["faithfulness_score"]),
            )
          : null,
      ),
      unavailable: runDetail?.summary == null,
    },
  ];

  const runOwnerOptions = useMemo(() => {
    const owners = new Set<string>();
    for (const run of mergedRuns) {
      owners.add(run.startedBy ?? "unavailable");
    }
    return [...owners].sort((left, right) => left.localeCompare(right));
  }, [mergedRuns]);

  const datasetOptions = setItems.map((setItem) => ({
    id: setItem.evaluation_set_id,
    name: setItem.name,
  }));

  const setOverviewRows = useMemo<EvaluationSetOverviewRow[]>(() => {
    return setItems.map((setItem) => {
      const latestRun = latestRunByDataset.get(setItem.evaluation_set_id);
      return {
        setId: setItem.evaluation_set_id,
        name: setItem.name,
        author: latestRun?.startedBy ?? "Unavailable",
        questionCount: setItem.question_count,
        latencyMs: latestRun?.latencyMsAverage ?? null,
        score: latestRun?.score ?? null,
        statusLabel: setStatusLabel(latestRun),
        statusTone: setStatusToneFromScore(latestRun?.score ?? null),
      };
    });
  }, [latestRunByDataset, setItems]);

  const recentRunItems = useMemo(
    () =>
      runsSortedByUpdated.slice(0, 4).map((run) => ({
        runId: run.runId,
        runName: run.runName,
        status: run.status,
        createdAt: run.createdAt,
        durationMs: run.durationMs,
        modelLabel: run.source === "live" ? "LLM: Configured" : null,
        rerankerLabel: run.source === "live" ? "Reranker: Configured" : null,
      })),
    [runsSortedByUpdated],
  );

  const listForbidden =
    isForbiddenError(setsQuery.error) || isForbiddenError(questionsQuery.error);
  if (listForbidden) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Evaluation access is restricted"
          description="Your role does not have permission to view evaluations in this organization."
          requestId={extractRequestIdFromError(
            setsQuery.error ?? questionsQuery.error,
          )}
        />
      </section>
    );
  }

  const listUnavailable =
    setsQuery.isError &&
    isApiClientError(setsQuery.error) &&
    setsQuery.error.status === 503;

  return (
    <section className="space-y-8 px-4 py-5 lg:px-8 lg:py-8">
      <EvaluationsPageHeader
        canRun={canRun}
        canCreateSet={canCreateSet}
        runDisabledReason="Only owner/admin can start evaluation runs."
        onStartRun={() => {
          setRunError(null);
          setIsRunDialogOpen(true);
        }}
        onCreateSet={() => {
          setCreateSetError(null);
          setIsCreateSetDialogOpen(true);
        }}
      />

      {listUnavailable ? (
        <ErrorState
          title="Evaluation backend is currently unavailable"
          description="Evaluation endpoints are temporarily unavailable. Retry shortly."
          error={setsQuery.error}
          onRetry={() => void setsQuery.refetch()}
        />
      ) : null}

      <EvaluationKpiGrid items={kpiItems} />

      <section className="grid grid-cols-1 gap-8 xl:grid-cols-12">
        <div className="xl:col-span-8">
          {setsQuery.isLoading ? (
            <RunsTableSkeleton />
          ) : setsQuery.isError && !listUnavailable ? (
            <ErrorState
              compact
              error={setsQuery.error}
              description={getApiErrorMessage(setsQuery.error)}
              onRetry={() => void setsQuery.refetch()}
            />
          ) : (
            <EvaluationSetsOverviewTable
              rows={setOverviewRows}
              selectedSetId={selectedSetId}
              canCreateSet={canCreateSet}
              onCreateSet={() => {
                setCreateSetError(null);
                setIsCreateSetDialogOpen(true);
              }}
              onSelectSet={(setId) => {
                setSelectedSetPreferenceId(setId);
                const latestRunId = latestRunBySet.get(setId) ?? null;
                setSelectedRunId(latestRunId);
              }}
            />
          )}
        </div>

        <div className="xl:col-span-4">
          <RecentRunsPanel
            items={recentRunItems}
            activeRunId={activeRunId}
            onSelectRun={(runId) => {
              setSelectedRunId(runId);
              setResultOffsetByRunId((previous) => ({
                ...previous,
                [runId]: 0,
              }));
              router.push(`/evaluations/runs/${encodeURIComponent(runId)}`);
            }}
          />
        </div>
      </section>

      <EvaluationInsightsRow
        retrievalP95Ms={metricFromSummary(runDetail?.summary, [
          "retrieval_p95_ms",
          "retrieval_latency_p95_ms",
          "retrieval_latency_ms_p95",
        ])}
        generationP95Ms={metricFromSummary(runDetail?.summary, [
          "generation_p95_ms",
          "generation_latency_p95_ms",
          "generation_latency_ms_p95",
          "latency_ms_average",
        ])}
        hallucinationRisk={normalizeRate(
          metricFromSummary(runDetail?.summary, [
            "context_hallucination_risk",
            "hallucination_risk",
            "hallucination_rate",
          ]),
        )}
        hallucinationRiskDelta={metricFromSummary(runDetail?.summary, [
          "context_hallucination_risk_delta",
          "hallucination_risk_delta",
        ])}
        nextRunLabel={
          selectedSet?.name
            ? `${selectedSet.name} Baseline`
            : "Nightly Baseline"
        }
        nextRunEta={nextRunEtaLabel()}
        onTriggerRun={() => {
          setRunError(null);
          setIsRunDialogOpen(true);
        }}
        triggerDisabled={!canRun}
      />

      <section
        id="evaluation-inspector"
        className="space-y-3 rounded-xl border border-gray-200 bg-white p-4 shadow-sm"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-gray-900">Run inspector</h2>
          <p className="text-sm text-gray-500">
            Search, filter, and compare runs before drilling into failed cases.
          </p>
        </div>

        <EvaluationRunsFilterBar
          filters={runFilters}
          datasetOptions={datasetOptions}
          ownerOptions={runOwnerOptions}
          onChange={setRunFilters}
          onReset={() => setRunFilters(runFiltersDefaults())}
        />

        {setsQuery.isLoading ? (
          <RunsTableSkeleton />
        ) : setsQuery.isError && !listUnavailable ? (
          <ErrorState
            compact
            error={setsQuery.error}
            description={getApiErrorMessage(setsQuery.error)}
            onRetry={() => void setsQuery.refetch()}
          />
        ) : filteredRuns.length === 0 ? (
          <div className="space-y-3">
            <EmptyState
              compact
              title="No evaluation runs yet"
              description="Start your first run once a dataset has test cases."
            />
            <OnboardingCtaBanner
              title="Build your knowledge base first"
              description="Upload and index documents, then chat with them before setting up evaluations. The Getting Started checklist walks you through each step."
              actionLabel="Upload documents"
              actionHref="/documents"
              secondaryLabel="Go to Chat"
              secondaryHref="/chat"
            />
          </div>
        ) : (
          <EvaluationRunsTable
            runs={filteredRuns}
            activeRunId={activeRunId}
            compareRunId={compareRunId}
            onSelectRun={(runId) => {
              setSelectedRunId(runId);
              setCompareRunId(null);
              setResultOffsetByRunId((previous) => ({
                ...previous,
                [runId]: 0,
              }));
              router.push(`/evaluations/runs/${encodeURIComponent(runId)}`);
            }}
            onCompareWith={(runId) => {
              if (activeRunId && runId !== activeRunId) {
                setCompareRunId(runId);
              }
            }}
          />
        )}
      </section>

      {activeRunId ? (
        runDetailQuery.isLoading ? (
          <EvaluationRunDetailSkeleton />
        ) : runDetailQuery.isError ? (
          isForbiddenError(runDetailQuery.error) ? (
            <ForbiddenState
              compact
              title="Run detail is restricted"
              description="You do not have permission to inspect this evaluation run."
              requestId={extractRequestIdFromError(runDetailQuery.error)}
            />
          ) : isApiClientError(runDetailQuery.error) &&
            runDetailQuery.error.status === 404 ? (
            <EmptyState
              title="Run not found or inaccessible"
              description="The run may belong to a different organization or was removed."
            />
          ) : (
            <ErrorState
              error={runDetailQuery.error}
              description={getApiErrorMessage(runDetailQuery.error)}
              onRetry={() => void runDetailQuery.refetch()}
            />
          )
        ) : runDetail ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setCompareRunId(null)}
                className={`rounded border px-3 py-1.5 text-xs font-semibold ${
                  !compareRunId
                    ? "border-[#8b5cf6] bg-[#8b5cf6] text-white"
                    : "border-[#cbc6dd] text-[#403b5f] hover:bg-gray-50"
                }`}
              >
                Run detail
              </button>
              {compareRunId && (
                <button
                  type="button"
                  onClick={() => {}}
                  className="rounded border border-[#8b5cf6] bg-[#8b5cf6] px-3 py-1.5 text-xs font-semibold text-white"
                >
                  Comparison view
                </button>
              )}
              {!compareRunId && filteredRuns.length > 1 && (
                <span className="text-xs text-gray-400">
                  Select a second run in the table above to compare
                </span>
              )}
            </div>

            {compareRunId && activeRunId ? (
              <RunComparisonPanel
                runAId={activeRunId}
                runBId={compareRunId}
                onClose={() => setCompareRunId(null)}
              />
            ) : (
              <>
                <EvaluationRunDetailSection
                  run={runDetail}
                  datasetName={
                    setItems.find(
                      (setItem) =>
                        setItem.evaluation_set_id ===
                        runDetail.evaluation_set_id,
                    )?.name ?? runDetail.evaluation_set_id
                  }
                  comparison={buildRunComparison(runDetail.summary)}
                  failureReason={runDetail.failure_reason ?? null}
                  failureType={runDetail.failure_type ?? null}
                />

                <EvaluationCasesSection
                  rows={filteredCaseRows}
                  filters={resultFilters}
                  onFilterChange={setResultFilters}
                />

                <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#ddd8ec] bg-white px-3 py-2">
                  <p className="text-sm text-[#66627d]">
                    Page{" "}
                    {Math.floor(resultOffset / EVALUATION_RESULTS_PAGE_SIZE) +
                      1}{" "}
                    of{" "}
                    {Math.max(
                      1,
                      Math.ceil(
                        (runDetail.results.total || 0) /
                          EVALUATION_RESULTS_PAGE_SIZE,
                      ),
                    )}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={resultOffset <= 0}
                      onClick={() =>
                        setResultOffsetByRunId((previous) => ({
                          ...previous,
                          [activeRunId]: Math.max(
                            0,
                            resultOffset - EVALUATION_RESULTS_PAGE_SIZE,
                          ),
                        }))
                      }
                      className="rounded border border-[#cbc6dd] px-2 py-1 text-xs font-semibold text-[#403b5f] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      disabled={
                        resultOffset + EVALUATION_RESULTS_PAGE_SIZE >=
                        runDetail.results.total
                      }
                      onClick={() =>
                        setResultOffsetByRunId((previous) => ({
                          ...previous,
                          [activeRunId]:
                            resultOffset + EVALUATION_RESULTS_PAGE_SIZE,
                        }))
                      }
                      className="rounded border border-[#cbc6dd] px-2 py-1 text-xs font-semibold text-[#403b5f] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        ) : null
      ) : (
        <EmptyState
          title="No run selected"
          description="Select a recent run or start a new run to inspect evaluation quality details."
        />
      )}

      <EvaluationSetsSection
        sets={setItems}
        selectedSetId={selectedSetId}
        onSelectSet={(setId) => {
          setSelectedSetPreferenceId(setId);
          const latestRunId = latestRunBySet.get(setId) ?? null;
          setSelectedRunId(latestRunId);
        }}
        isSetsLoading={setsQuery.isLoading}
        setsError={setsQuery.error}
        onRetrySets={() => void setsQuery.refetch()}
        setSearch={datasetSearch}
        onSetSearchChange={setDatasetSearch}
        questions={questions}
        isQuestionsLoading={questionsQuery.isLoading}
        questionsError={questionsQuery.error}
        onRetryQuestions={() => void questionsQuery.refetch()}
        questionFilters={questionFilters}
        onQuestionFiltersChange={setQuestionFilters}
        canManageQuestions={canManageQuestions}
        addQuestionDraft={addQuestionDraft}
        onAddQuestionDraftChange={setAddQuestionDraft}
        onAddQuestion={() => {
          setAddQuestionError(null);
          addQuestionMutation.mutate();
        }}
        addQuestionError={addQuestionError}
        isAddingQuestion={addQuestionMutation.isPending}
      />

      {selectedSet && (
        <DatasetBuilderPanel
          evaluationSet={selectedSet}
          questions={questions}
          canManage={canManageQuestions}
          canAdmin={canAdmin}
          onRefreshSet={() => void setsQuery.refetch()}
          onRefreshQuestions={() =>
            void queryClient.invalidateQueries({
              queryKey: queryKeys.evaluations.setQuestions(
                selectedSet.evaluation_set_id,
                { limit: EVALUATION_QUESTION_LIMIT, offset: 0 },
              ),
            })
          }
          onSetDeleted={() => {
            setSelectedSetPreferenceId(null);
            setSelectedRunId(null);
          }}
          onSetDuplicated={(newSetId) => {
            setSelectedSetPreferenceId(newSetId);
          }}
        />
      )}

      <CreateEvaluationSetDialog
        containerRef={createSetModalRef}
        isOpen={isCreateSetDialogOpen}
        isSubmitting={createSetMutation.isPending}
        name={createSetName}
        description={createSetDescription}
        error={createSetError}
        onNameChange={setCreateSetName}
        onDescriptionChange={setCreateSetDescription}
        onClose={() => {
          if (createSetMutation.isPending) {
            return;
          }
          setIsCreateSetDialogOpen(false);
        }}
        onSubmit={() => {
          if (!canCreateSet) {
            setCreateSetError("Only owner/admin can create evaluation sets.");
            return;
          }

          const normalizedName = createSetName.trim();
          if (!normalizedName) {
            setCreateSetError("Set name is required.");
            return;
          }

          setCreateSetError(null);
          createSetMutation.mutate({
            name: normalizedName,
            description: createSetDescription.trim() || null,
          });
        }}
      />

      <StartEvaluationRunDialog
        containerRef={runModalRef}
        isOpen={isRunDialogOpen}
        isSubmitting={runMutation.isPending}
        setName={selectedSet?.name ?? "Selected set"}
        topK={runTopK}
        rerank={runRerank}
        modelName={runModelName}
        metricOptions={runMetricOptions}
        selectedDocumentIds={runDocumentIds}
        chunkingProfiles={chunkingProfilesQuery.data?.profiles ?? []}
        isChunkingProfilesLoading={chunkingProfilesQuery.isLoading}
        chunkingProfilesError={chunkingProfilesQuery.error}
        selectedChunkingProfileIds={runChunkingProfileIds}
        regressionThresholds={runRegressionThresholds}
        indexedDocuments={indexedDocuments}
        isDocumentsLoading={documentsQuery.isLoading}
        documentsError={documentsQuery.error}
        error={runError}
        onClose={() => {
          if (runMutation.isPending) {
            return;
          }
          setIsRunDialogOpen(false);
        }}
        onSubmit={() => runMutation.mutate()}
        onTopKChange={(next) =>
          setRunTopK(Math.max(MIN_TOP_K, Math.min(MAX_TOP_K, next)))
        }
        onRerankChange={setRunRerank}
        onModelNameChange={setRunModelName}
        onMetricOptionsChange={setRunMetricOptions}
        onToggleDocument={(documentId) => {
          setRunDocumentIds((previous) =>
            previous.includes(documentId)
              ? previous.filter((value) => value !== documentId)
              : [...previous, documentId],
          );
        }}
        onToggleChunkingProfile={(profileId) => {
          setRunChunkingProfileIds((previous) =>
            previous.includes(profileId)
              ? previous.filter((value) => value !== profileId)
              : [...previous, profileId],
          );
        }}
        onRegressionThresholdChange={(key, value) => {
          setRunRegressionThresholds((previous) => ({
            ...previous,
            [key]: value,
          }));
        }}
        modelProfiles={modelProfilesQuery.data?.items ?? []}
        isModelProfilesLoading={modelProfilesQuery.isLoading}
        modelProfilesError={modelProfilesQuery.error}
        selectedModelProfileId={runModelProfileId}
        onModelProfileChange={setRunModelProfileId}
      />
    </section>
  );
}
