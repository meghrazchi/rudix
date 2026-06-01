import type { FormEvent } from "react";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import type {
  EvaluationQuestionResponse,
  EvaluationSetResponse,
} from "@/lib/api/evaluations";
import { getApiErrorMessage } from "@/lib/api/errors";

type DatasetQuestionFilters = {
  query: string;
  sortBy: "created_desc" | "created_asc" | "question_asc";
};

type AddQuestionDraft = {
  question: string;
  expectedAnswer: string;
  expectedPage: string;
  tags: string;
};

type EvaluationSetsSectionProps = {
  sets: EvaluationSetResponse[];
  selectedSetId: string | null;
  onSelectSet: (setId: string) => void;
  isSetsLoading: boolean;
  setsError: unknown;
  onRetrySets: () => void;
  setSearch: string;
  onSetSearchChange: (next: string) => void;
  questions: EvaluationQuestionResponse[];
  isQuestionsLoading: boolean;
  questionsError: unknown;
  onRetryQuestions: () => void;
  questionFilters: DatasetQuestionFilters;
  onQuestionFiltersChange: (next: DatasetQuestionFilters) => void;
  canManageQuestions: boolean;
  addQuestionDraft: AddQuestionDraft;
  onAddQuestionDraftChange: (next: AddQuestionDraft) => void;
  onAddQuestion: () => void;
  addQuestionError: string | null;
  isAddingQuestion: boolean;
};

function filteredSets(
  sets: EvaluationSetResponse[],
  query: string,
): EvaluationSetResponse[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return sets;
  }

  return sets.filter(
    (set) =>
      set.name.toLowerCase().includes(normalized) ||
      (set.description ?? "").toLowerCase().includes(normalized),
  );
}

function filteredQuestions(
  questions: EvaluationQuestionResponse[],
  filters: DatasetQuestionFilters,
): EvaluationQuestionResponse[] {
  const normalized = filters.query.trim().toLowerCase();
  const filtered = questions.filter((question) => {
    if (!normalized) {
      return true;
    }

    return (
      question.question.toLowerCase().includes(normalized) ||
      (question.expected_answer ?? "").toLowerCase().includes(normalized) ||
      (question.tags ?? []).some((tag) =>
        tag.toLowerCase().includes(normalized),
      )
    );
  });

  return [...filtered].sort((left, right) => {
    if (filters.sortBy === "created_asc") {
      return Date.parse(left.created_at) - Date.parse(right.created_at);
    }
    if (filters.sortBy === "question_asc") {
      return left.question.localeCompare(right.question);
    }
    return Date.parse(right.created_at) - Date.parse(left.created_at);
  });
}

export function EvaluationSetsSection({
  sets,
  selectedSetId,
  onSelectSet,
  isSetsLoading,
  setsError,
  onRetrySets,
  setSearch,
  onSetSearchChange,
  questions,
  isQuestionsLoading,
  questionsError,
  onRetryQuestions,
  questionFilters,
  onQuestionFiltersChange,
  canManageQuestions,
  addQuestionDraft,
  onAddQuestionDraftChange,
  onAddQuestion,
  addQuestionError,
  isAddingQuestion,
}: EvaluationSetsSectionProps) {
  const visibleSets = filteredSets(sets, setSearch);
  const selectedSet =
    sets.find((candidate) => candidate.evaluation_set_id === selectedSetId) ??
    null;

  const visibleQuestions = filteredQuestions(questions, questionFilters);

  return (
    <section
      className="grid gap-4 xl:grid-cols-[360px_1fr]"
      aria-label="Evaluation datasets and test cases"
    >
      <div className="rounded-2xl border border-[#d8d4e8] bg-white p-4 shadow-sm">
        <h2 className="text-lg font-semibold text-[#292442]">
          Evaluation datasets
        </h2>
        <p className="mt-1 text-sm text-[#66627d]">
          Select a dataset to inspect test cases and run configurations.
        </p>

        <label className="mt-3 grid gap-1 text-xs font-semibold tracking-wide text-[#645f7b] uppercase">
          Search datasets
          <input
            type="search"
            value={setSearch}
            onChange={(event) => onSetSearchChange(event.target.value)}
            placeholder="Dataset name"
            className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm font-medium tracking-normal text-[#2a2640] normal-case"
          />
        </label>

        <div className="mt-3">
          {isSetsLoading ? (
            <LoadingState compact title="Loading evaluation datasets..." />
          ) : setsError ? (
            <ErrorState
              compact
              error={setsError}
              description={getApiErrorMessage(setsError)}
              onRetry={onRetrySets}
            />
          ) : visibleSets.length === 0 ? (
            <EmptyState
              compact
              title="No datasets found."
              description="Create a set or change search filters."
            />
          ) : (
            <ul className="max-h-[420px] space-y-2 overflow-auto pr-1">
              {visibleSets.map((set) => (
                <li key={set.evaluation_set_id}>
                  <button
                    type="button"
                    onClick={() => onSelectSet(set.evaluation_set_id)}
                    className={`w-full rounded-lg border px-3 py-2 text-left ${
                      set.evaluation_set_id === selectedSetId
                        ? "border-[#3525cd] bg-[#f3f0ff]"
                        : "border-[#e5e1f1] bg-white hover:bg-[#faf8ff]"
                    }`}
                  >
                    <p className="text-sm font-semibold text-[#2f2a49]">
                      {set.name}
                    </p>
                    <p className="mt-1 text-xs text-[#66627d]">
                      {set.description ?? "No description"}
                    </p>
                    <p className="mt-1 text-xs text-[#66627d]">
                      {set.question_count} questions • updated{" "}
                      {new Date(set.updated_at).toLocaleDateString()}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="space-y-4 rounded-2xl border border-[#d8d4e8] bg-white p-4 shadow-sm">
        <div>
          <h2 className="text-lg font-semibold text-[#292442]">Test cases</h2>
          <p className="mt-1 text-sm text-[#66627d]">
            Search and sort expected questions/answers for dataset quality
            checks.
          </p>
        </div>

        {!selectedSet ? (
          <EmptyState
            compact
            title="Select a dataset to inspect test cases."
            description="Once selected, you can search and manage test cases."
          />
        ) : (
          <>
            <section className="grid gap-2 rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3 lg:grid-cols-3">
              <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#635e7b] uppercase lg:col-span-2">
                Search test cases
                <input
                  type="search"
                  value={questionFilters.query}
                  onChange={(event) =>
                    onQuestionFiltersChange({
                      ...questionFilters,
                      query: event.target.value,
                    })
                  }
                  placeholder="Question, expected answer, or tag"
                  className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm font-medium tracking-normal text-[#2a2640] normal-case"
                />
              </label>

              <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#635e7b] uppercase">
                Sort
                <select
                  value={questionFilters.sortBy}
                  onChange={(event) =>
                    onQuestionFiltersChange({
                      ...questionFilters,
                      sortBy: event.target
                        .value as DatasetQuestionFilters["sortBy"],
                    })
                  }
                  className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm font-medium tracking-normal text-[#2a2640] normal-case"
                >
                  <option value="created_desc">Newest first</option>
                  <option value="created_asc">Oldest first</option>
                  <option value="question_asc">Question A-Z</option>
                </select>
              </label>
            </section>

            {canManageQuestions ? (
              <form
                className="grid gap-2 rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3"
                onSubmit={(event: FormEvent<HTMLFormElement>) => {
                  event.preventDefault();
                  onAddQuestion();
                }}
              >
                <p className="text-sm font-semibold text-[#2f2a49]">
                  Add test case
                </p>

                <label className="grid gap-1">
                  <span className="text-xs font-semibold tracking-wide text-[#635e7b] uppercase">
                    Question
                  </span>
                  <textarea
                    rows={2}
                    value={addQuestionDraft.question}
                    onChange={(event) =>
                      onAddQuestionDraftChange({
                        ...addQuestionDraft,
                        question: event.target.value,
                      })
                    }
                    className="rounded-lg border border-[#d1cce4] px-2 py-1.5 text-sm text-[#2a2640]"
                    placeholder="What is the data retention policy?"
                  />
                </label>

                <label className="grid gap-1">
                  <span className="text-xs font-semibold tracking-wide text-[#635e7b] uppercase">
                    Expected answer
                  </span>
                  <textarea
                    rows={2}
                    value={addQuestionDraft.expectedAnswer}
                    onChange={(event) =>
                      onAddQuestionDraftChange({
                        ...addQuestionDraft,
                        expectedAnswer: event.target.value,
                      })
                    }
                    className="rounded-lg border border-[#d1cce4] px-2 py-1.5 text-sm text-[#2a2640]"
                    placeholder="Optional expected answer"
                  />
                </label>

                <div className="grid gap-2 sm:grid-cols-2">
                  <label className="grid gap-1">
                    <span className="text-xs font-semibold tracking-wide text-[#635e7b] uppercase">
                      Expected page
                    </span>
                    <input
                      value={addQuestionDraft.expectedPage}
                      onChange={(event) =>
                        onAddQuestionDraftChange({
                          ...addQuestionDraft,
                          expectedPage: event.target.value,
                        })
                      }
                      className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640]"
                      placeholder="Optional"
                    />
                  </label>
                  <label className="grid gap-1">
                    <span className="text-xs font-semibold tracking-wide text-[#635e7b] uppercase">
                      Tags
                    </span>
                    <input
                      value={addQuestionDraft.tags}
                      onChange={(event) =>
                        onAddQuestionDraftChange({
                          ...addQuestionDraft,
                          tags: event.target.value,
                        })
                      }
                      className="h-9 rounded-lg border border-[#d1cce4] px-2 text-sm text-[#2a2640]"
                      placeholder="compliance, retention"
                    />
                  </label>
                </div>

                {addQuestionError ? (
                  <p className="text-xs text-rose-700">{addQuestionError}</p>
                ) : null}

                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={isAddingQuestion}
                    className="rounded bg-[#3525cd] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#2c1ea9] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isAddingQuestion ? "Adding..." : "Add test case"}
                  </button>
                </div>
              </form>
            ) : (
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                Your role can inspect test cases but only owner/admin can add
                new ones.
              </p>
            )}

            {isQuestionsLoading ? (
              <LoadingState compact title="Loading test cases..." />
            ) : questionsError ? (
              <ErrorState
                compact
                error={questionsError}
                description={getApiErrorMessage(questionsError)}
                onRetry={onRetryQuestions}
              />
            ) : visibleQuestions.length === 0 ? (
              <EmptyState
                compact
                title="No test cases match current filters."
                description="Add new test cases or adjust the filters."
              />
            ) : (
              <div className="overflow-x-auto rounded-xl border border-[#ddd8ec] bg-white">
                <table className="min-w-full divide-y divide-[#ece8f7] text-sm">
                  <caption className="sr-only">
                    Test cases with expected answers, expected page, and tags.
                  </caption>
                  <thead className="bg-[#faf8ff]">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-[#67627e] uppercase">
                        Question
                      </th>
                      <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-[#67627e] uppercase">
                        Expected answer
                      </th>
                      <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-[#67627e] uppercase">
                        Page
                      </th>
                      <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-[#67627e] uppercase">
                        Tags
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#f1eef9]">
                    {visibleQuestions.map((question) => (
                      <tr key={question.evaluation_question_id}>
                        <td className="px-3 py-2 text-[#2f2a49]">
                          {question.question}
                        </td>
                        <td className="px-3 py-2 text-[#4e4968]">
                          {question.expected_answer ?? "Unavailable"}
                        </td>
                        <td className="px-3 py-2 text-[#4e4968]">
                          {question.expected_page_number ?? "-"}
                        </td>
                        <td className="px-3 py-2 text-[#4e4968]">
                          {(question.tags ?? []).length > 0
                            ? (question.tags ?? []).join(", ")
                            : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

export type { AddQuestionDraft, DatasetQuestionFilters };
