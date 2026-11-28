"use client";

import { useRef, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/states/EmptyState";
import { LanguageCoverageTable } from "@/components/evaluations/multilingual-eval-panel";
import {
  deleteEvaluationQuestion,
  deleteEvaluationSet,
  duplicateEvaluationSet,
  importEvaluationCases,
  listDatasetVersions,
  listEvaluationQuestions,
  publishEvaluationSet,
  updateEvaluationQuestion,
  updateEvaluationSet,
  validateEvaluationDataset,
  type DatasetValidationIssue,
  type EvaluationDatasetVersionResponse,
  type EvaluationQuestionResponse,
  type EvaluationSetResponse,
} from "@/lib/api/evaluations";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { parseTagsString } from "@/lib/schemas/evaluation-datasets";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

// ---------------------------------------------------------------------------
// Difficulty badge
// ---------------------------------------------------------------------------

const KNOWN_DIFFICULTIES = new Set(["easy", "medium", "hard"]);

/** Page size of the case list; "Load more" fetches this many more cases. */
export const DATASET_CASES_PAGE_SIZE = 50;

/**
 * Matches every cached question list of one evaluation set: the empty params
 * object partially matches any page size, so the builder's paged list and the
 * page's own list are refreshed together.
 */
function allSetQuestionsKey(evaluationSetId: string) {
  return queryKeys.evaluations.setQuestions(evaluationSetId);
}

function DifficultyBadge({ difficulty }: { difficulty: string | null }) {
  const t = useTranslations("evaluations.datasetBuilder");
  if (!difficulty) return null;
  const colors: Record<string, string> = {
    easy: "bg-green-50 text-green-700 border-green-200",
    medium: "bg-yellow-50 text-yellow-700 border-yellow-200",
    hard: "bg-red-50 text-red-700 border-red-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium capitalize ${colors[difficulty] ?? "border-gray-200 bg-gray-50 text-gray-600"}`}
    >
      {KNOWN_DIFFICULTIES.has(difficulty)
        ? t(`difficulty.${difficulty}`)
        : difficulty}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function DatasetStatusBadge({ status }: { status: string }) {
  const t = useTranslations("evaluations.datasetBuilder");
  const styles =
    status === "published"
      ? "bg-purple-50 text-purple-700 border-purple-200"
      : "bg-gray-50 text-gray-600 border-gray-200";
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold capitalize ${styles}`}
    >
      {status === "draft" || status === "published"
        ? t(`status.${status}`)
        : status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Validation panel
// ---------------------------------------------------------------------------

type ValidationPanelProps = {
  evaluationSetId: string;
};

function ValidationPanel({ evaluationSetId }: ValidationPanelProps) {
  const t = useTranslations("evaluations.datasetBuilder");
  const query = useQuery({
    queryKey: queryKeys.evaluations.setValidation(evaluationSetId),
    queryFn: () => validateEvaluationDataset(evaluationSetId),
    enabled: Boolean(evaluationSetId),
    staleTime: 30_000,
  });

  if (query.isLoading) {
    return (
      <p className="animate-pulse text-xs text-gray-400">{t("validating")}</p>
    );
  }

  if (query.isError || !query.data) {
    return null;
  }

  const { is_valid, issue_count, issues } = query.data;

  if (is_valid) {
    return <p className="text-xs font-medium text-green-700">{t("valid")}</p>;
  }

  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold text-red-700">
        {t("issuesFound", { count: issue_count })}
      </p>
      <ul className="space-y-1">
        {issues.slice(0, 5).map((issue: DatasetValidationIssue) => (
          <li
            key={issue.evaluation_question_id + issue.issue_type}
            className="rounded border border-red-100 bg-red-50 px-2 py-1 text-xs text-red-700"
          >
            <span className="font-medium capitalize">
              {issue.issue_type.replace(/_/g, " ")}
            </span>
            {" — "}
            {issue.question_preview}
          </li>
        ))}
        {issues.length > 5 && (
          <li className="text-xs text-gray-500">
            {t("moreIssues", { count: issues.length - 5 })}
          </li>
        )}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Versions panel
// ---------------------------------------------------------------------------

type VersionsPanelProps = {
  evaluationSetId: string;
};

function VersionsPanel({ evaluationSetId }: VersionsPanelProps) {
  const t = useTranslations("evaluations.datasetBuilder");
  const query = useQuery({
    queryKey: queryKeys.evaluations.setVersions(evaluationSetId),
    queryFn: () => listDatasetVersions(evaluationSetId),
    enabled: Boolean(evaluationSetId),
  });

  if (query.isLoading) {
    return (
      <p className="animate-pulse text-xs text-gray-400">
        {t("loadingVersions")}
      </p>
    );
  }

  const items = query.data?.items ?? [];

  if (items.length === 0) {
    return <p className="text-xs text-gray-400">{t("noVersions")}</p>;
  }

  return (
    <ul className="space-y-1">
      {items.map((version: EvaluationDatasetVersionResponse) => (
        <li
          key={version.version_id}
          className="flex items-center justify-between rounded border border-gray-100 bg-gray-50 px-2 py-1 text-xs text-gray-700"
        >
          <span className="font-semibold">v{version.version_number}</span>
          <span className="text-gray-500">
            {t("versionCases", { count: version.question_count })}
          </span>
          {version.published_at && (
            <span className="text-gray-400">
              {new Date(version.published_at).toLocaleDateString()}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Import dialog
// ---------------------------------------------------------------------------

type ImportDialogProps = {
  containerRef: React.RefObject<HTMLDivElement | null>;
  isOpen: boolean;
  evaluationSetId: string;
  onClose: () => void;
  onSuccess: (result: { imported: number; skipped: number }) => void;
};

function ImportDialog({
  containerRef,
  isOpen,
  evaluationSetId,
  onClose,
  onSuccess,
}: ImportDialogProps) {
  const t = useTranslations("evaluations.datasetBuilder");
  const [format, setFormat] = useState<"json" | "csv">("json");
  const [data, setData] = useState("");
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const importMutation = useMutation({
    mutationFn: () =>
      importEvaluationCases(evaluationSetId, {
        format,
        data,
        skip_duplicates: skipDuplicates,
      }),
    onSuccess: (result) => {
      setData("");
      setError(null);
      onSuccess({
        imported: result.imported,
        skipped: result.skipped_duplicates,
      });
      onClose();
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  if (!isOpen) return null;

  const placeholder =
    format === "json"
      ? '[{"question": "What is RAG?", "expected_answer": "...", "difficulty": "easy", "tags": "rag,retrieval"}]'
      : "question,expected_answer,difficulty\nWhat is RAG?,Retrieval Augmented Generation,easy";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#16162c]/55 px-4"
      onClick={onClose}
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-dialog-title"
        className="w-full max-w-2xl rounded-2xl border border-[#d8d4e8] bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="import-dialog-title"
          className="mb-4 text-base font-semibold text-gray-900"
        >
          {t("import.title")}
        </h2>

        <div className="mb-3 flex gap-2">
          {(["json", "csv"] as const).map((fmt) => (
            <button
              key={fmt}
              type="button"
              onClick={() => setFormat(fmt)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold uppercase transition-colors ${
                format === fmt
                  ? "border-[#6d5bd0] bg-[#6d5bd0] text-white"
                  : "border-gray-200 bg-white text-gray-600 hover:border-[#6d5bd0]"
              }`}
            >
              {fmt}
            </button>
          ))}
        </div>

        <textarea
          value={data}
          onChange={(e) => setData(e.target.value)}
          placeholder={placeholder}
          rows={8}
          className="mb-3 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 font-mono text-xs text-gray-800 focus:border-[#6d5bd0] focus:outline-none"
        />

        <label className="mb-4 flex cursor-pointer items-center gap-2 text-xs text-gray-600">
          <input
            type="checkbox"
            checked={skipDuplicates}
            onChange={(e) => setSkipDuplicates(e.target.checked)}
            className="rounded"
          />
          {t("import.skipDuplicates")}
        </label>

        {error && (
          <p className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={importMutation.isPending}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-60"
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            onClick={() => {
              setError(null);
              if (!data.trim()) {
                setError(t("import.required"));
                return;
              }
              importMutation.mutate();
            }}
            disabled={importMutation.isPending}
            className="rounded-lg bg-[#6d5bd0] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#5a4ab8] disabled:opacity-60"
          >
            {importMutation.isPending
              ? t("import.importing")
              : t("import.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Edit question inline dialog
// ---------------------------------------------------------------------------

type EditQuestionDialogProps = {
  containerRef: React.RefObject<HTMLDivElement | null>;
  isOpen: boolean;
  question: EvaluationQuestionResponse;
  evaluationSetId: string;
  onClose: () => void;
  onSaved: () => void;
};

function EditQuestionDialog({
  containerRef,
  isOpen,
  question,
  evaluationSetId,
  onClose,
  onSaved,
}: EditQuestionDialogProps) {
  const t = useTranslations("evaluations.datasetBuilder");
  const [text, setText] = useState(question.question);
  const [answer, setAnswer] = useState(question.expected_answer ?? "");
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard" | "">(
    (question.difficulty as "easy" | "medium" | "hard") ?? "",
  );
  const [tags, setTags] = useState(question.tags.join(", "));
  const [error, setError] = useState<string | null>(null);

  const updateMutation = useMutation({
    mutationFn: () =>
      updateEvaluationQuestion(
        evaluationSetId,
        question.evaluation_question_id,
        {
          question: text.trim() || undefined,
          expected_answer: answer.trim() || null,
          difficulty: difficulty || null,
          tags: parseTagsString(tags),
        },
      ),
    onSuccess: () => {
      setError(null);
      onSaved();
      onClose();
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#16162c]/55 px-4"
      onClick={onClose}
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-question-title"
        className="w-full max-w-lg rounded-2xl border border-[#d8d4e8] bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="edit-question-title"
          className="mb-4 text-base font-semibold text-gray-900"
        >
          {t("edit.title")}
        </h2>

        <label className="mb-2 block text-xs font-medium text-gray-700">
          {t("edit.question")}
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 focus:border-[#6d5bd0] focus:outline-none"
          />
        </label>

        <label className="mb-2 block text-xs font-medium text-gray-700">
          {t("edit.expectedAnswer")}
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={2}
            className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 focus:border-[#6d5bd0] focus:outline-none"
          />
        </label>

        <div className="mb-2 flex gap-3">
          <label className="flex-1 text-xs font-medium text-gray-700">
            {t("edit.difficulty")}
            <select
              value={difficulty}
              onChange={(e) =>
                setDifficulty(e.target.value as "easy" | "medium" | "hard" | "")
              }
              className="mt-1 w-full rounded-lg border border-gray-200 px-2 py-1.5 text-sm text-gray-800 focus:border-[#6d5bd0] focus:outline-none"
            >
              <option value="">{t("edit.none")}</option>
              <option value="easy">{t("edit.easy")}</option>
              <option value="medium">{t("edit.medium")}</option>
              <option value="hard">{t("edit.hard")}</option>
            </select>
          </label>
          <label className="flex-1 text-xs font-medium text-gray-700">
            {t("edit.tags")}
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-200 px-2 py-1.5 text-sm text-gray-800 focus:border-[#6d5bd0] focus:outline-none"
            />
          </label>
        </div>

        {error && (
          <p className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={updateMutation.isPending}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-60"
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            onClick={() => {
              if (!text.trim()) {
                setError(t("edit.questionRequired"));
                return;
              }
              setError(null);
              updateMutation.mutate();
            }}
            disabled={updateMutation.isPending}
            className="rounded-lg bg-[#6d5bd0] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#5a4ab8] disabled:opacity-60"
          >
            {updateMutation.isPending ? t("edit.saving") : t("edit.save")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Question row with inline edit/delete
// ---------------------------------------------------------------------------

type QuestionRowProps = {
  question: EvaluationQuestionResponse;
  evaluationSetId: string;
  canManage: boolean;
  onDeleted: () => void;
  onUpdated: () => void;
};

function QuestionRow({
  question,
  evaluationSetId,
  canManage,
  onDeleted,
  onUpdated,
}: QuestionRowProps) {
  const t = useTranslations("evaluations.datasetBuilder");
  const [isEditing, setIsEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const editDialogRef = useRef<HTMLDivElement | null>(null);

  useOverlayFocus({
    isOpen: isEditing,
    containerRef: editDialogRef,
    onClose: () => setIsEditing(false),
  });

  const deleteMutation = useMutation({
    mutationFn: () =>
      deleteEvaluationQuestion(
        evaluationSetId,
        question.evaluation_question_id,
      ),
    onSuccess: () => {
      setConfirmingDelete(false);
      onDeleted();
    },
  });

  return (
    <>
      <li className="group flex items-start gap-2 rounded-lg border border-gray-100 bg-white px-3 py-2 hover:border-[#cbc6dd]">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-gray-800">{question.question}</p>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <DifficultyBadge difficulty={question.difficulty ?? null} />
            {question.tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-xs text-gray-500"
              >
                {tag}
              </span>
            ))}
            {question.expected_answer && (
              <span className="text-xs text-gray-400 italic">
                {t("row.hasExpected")}
              </span>
            )}
          </div>
        </div>

        {canManage && (
          <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            <button
              type="button"
              onClick={() => setIsEditing(true)}
              className="rounded px-2 py-1 text-xs font-medium text-[#6d5bd0] hover:bg-[#f0eefb]"
            >
              {t("row.edit")}
            </button>
            {!confirmingDelete ? (
              <button
                type="button"
                onClick={() => setConfirmingDelete(true)}
                className="rounded px-2 py-1 text-xs font-medium text-red-500 hover:bg-red-50"
              >
                {t("row.delete")}
              </button>
            ) : (
              <div className="flex items-center gap-1">
                <span className="text-xs text-red-600">{t("row.sure")}</span>
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate()}
                  disabled={deleteMutation.isPending}
                  className="rounded px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-60"
                >
                  {t("row.yes")}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmingDelete(false)}
                  className="rounded px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-50"
                >
                  {t("row.no")}
                </button>
              </div>
            )}
          </div>
        )}
      </li>

      <EditQuestionDialog
        containerRef={editDialogRef}
        isOpen={isEditing}
        question={question}
        evaluationSetId={evaluationSetId}
        onClose={() => setIsEditing(false)}
        onSaved={onUpdated}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Dataset builder panel
// ---------------------------------------------------------------------------

export type DatasetBuilderPanelProps = {
  evaluationSet: EvaluationSetResponse;
  questions: EvaluationQuestionResponse[];
  canManage: boolean;
  canAdmin: boolean;
  onRefreshSet: () => void;
  onRefreshQuestions: () => void;
  onSetDeleted: () => void;
  onSetDuplicated: (newSetId: string) => void;
};

export function DatasetBuilderPanel({
  evaluationSet,
  questions,
  canManage,
  canAdmin,
  onRefreshSet,
  onRefreshQuestions,
  onSetDeleted,
  onSetDuplicated,
}: DatasetBuilderPanelProps) {
  const t = useTranslations("evaluations.datasetBuilder");
  const queryClient = useQueryClient();
  const setId = evaluationSet.evaluation_set_id;

  // Paged case list: the first page loads automatically, "Load more" fetches
  // the next DATASET_CASES_PAGE_SIZE cases via offset paging. The `questions`
  // prop (first page loaded by the parent) is shown until this query resolves.
  const casesQuery = useInfiniteQuery({
    queryKey: queryKeys.evaluations.setQuestions(setId, {
      view: "builder",
      limit: DATASET_CASES_PAGE_SIZE,
    }),
    queryFn: ({ pageParam }) =>
      listEvaluationQuestions(setId, {
        limit: DATASET_CASES_PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const next = lastPage.offset + lastPage.items.length;
      return lastPage.items.length > 0 && next < lastPage.total
        ? next
        : undefined;
    },
  });
  const pagedCases = casesQuery.data?.pages.flatMap((page) => page.items);
  const visibleCases = pagedCases ?? questions;
  const totalCases = casesQuery.data?.pages.at(-1)?.total ?? questions.length;

  const [isImportOpen, setIsImportOpen] = useState(false);
  const [isEditingMeta, setIsEditingMeta] = useState(false);
  const [editName, setEditName] = useState(evaluationSet.name);
  const [editDescription, setEditDescription] = useState(
    evaluationSet.description ?? "",
  );
  const [metaError, setMetaError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [importSuccess, setImportSuccess] = useState<string | null>(null);
  const [confirmDeleteSet, setConfirmDeleteSet] = useState(false);

  const importDialogRef = useRef<HTMLDivElement | null>(null);

  useOverlayFocus({
    isOpen: isImportOpen,
    containerRef: importDialogRef,
    onClose: () => setIsImportOpen(false),
  });

  const updateSetMutation = useMutation({
    mutationFn: () =>
      updateEvaluationSet(evaluationSet.evaluation_set_id, {
        name: editName.trim() || undefined,
        description: editDescription.trim() || null,
      }),
    onSuccess: () => {
      setMetaError(null);
      setIsEditingMeta(false);
      onRefreshSet();
      void queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.sets,
      });
    },
    onError: (err) => setMetaError(getApiErrorMessage(err)),
  });

  const publishMutation = useMutation({
    mutationFn: () => publishEvaluationSet(evaluationSet.evaluation_set_id),
    onSuccess: () => {
      setActionError(null);
      onRefreshSet();
      void queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.sets,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.setVersions(
          evaluationSet.evaluation_set_id,
        ),
      });
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  });

  const duplicateMutation = useMutation({
    mutationFn: () => duplicateEvaluationSet(evaluationSet.evaluation_set_id),
    onSuccess: (result) => {
      setActionError(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.sets,
      });
      onSetDuplicated(result.evaluation_set_id);
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  });

  const deleteSetMutation = useMutation({
    mutationFn: () => deleteEvaluationSet(evaluationSet.evaluation_set_id),
    onSuccess: () => {
      setConfirmDeleteSet(false);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.evaluations.sets,
      });
      onSetDeleted();
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  });

  return (
    <div className="space-y-4 rounded-xl border border-[#e0daf0] bg-white p-4 shadow-sm">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {isEditingMeta ? (
            <div className="space-y-2">
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="w-full rounded-lg border border-gray-200 px-2 py-1 text-sm font-semibold text-gray-900 focus:border-[#6d5bd0] focus:outline-none"
                placeholder={t("panel.namePlaceholder")}
              />
              <textarea
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                rows={2}
                className="w-full rounded-lg border border-gray-200 px-2 py-1 text-sm text-gray-600 focus:border-[#6d5bd0] focus:outline-none"
                placeholder={t("panel.descriptionPlaceholder")}
              />
              {metaError && <p className="text-xs text-red-600">{metaError}</p>}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => updateSetMutation.mutate()}
                  disabled={updateSetMutation.isPending}
                  className="rounded-lg bg-[#6d5bd0] px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-60"
                >
                  {updateSetMutation.isPending
                    ? t("edit.saving")
                    : t("edit.save")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setIsEditingMeta(false);
                    setEditName(evaluationSet.name);
                    setEditDescription(evaluationSet.description ?? "");
                  }}
                  className="rounded-lg border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600"
                >
                  {t("cancel")}
                </button>
              </div>
            </div>
          ) : (
            <div>
              <div className="flex items-center gap-2">
                <h3 className="truncate text-sm font-semibold text-gray-900">
                  {evaluationSet.name}
                </h3>
                <DatasetStatusBadge status={evaluationSet.status} />
                <span className="text-xs text-gray-400">
                  v{evaluationSet.version}
                </span>
              </div>
              {evaluationSet.description && (
                <p className="mt-0.5 truncate text-xs text-gray-500">
                  {evaluationSet.description}
                </p>
              )}
            </div>
          )}
        </div>

        {canManage && !isEditingMeta && (
          <button
            type="button"
            onClick={() => {
              setEditName(evaluationSet.name);
              setEditDescription(evaluationSet.description ?? "");
              setIsEditingMeta(true);
            }}
            className="shrink-0 rounded-lg border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:border-[#6d5bd0] hover:text-[#6d5bd0]"
          >
            {t("row.edit")}
          </button>
        )}
      </div>

      {/* Action bar */}
      {(canManage || canAdmin) && (
        <div className="flex flex-wrap gap-2">
          {canManage && (
            <button
              type="button"
              onClick={() => {
                setImportSuccess(null);
                setIsImportOpen(true);
              }}
              className="rounded-lg border border-[#cbc6dd] px-3 py-1.5 text-xs font-medium text-[#403b5f] hover:border-[#6d5bd0] hover:text-[#6d5bd0]"
            >
              {t("import.title")}
            </button>
          )}

          {canManage && (
            <button
              type="button"
              onClick={() => {
                setActionError(null);
                duplicateMutation.mutate();
              }}
              disabled={duplicateMutation.isPending}
              className="rounded-lg border border-[#cbc6dd] px-3 py-1.5 text-xs font-medium text-[#403b5f] hover:border-[#6d5bd0] hover:text-[#6d5bd0] disabled:opacity-60"
            >
              {duplicateMutation.isPending
                ? t("panel.duplicating")
                : t("panel.duplicate")}
            </button>
          )}

          {canAdmin && (
            <button
              type="button"
              onClick={() => {
                setActionError(null);
                publishMutation.mutate();
              }}
              disabled={
                publishMutation.isPending ||
                evaluationSet.status === "published"
              }
              title={
                evaluationSet.status === "published"
                  ? t("panel.alreadyPublished")
                  : undefined
              }
              className="rounded-lg border border-[#cbc6dd] px-3 py-1.5 text-xs font-medium text-[#403b5f] hover:border-[#6d5bd0] hover:text-[#6d5bd0] disabled:opacity-60"
            >
              {publishMutation.isPending
                ? t("panel.publishing")
                : t("panel.publish")}
            </button>
          )}

          {canAdmin && (
            <div className="ml-auto">
              {!confirmDeleteSet ? (
                <button
                  type="button"
                  onClick={() => setConfirmDeleteSet(true)}
                  className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
                >
                  {t("panel.deleteDataset")}
                </button>
              ) : (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-red-700">
                    {t("panel.deleteDatasetQuestion")}
                  </span>
                  <button
                    type="button"
                    onClick={() => deleteSetMutation.mutate()}
                    disabled={deleteSetMutation.isPending}
                    className="rounded-lg bg-red-600 px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-60"
                  >
                    {deleteSetMutation.isPending
                      ? t("panel.deleting")
                      : t("panel.yesDelete")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmDeleteSet(false)}
                    className="rounded-lg border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600"
                  >
                    {t("cancel")}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {importSuccess && (
        <p className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs font-medium text-green-700">
          {importSuccess}
        </p>
      )}

      {actionError && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {actionError}
        </p>
      )}

      {/* Validation */}
      <div>
        <p className="mb-1.5 text-xs font-semibold tracking-wide text-gray-400 uppercase">
          {t("panel.validation")}
        </p>
        <ValidationPanel evaluationSetId={evaluationSet.evaluation_set_id} />
      </div>

      {/* Versions */}
      <div>
        <p className="mb-1.5 text-xs font-semibold tracking-wide text-gray-400 uppercase">
          {t("panel.versionHistory")}
        </p>
        <VersionsPanel evaluationSetId={evaluationSet.evaluation_set_id} />
      </div>

      {/* Case list */}
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <p className="text-xs font-semibold tracking-wide text-gray-400 uppercase">
            {visibleCases.length < totalCases
              ? t("panel.casesPartial", {
                  loaded: visibleCases.length,
                  total: totalCases,
                })
              : t("panel.cases", { count: totalCases })}
          </p>
        </div>
        {visibleCases.length === 0 ? (
          <EmptyState
            compact
            title={t("panel.noCases")}
            description={t("panel.noCasesHint")}
          />
        ) : (
          <ul className="space-y-1.5">
            {visibleCases.map((q) => (
              <QuestionRow
                key={q.evaluation_question_id}
                question={q}
                evaluationSetId={evaluationSet.evaluation_set_id}
                canManage={canManage}
                onDeleted={() => {
                  void queryClient.invalidateQueries({
                    queryKey: allSetQuestionsKey(
                      evaluationSet.evaluation_set_id,
                    ),
                  });
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.evaluations.sets,
                  });
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.evaluations.setValidation(
                      evaluationSet.evaluation_set_id,
                    ),
                  });
                  onRefreshQuestions();
                }}
                onUpdated={() => {
                  void queryClient.invalidateQueries({
                    queryKey: allSetQuestionsKey(
                      evaluationSet.evaluation_set_id,
                    ),
                  });
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.evaluations.setValidation(
                      evaluationSet.evaluation_set_id,
                    ),
                  });
                  onRefreshQuestions();
                }}
              />
            ))}
          </ul>
        )}
        {casesQuery.hasNextPage ? (
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={() => void casesQuery.fetchNextPage()}
              disabled={casesQuery.isFetchingNextPage}
              className="rounded-lg border border-[#cbc6dd] px-3 py-1.5 text-xs font-medium text-[#403b5f] hover:border-[#6d5bd0] hover:text-[#6d5bd0] disabled:opacity-60"
            >
              {casesQuery.isFetchingNextPage
                ? t("panel.loadingMore")
                : t("panel.loadMore")}
            </button>
            {casesQuery.isFetchNextPageError ? (
              <span role="alert" className="text-xs text-red-700">
                {t("panel.loadMoreFailed")}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      <section aria-label={t("panel.languageCoverage")}>
        <h3 className="mb-2 text-sm font-semibold text-[#2f2a48]">
          {t("panel.languageCoverage")}
        </h3>
        <LanguageCoverageTable
          evaluationSetId={evaluationSet.evaluation_set_id}
        />
      </section>

      <ImportDialog
        containerRef={importDialogRef}
        isOpen={isImportOpen}
        evaluationSetId={evaluationSet.evaluation_set_id}
        onClose={() => setIsImportOpen(false)}
        onSuccess={({ imported, skipped }) => {
          setImportSuccess(
            skipped > 0
              ? t("panel.importedSkipped", { imported, skipped })
              : t("panel.imported", { imported }),
          );
          void queryClient.invalidateQueries({
            queryKey: allSetQuestionsKey(evaluationSet.evaluation_set_id),
          });
          void queryClient.invalidateQueries({
            queryKey: queryKeys.evaluations.sets,
          });
          void queryClient.invalidateQueries({
            queryKey: queryKeys.evaluations.setValidation(
              evaluationSet.evaluation_set_id,
            ),
          });
          onRefreshQuestions();
        }}
      />
    </div>
  );
}
