import { expect, test, type Page, type Route } from "@playwright/test";

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
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "*",
      "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    },
    body: JSON.stringify(body),
  });
}

async function seedSession(page: Page): Promise<void> {
  await page.addInitScript(
    ({ key, value }: { key: string; value: string }) => {
      window.sessionStorage.setItem(key, value);
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

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Agent approval queue — E2E", () => {
  test("approval queue panel shows pending approval for a waiting_approval run", async ({
    page,
  }) => {
    await seedSession(page);
    await page.route("**/api/v1/**", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname.replace(/^\/api\/v1/, "");

      if (req.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }

      if (path === "/agent/runs" && req.method() === "GET") {
        await fulfillJson(route, {
          runs: [runWaitingApproval],
          total: 1,
          limit: 20,
          offset: 0,
        });
        return;
      }

      if (path === `/agent/runs/${RUN_ID}` && req.method() === "GET") {
        await fulfillJson(route, runDetailWaitingApproval);
        return;
      }

      if (path === "/agent/approvals" && req.method() === "GET") {
        await fulfillJson(route, {
          approvals: [pendingApprovalQueueItem],
          total: 1,
          limit: 20,
          offset: 0,
        });
        return;
      }

      await route.continue();
    });

    await page.goto("/workspace/agent");
    await expect(
      page.getByText("About to write results to /reports/q2.pdf"),
    ).toBeVisible();
    await expect(page.getByText("high")).toBeVisible();
    await expect(page.getByText("file_write")).toBeVisible();
    await expect(page.getByText("Summarise Q2 revenue report")).toBeVisible();
  });

  test("approving a run transitions it to running", async ({ page }) => {
    await seedSession(page);
    let approvalQueueCallCount = 0;

    await page.route("**/api/v1/**", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname.replace(/^\/api\/v1/, "");

      if (req.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }

      if (path === "/agent/runs" && req.method() === "GET") {
        await fulfillJson(route, {
          runs: [runWaitingApproval],
          total: 1,
          limit: 20,
          offset: 0,
        });
        return;
      }

      if (path === `/agent/runs/${RUN_ID}` && req.method() === "GET") {
        await fulfillJson(route, runDetailWaitingApproval);
        return;
      }

      if (path === "/agent/approvals" && req.method() === "GET") {
        approvalQueueCallCount++;
        const items =
          approvalQueueCallCount === 1 ? [pendingApprovalQueueItem] : [];
        await fulfillJson(route, {
          approvals: items,
          total: items.length,
          limit: 20,
          offset: 0,
        });
        return;
      }

      if (
        path === `/agent/runs/${RUN_ID}/approvals/${APPROVAL_ID}/decision` &&
        req.method() === "POST"
      ) {
        await fulfillJson(route, makeApprovalResponse({ status: "approved" }));
        return;
      }

      await route.continue();
    });

    await page.goto("/workspace/agent");
    const approveBtn = page.getByRole("button", { name: /approve/i }).first();
    await expect(approveBtn).toBeVisible();
    await approveBtn.click();

    await expect(
      page.getByRole("button", { name: /approve/i }).first(),
    ).toBeHidden({ timeout: 5000 });
  });

  test("rejecting an approval transitions run to failed and shows reason", async ({
    page,
  }) => {
    await seedSession(page);

    await page.route("**/api/v1/**", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname.replace(/^\/api\/v1/, "");

      if (req.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }

      if (path === "/agent/runs" && req.method() === "GET") {
        await fulfillJson(route, {
          runs: [runWaitingApproval],
          total: 1,
          limit: 20,
          offset: 0,
        });
        return;
      }

      if (path === `/agent/runs/${RUN_ID}` && req.method() === "GET") {
        await fulfillJson(route, runDetailWaitingApproval);
        return;
      }

      if (path === "/agent/approvals" && req.method() === "GET") {
        await fulfillJson(route, {
          approvals: [pendingApprovalQueueItem],
          total: 1,
          limit: 20,
          offset: 0,
        });
        return;
      }

      if (
        path === `/agent/runs/${RUN_ID}/approvals/${APPROVAL_ID}/decision` &&
        req.method() === "POST"
      ) {
        await fulfillJson(
          route,
          makeApprovalResponse({
            status: "rejected",
            decision_reason: "Path looks unsafe",
          }),
        );
        return;
      }

      await route.continue();
    });

    await page.goto("/workspace/agent");
    const rejectBtn = page.getByRole("button", { name: /reject/i }).first();
    await expect(rejectBtn).toBeVisible();
    await rejectBtn.click();

    await expect(rejectBtn).toBeHidden({ timeout: 5000 });
  });

  test("expired approval shows expired badge and decision returns 409", async ({
    page,
  }) => {
    await seedSession(page);
    const expiredItem = {
      ...pendingApprovalQueueItem,
      status: "pending",
      expires_at: "2026-06-19T07:00:00Z",
    };

    await page.route("**/api/v1/**", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname.replace(/^\/api\/v1/, "");

      if (req.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }

      if (path === "/agent/runs" && req.method() === "GET") {
        await fulfillJson(route, {
          runs: [runWaitingApproval],
          total: 1,
          limit: 20,
          offset: 0,
        });
        return;
      }

      if (path === `/agent/runs/${RUN_ID}` && req.method() === "GET") {
        await fulfillJson(route, runDetailWaitingApproval);
        return;
      }

      if (path === "/agent/approvals" && req.method() === "GET") {
        await fulfillJson(route, {
          approvals: [expiredItem],
          total: 1,
          limit: 20,
          offset: 0,
        });
        return;
      }

      if (
        path === `/agent/runs/${RUN_ID}/approvals/${APPROVAL_ID}/decision` &&
        req.method() === "POST"
      ) {
        await fulfillJson(
          route,
          {
            detail: { code: "approval_expired", message: "Approval expired." },
          },
          409,
        );
        return;
      }

      await route.continue();
    });

    await page.goto("/workspace/agent");
    await expect(page.getByText(/expired/i).first()).toBeVisible();

    const approveBtn = page.getByRole("button", { name: /approve/i }).first();
    await expect(approveBtn).toBeVisible();
    await approveBtn.click();

    await expect(page.getByRole("alert").first()).toBeVisible({
      timeout: 5000,
    });
  });

  test("approval queue is empty for admin with no pending approvals", async ({
    page,
  }) => {
    await seedSession(page);

    await page.route("**/api/v1/**", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname.replace(/^\/api\/v1/, "");

      if (req.method() === "OPTIONS") {
        await route.fulfill({
          status: 200,
          headers: {
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          },
        });
        return;
      }

      if (path === "/agent/runs" && req.method() === "GET") {
        await fulfillJson(route, { runs: [], total: 0, limit: 20, offset: 0 });
        return;
      }

      if (path === "/agent/approvals" && req.method() === "GET") {
        await fulfillJson(route, {
          approvals: [],
          total: 0,
          limit: 20,
          offset: 0,
        });
        return;
      }

      await route.continue();
    });

    await page.goto("/workspace/agent");
    await expect(page.getByText(/no pending approvals/i)).toBeVisible();
  });
});
