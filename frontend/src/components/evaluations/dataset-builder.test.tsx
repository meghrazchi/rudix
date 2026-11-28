import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DATASET_CASES_PAGE_SIZE,
  DatasetBuilderPanel,
} from "@/components/evaluations/dataset-builder";
import type {
  EvaluationQuestionResponse,
  EvaluationSetResponse,
} from "@/lib/api/evaluations";
import { renderWithProviders } from "@/test/render";

const listEvaluationQuestions = vi.fn();

vi.mock("@/lib/api/evaluations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/evaluations")>();
  return {
    ...actual,
    listEvaluationQuestions: (...args: unknown[]) =>
      listEvaluationQuestions(...args),
    validateEvaluationDataset: vi.fn().mockResolvedValue({
      is_valid: true,
      issue_count: 0,
      issues: [],
    }),
    listDatasetVersions: vi.fn().mockResolvedValue({ items: [] }),
    getLanguageCoverage: vi.fn().mockResolvedValue({
      items: [],
      unlabelled_count: 0,
      total_question_count: 0,
      coverage_warning_languages: [],
    }),
  };
});

const EVALUATION_SET = {
  evaluation_set_id: "set-1",
  name: "Regression suite",
  description: null,
  status: "draft",
  version: 1,
  scope: {},
} as unknown as EvaluationSetResponse;

function makeQuestion(index: number): EvaluationQuestionResponse {
  return {
    evaluation_question_id: `q-${index}`,
    evaluation_set_id: "set-1",
    question: `Question number ${index}`,
    expected_answer: null,
    tags: [],
    difficulty: null,
    created_at: "2026-06-18T10:00:00Z",
  } as unknown as EvaluationQuestionResponse;
}

function page(offset: number, count: number, total: number) {
  return {
    evaluation_set_id: "set-1",
    items: Array.from({ length: count }, (_, i) => makeQuestion(offset + i)),
    total,
    limit: DATASET_CASES_PAGE_SIZE,
    offset,
  };
}

function renderPanel() {
  return renderWithProviders(
    <DatasetBuilderPanel
      evaluationSet={EVALUATION_SET}
      questions={[]}
      canManage={false}
      canAdmin={false}
      onRefreshSet={vi.fn()}
      onRefreshQuestions={vi.fn()}
      onSetDeleted={vi.fn()}
      onSetDuplicated={vi.fn()}
    />,
  );
}

describe("DatasetBuilderPanel case paging (R07-06)", () => {
  beforeEach(() => {
    listEvaluationQuestions.mockReset();
  });

  it("shows the loaded count and loads the next page by offset", async () => {
    listEvaluationQuestions.mockImplementation(
      async (_setId: string, params: { offset?: number }) =>
        (params.offset ?? 0) === 0
          ? page(0, DATASET_CASES_PAGE_SIZE, DATASET_CASES_PAGE_SIZE + 2)
          : page(DATASET_CASES_PAGE_SIZE, 2, DATASET_CASES_PAGE_SIZE + 2),
    );

    renderPanel();

    expect(
      await screen.findByText(
        `Cases (${DATASET_CASES_PAGE_SIZE} of ${DATASET_CASES_PAGE_SIZE + 2})`,
      ),
    ).toBeInTheDocument();
    expect(listEvaluationQuestions).toHaveBeenCalledWith("set-1", {
      limit: DATASET_CASES_PAGE_SIZE,
      offset: 0,
    });

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(
      await screen.findByText(`Cases (${DATASET_CASES_PAGE_SIZE + 2})`),
    ).toBeInTheDocument();
    expect(listEvaluationQuestions).toHaveBeenLastCalledWith("set-1", {
      limit: DATASET_CASES_PAGE_SIZE,
      offset: DATASET_CASES_PAGE_SIZE,
    });
    expect(
      screen.getByText(`Question number ${DATASET_CASES_PAGE_SIZE + 1}`),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Load more" }),
    ).not.toBeInTheDocument();
  });

  it("hides Load more when everything fits in the first page", async () => {
    listEvaluationQuestions.mockResolvedValue(page(0, 3, 3));

    renderPanel();

    expect(await screen.findByText("Cases (3)")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Load more" }),
    ).not.toBeInTheDocument();
  });

  it("shows an error next to Load more when the next page fails", async () => {
    listEvaluationQuestions.mockImplementation(
      async (_setId: string, params: { offset?: number }) => {
        if ((params.offset ?? 0) === 0) {
          return page(0, DATASET_CASES_PAGE_SIZE, DATASET_CASES_PAGE_SIZE + 1);
        }
        throw new Error("boom");
      },
    );

    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));

    await waitFor(() =>
      expect(
        screen.getByText("Could not load more cases."),
      ).toBeInTheDocument(),
    );
  });
});
