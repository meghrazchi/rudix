import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AbTestPanel } from "@/components/evaluations/ab-test-panel";

const apiBaseUrl = "http://api.test";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: { status: "authenticated", session: null },
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const EXPERIMENT_1 = {
  experiment_id: "exp-1",
  name: "Prompt v2 vs v3",
  description: "Compare faithfulness",
  evaluation_set_id: "eval-set-1",
  status: "draft",
  metrics_config: {},
  created_by_id: "user-1",
  created_at: "2026-06-18T10:00:00Z",
  updated_at: "2026-06-18T10:00:00Z",
  variants: [
    {
      variant_id: "var-1",
      experiment_id: "exp-1",
      label: "Control",
      description: null,
      rag_profile_id: null,
      rag_profile_version: null,
      prompt_template_version_id: null,
      model_profile_key: null,
      config_snapshot: {},
      approval_status: "pending",
      approved_by_id: null,
      approval_note: null,
      approved_at: null,
      created_at: "2026-06-18T10:00:00Z",
      updated_at: "2026-06-18T10:00:00Z",
    },
    {
      variant_id: "var-2",
      experiment_id: "exp-1",
      label: "Challenger",
      description: "New prompt template",
      rag_profile_id: "rag-1",
      rag_profile_version: 3,
      prompt_template_version_id: "ptv-1",
      model_profile_key: "cloud_baseline",
      config_snapshot: {},
      approval_status: "pending",
      approved_by_id: null,
      approval_note: null,
      approved_at: null,
      created_at: "2026-06-18T10:01:00Z",
      updated_at: "2026-06-18T10:01:00Z",
    },
  ],
};

const RUN_COMPLETED = {
  experiment_run_id: "run-1",
  experiment_id: "exp-1",
  status: "completed",
  triggered_by_id: "user-1",
  started_at: "2026-06-18T10:05:00Z",
  completed_at: "2026-06-18T10:10:00Z",
  created_at: "2026-06-18T10:05:00Z",
  updated_at: "2026-06-18T10:10:00Z",
  variant_summaries: [
    {
      variant_id: "var-1",
      variant_label: "Control",
      evaluation_run_id: "er-1",
      status: "completed",
      metrics_summary: {
        faithfulness_score: 0.72,
        citation_accuracy_score: 0.81,
        latency_ms_p95: 480,
      },
      deltas_vs_reference: [],
      error_detail: null,
    },
    {
      variant_id: "var-2",
      variant_label: "Challenger",
      evaluation_run_id: "er-2",
      status: "completed",
      metrics_summary: {
        faithfulness_score: 0.89,
        citation_accuracy_score: 0.77,
        latency_ms_p95: 320,
      },
      deltas_vs_reference: [
        {
          metric: "faithfulness_score",
          label: "Faithfulness Score",
          reference_value: 0.72,
          variant_value: 0.89,
          delta: 0.17,
          improved: true,
        },
        {
          metric: "citation_accuracy_score",
          label: "Citation Accuracy",
          reference_value: 0.81,
          variant_value: 0.77,
          delta: -0.04,
          improved: false,
        },
      ],
      error_detail: null,
    },
  ],
  comparison_report: {
    winner_by_metric: {
      "Faithfulness Score": "Challenger",
      "Citation Accuracy": "Control",
    },
  },
};

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const server = setupServer(
  http.get(`${apiBaseUrl}/ab-experiments`, () =>
    HttpResponse.json({
      items: [EXPERIMENT_1],
      total: 1,
      limit: 50,
      offset: 0,
    }),
  ),
  http.get(`${apiBaseUrl}/ab-experiments/exp-1`, () =>
    HttpResponse.json(EXPERIMENT_1),
  ),
  http.get(`${apiBaseUrl}/ab-experiments/exp-1/runs`, () =>
    HttpResponse.json({
      items: [RUN_COMPLETED],
      total: 1,
      limit: 50,
      offset: 0,
    }),
  ),
  http.post(`${apiBaseUrl}/ab-experiments`, () =>
    HttpResponse.json(
      {
        ...EXPERIMENT_1,
        experiment_id: "exp-2",
        name: "New Experiment",
        variants: [],
      },
      { status: 201 },
    ),
  ),
  http.post(`${apiBaseUrl}/ab-experiments/exp-1/runs`, () =>
    HttpResponse.json(
      { ...RUN_COMPLETED, status: "running", experiment_run_id: "run-2" },
      { status: 201 },
    ),
  ),
  http.post(`${apiBaseUrl}/ab-experiments/exp-1/variants/var-1/approve`, () =>
    HttpResponse.json({
      ...EXPERIMENT_1.variants[0],
      approval_status: "approved",
    }),
  ),
  http.post(`${apiBaseUrl}/ab-experiments/exp-1/variants/var-2/reject`, () =>
    HttpResponse.json({
      ...EXPERIMENT_1.variants[1],
      approval_status: "rejected",
    }),
  ),
  http.delete(
    `${apiBaseUrl}/ab-experiments/exp-1`,
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.delete(
    `${apiBaseUrl}/ab-experiments/exp-1/variants/var-2`,
    () => new HttpResponse(null, { status: 204 }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AbTestPanel />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AbTestPanel", () => {
  it("renders the experiment list sidebar", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Prompt v2 vs v3")).toBeInTheDocument();
    });
  });

  it("shows empty state when no experiments", async () => {
    server.use(
      http.get(`${apiBaseUrl}/ab-experiments`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/No experiments yet/i)).toBeInTheDocument();
    });
  });

  it("displays experiment detail on selection", async () => {
    renderPanel();
    await waitFor(() => screen.getByText("Prompt v2 vs v3"));
    fireEvent.click(screen.getByText("Prompt v2 vs v3"));
    await waitFor(() => {
      expect(screen.getByText("Control")).toBeInTheDocument();
      expect(screen.getByText("Challenger")).toBeInTheDocument();
    });
  });

  it("shows variant labels and approval badges", async () => {
    renderPanel();
    await waitFor(() => screen.getByText("Prompt v2 vs v3"));
    fireEvent.click(screen.getByText("Prompt v2 vs v3"));
    await waitFor(() => {
      const pendingBadges = screen.getAllByText("PENDING");
      expect(pendingBadges.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("shows comparison table with metric deltas for completed run", async () => {
    renderPanel();
    await waitFor(() => screen.getByText("Prompt v2 vs v3"));
    fireEvent.click(screen.getByText("Prompt v2 vs v3"));
    await waitFor(() => {
      // Faithfulness improved (+17%) should be visible in comparison
      expect(screen.getByText(/Faithfulness/i)).toBeInTheDocument();
    });
  });

  it("shows winner by metric summary", async () => {
    renderPanel();
    await waitFor(() => screen.getByText("Prompt v2 vs v3"));
    fireEvent.click(screen.getByText("Prompt v2 vs v3"));
    await waitFor(() => {
      expect(screen.getByText(/Winners by metric/i)).toBeInTheDocument();
    });
  });

  it("shows variant metadata (RAG profile, model key)", async () => {
    renderPanel();
    await waitFor(() => screen.getByText("Prompt v2 vs v3"));
    fireEvent.click(screen.getByText("Prompt v2 vs v3"));
    await waitFor(() => {
      expect(screen.getByText(/RAG profile v3/i)).toBeInTheDocument();
      expect(screen.getByText(/cloud_baseline/i)).toBeInTheDocument();
    });
  });

  it("shows the create form on + New click", async () => {
    renderPanel();
    await waitFor(() => screen.getByText(/\+ New/i));
    fireEvent.click(screen.getByText(/\+ New/i));
    expect(screen.getByText(/New A\/B Experiment/i)).toBeInTheDocument();
  });

  it("shows + Add variant toggle in detail view", async () => {
    renderPanel();
    await waitFor(() => screen.getByText("Prompt v2 vs v3"));
    fireEvent.click(screen.getByText("Prompt v2 vs v3"));
    await waitFor(() => screen.getByText(/\+ Add variant/i));
    fireEvent.click(screen.getByText(/\+ Add variant/i));
    expect(screen.getByText(/Add Variant/i)).toBeInTheDocument();
  });

  it("shows Run Experiment button and sends request on click", async () => {
    let ran = false;
    server.use(
      http.post(`${apiBaseUrl}/ab-experiments/exp-1/runs`, () => {
        ran = true;
        return HttpResponse.json(
          { ...RUN_COMPLETED, status: "running", experiment_run_id: "run-99" },
          { status: 201 },
        );
      }),
    );
    renderPanel();
    await waitFor(() => screen.getByText("Prompt v2 vs v3"));
    fireEvent.click(screen.getByText("Prompt v2 vs v3"));
    await waitFor(() => screen.getByText(/Run Experiment/i));
    fireEvent.click(screen.getByText(/Run Experiment/i));
    await waitFor(() => expect(ran).toBe(true));
  });

  it("status badge shows COMPLETED for a finished run", async () => {
    renderPanel();
    await waitFor(() => screen.getByText("Prompt v2 vs v3"));
    fireEvent.click(screen.getByText("Prompt v2 vs v3"));
    await waitFor(() => {
      const completedBadges = screen.getAllByText("COMPLETED");
      expect(completedBadges.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("Approve button triggers approval request", async () => {
    let approved = false;
    server.use(
      http.post(
        `${apiBaseUrl}/ab-experiments/exp-1/variants/var-1/approve`,
        () => {
          approved = true;
          return HttpResponse.json({
            ...EXPERIMENT_1.variants[0],
            approval_status: "approved",
          });
        },
      ),
    );
    renderPanel();
    await waitFor(() => screen.getByText("Prompt v2 vs v3"));
    fireEvent.click(screen.getByText("Prompt v2 vs v3"));
    await waitFor(() => screen.getAllByText("Approve"));
    fireEvent.click(screen.getAllByText("Approve")[0]);
    await waitFor(() => expect(approved).toBe(true));
  });
});
