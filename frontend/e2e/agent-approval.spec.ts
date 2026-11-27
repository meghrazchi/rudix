import { expect, test, type Page, type Route } from "@playwright/test";

import { mockCorsHeaders } from "./support/mock-cors";

const SESSION_STORAGE_KEY = "rudix.session.v1";
const ORG_ID = "c8ae2f17-c58e-499e-88bf-e6b0a8648c21";
const RUN_ID = "run-e2e-approval-001";
const APPROVAL_ID = "appr-e2e-001";
const USER_ID = "e2e-user-approval";

const session = {
  userId: USER_ID,
  email: "admin@example.com",
  role: "admin" as const,
  organizationId: ORG_ID,
  organizationName: "Rudix E2E Org",
  accessToken: "e2e-access-token",
  refreshToken: "e2e-refresh-token",
};

// ── Fixtures ──────────────────────────────────────────────────────────────────

const runWaitingApproval = {
  run_id: RUN_ID,
  status: "waiting_approval",
  objective: "Summarise Q2 revenue report",
  total_cost_usd: null,
  trace_request_id: null,
  error_message: null,
  started_at: "2026-06-19T08:00:00Z",
  completed_at: null,
  cancelled_at: null,
  created_at: "2026-06-19T08:00:00Z",
  updated_at: "2026-06-19T08:01:00Z",
};

const runDetailWaitingApproval = {
  ...runWaitingApproval,
  organization_id: ORG_ID,
  user_id: USER_ID,
  surface: "api",
  max_steps: null,
  max_parallel_tool_calls: null,
  budget: {},
  costs: {},
  outcome: {},
  observations: {},
  error_details: {},
  steps: [],
  tool_calls: [],
  approvals: [
    {
      approval_id: APPROVAL_ID,
      agent_run_id: RUN_ID,
      agent_step_id: null,
      tool_call_id: null,
      requested_by_user_id: USER_ID,
      decided_by_user_id: null,
      status: "pending",
      request_summary: "About to write results to /reports/q2.pdf",
      decision_reason: null,
      request_payload: { tool_name: "file_write", risk_level: "high" },
      decision_payload: {},
      expires_at: "2026-06-19T09:00:00Z",
      decided_at: null,
      created_at: "2026-06-19T08:01:00Z",
      updated_at: "2026-06-19T08:01:00Z",
    },
  ],
};

const pendingApprovalQueueItem = {
  approval_id: APPROVAL_ID,
  agent_run_id: RUN_ID,
  agent_step_id: null,
  tool_call_id: null,
  requested_by_user_id: USER_ID,
  status: "pending",
  risk_level: "high",
  tool_name: "file_write",
  request_summary: "About to write results to /reports/q2.pdf",
  request_payload: { tool_name: "file_write", risk_level: "high" },
  expires_at: "2026-06-19T09:00:00Z",
  run_objective: "Summarise Q2 revenue report",
  created_at: "2026-06-19T08:01:00Z",
  updated_at: "2026-06-19T08:01:00Z",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

async function fulfillJson(
  route: Route,
  body: unknown,
  status = 200,
): Promise<void> {
  await route.fulfill({
    status,
    headers: {
      "content-type": "application/json",
      ...mockCorsHeaders(route.request()),
    },
    body: JSON.stringify(body),
  });
}

async function seedSession(page: Page): Promise<void> {
  await page.addInitScript(
    ({ key, value }: { key: string; value: string }) => {
      // The app persists the session in localStorage (auth-session.ts).
      window.localStorage.setItem(key, value);
    },
    { key: SESSION_STORAGE_KEY, value: JSON.stringify(session) },
  );
}

function makeApprovalResponse(overrides: Record<string, unknown> = {}) {
  return {
    approval_id: APPROVAL_ID,
    agent_run_id: RUN_ID,
    agent_step_id: null,
    tool_call_id: null,
    requested_by_user_id: USER_ID,
    decided_by_user_id: USER_ID,
    status: "approved",
    request_summary: "About to write results to /reports/q2.pdf",
    decision_reason: null,
    request_payload: { tool_name: "file_write", risk_level: "high" },
    decision_payload: {},
    expires_at: "2026-06-19T09:00:00Z",
    decided_at: "2026-06-19T08:05:00Z",
    created_at: "2026-06-19T08:01:00Z",
    updated_at: "2026-06-19T08:05:00Z",
    ...overrides,
  };
}

// ── Stateful API mock ─────────────────────────────────────────────────────────

type Decision = "approved" | "rejected";

type AgentMockOptions = {
  queueItem?: typeof pendingApprovalQueueItem | null;
  decisionError?: { status: number; body: unknown };
};

type AgentMockState = {
  decisions: Array<{ status?: string; reason?: string | null }>;
};

/**
 * Mocks the agent API like the backend behaves: once a decision is recorded
 * the approval leaves the queue, and the run detail reflects the decision and
 * the resulting run status (approved -> running, rejected -> failed).
 */
async function installAgentApiMocks(
  page: Page,
  options: AgentMockOptions = {},
): Promise<AgentMockState> {
  const state: AgentMockState = { decisions: [] };
  const queueItem =
    options.queueItem === undefined
      ? pendingApprovalQueueItem
      : options.queueItem;
  let decided: { status: Decision; reason: string | null } | null = null;

  const runStatus = () =>
    decided === null
      ? "waiting_approval"
      : decided.status === "approved"
        ? "running"
        : "failed";

  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");

    if (req.method() === "OPTIONS") {
      await route.fulfill({ status: 200, headers: mockCorsHeaders(req) });
      return;
    }

    if (path === "/agent/runs" && req.method() === "GET") {
      const runs = queueItem
        ? [{ ...runWaitingApproval, status: runStatus() }]
        : [];
      await fulfillJson(route, {
        runs,
        total: runs.length,
        limit: 20,
        offset: 0,
      });
      return;
    }

    if (path === `/agent/runs/${RUN_ID}` && req.method() === "GET") {
      const [approval] = runDetailWaitingApproval.approvals;
      await fulfillJson(route, {
        ...runDetailWaitingApproval,
        status: runStatus(),
        approvals: [
          decided === null
            ? approval
            : {
                ...approval,
                status: decided.status,
                decision_reason: decided.reason,
                decided_by_user_id: USER_ID,
                decided_at: "2026-06-19T08:05:00Z",
              },
        ],
      });
      return;
    }

    if (path === "/agent/approvals" && req.method() === "GET") {
      const approvals = queueItem && decided === null ? [queueItem] : [];
      await fulfillJson(route, {
        approvals,
        total: approvals.length,
        limit: 20,
        offset: 0,
      });
      return;
    }

    if (
      path === `/agent/runs/${RUN_ID}/approvals/${APPROVAL_ID}/decision` &&
      req.method() === "POST"
    ) {
      const body = JSON.parse(req.postData() ?? "{}") as {
        status?: string;
        reason?: string | null;
      };
      state.decisions.push(body);
      if (options.decisionError) {
        await fulfillJson(
          route,
          options.decisionError.body,
          options.decisionError.status,
        );
        return;
      }
      decided = {
        status: body.status === "rejected" ? "rejected" : "approved",
        reason: body.reason ?? null,
      };
      await fulfillJson(
        route,
        makeApprovalResponse({
          status: decided.status,
          decision_reason: decided.reason,
        }),
      );
      return;
    }

    await fulfillJson(
      route,
      { detail: `No agent-approval mock for ${req.method()} ${path}` },
      404,
    );
  });

  return state;
}

function approvalQueue(page: Page) {
  return page.getByRole("region", { name: "Approval queue" });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Agent approval queue — E2E", () => {
  test("approval queue panel shows pending approval for a waiting_approval run", async ({
    page,
  }) => {
    await seedSession(page);
    await installAgentApiMocks(page);

    await page.goto("/workspace/agent");
    const queue = approvalQueue(page);
    await expect(
      queue.getByText("About to write results to /reports/q2.pdf"),
    ).toBeVisible();
    await expect(queue.getByText("High", { exact: true })).toBeVisible();
    await expect(queue.getByText("file_write", { exact: true })).toBeVisible();
    await expect(queue.getByText("Summarise Q2 revenue report")).toBeVisible();
    // The run's status badge uses a translated label, not a raw key.
    await expect(
      page.getByText("Waiting for approval", { exact: true }).first(),
    ).toBeVisible();
  });

  test("approving a run transitions it to running", async ({ page }) => {
    await seedSession(page);
    const state = await installAgentApiMocks(page);

    await page.goto("/workspace/agent");
    const queue = approvalQueue(page);
    const approveBtn = queue.getByRole("button", { name: "Approve" });
    await expect(approveBtn).toBeVisible();
    await approveBtn.click();

    await expect(queue.getByText("No pending approvals")).toBeVisible();
    await expect(queue.getByRole("button", { name: "Approve" })).toHaveCount(0);
    expect(state.decisions).toEqual([
      expect.objectContaining({ status: "approved" }),
    ]);
    // The refreshed run detail shows the run moved on to running.
    await expect(
      page.getByText("Running", { exact: true }).first(),
    ).toBeVisible();
  });

  test("rejecting an approval transitions run to failed and shows reason", async ({
    page,
  }) => {
    await seedSession(page);
    const state = await installAgentApiMocks(page);

    await page.goto("/workspace/agent");
    const queue = approvalQueue(page);
    await queue.getByRole("button", { name: "Add reason" }).click();
    await queue.getByRole("textbox").first().fill("Path looks unsafe");
    const rejectBtn = queue.getByRole("button", { name: "Reject" });
    await rejectBtn.click();

    await expect(queue.getByText("No pending approvals")).toBeVisible();
    expect(state.decisions).toEqual([
      { status: "rejected", reason: "Path looks unsafe" },
    ]);
    // The refreshed run detail shows the failed run and the decision reason.
    await expect(
      page.getByText("Failed", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByText("Reason: Path looks unsafe")).toBeVisible();
  });

  test("expired approval shows expired badge and decision returns 409", async ({
    page,
  }) => {
    await seedSession(page);
    const state = await installAgentApiMocks(page, {
      queueItem: {
        ...pendingApprovalQueueItem,
        status: "pending",
        expires_at: "2026-06-19T07:00:00Z",
      },
      decisionError: {
        status: 409,
        body: {
          detail: { code: "approval_expired", message: "Approval expired." },
        },
      },
    });

    await page.goto("/workspace/agent");
    const queue = approvalQueue(page);
    await expect(queue.getByText("Expired", { exact: true })).toBeVisible();

    const approveBtn = queue.getByRole("button", { name: "Approve" });
    await expect(approveBtn).toBeVisible();
    await approveBtn.click();

    await expect(queue.getByRole("alert")).toContainText(
      "conflicts with current state",
    );
    expect(state.decisions).toHaveLength(1);
    // The approval stays in the queue: nothing was decided.
    await expect(
      queue.getByText("About to write results to /reports/q2.pdf"),
    ).toBeVisible();
  });

  test("approval queue is empty for admin with no pending approvals", async ({
    page,
  }) => {
    await seedSession(page);
    await installAgentApiMocks(page, { queueItem: null });

    await page.goto("/workspace/agent");
    await expect(
      approvalQueue(page).getByText("No pending approvals"),
    ).toBeVisible();
  });
});
