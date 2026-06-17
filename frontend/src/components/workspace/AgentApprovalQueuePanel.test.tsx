import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentApprovalQueuePanel } from "@/components/workspace/AgentApprovalQueuePanel";
import type {
  AgentApprovalQueueItem,
  AgentApprovalQueueResponse,
} from "@/lib/api/agent";

// ── Mock: agent API ───────────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  listAgentApprovals: vi.fn(),
  decideAgentRunApproval: vi.fn(),
}));

vi.mock("@/lib/api/agent", () => ({
  listAgentApprovals: (...args: unknown[]) =>
    mockApi.listAgentApprovals(...args),
  decideAgentRunApproval: (...args: unknown[]) =>
    mockApi.decideAgentRunApproval(...args),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

const NOW = "2026-06-19T10:00:00.000Z";
const FUTURE_EXPIRY = "2026-06-19T10:30:00.000Z";

function makeQueueItem(
  overrides: Partial<AgentApprovalQueueItem> = {},
): AgentApprovalQueueItem {
  return {
    approval_id: "appr-1",
    agent_run_id: "run-1",
    agent_step_id: null,
    tool_call_id: null,
    requested_by_user_id: "user-1",
    status: "pending",
    risk_level: "high",
    tool_name: "file_write",
    request_summary: "Agent wants to write /tmp/output.txt",
    request_payload: { tool_name: "file_write", risk_level: "high" },
    expires_at: FUTURE_EXPIRY,
    run_objective: "Summarise quarterly results",
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  };
}

function makeQueueResponse(
  items: AgentApprovalQueueItem[] = [],
  total?: number,
): AgentApprovalQueueResponse {
  return {
    approvals: items,
    total: total ?? items.length,
    limit: 20,
    offset: 0,
  };
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AgentApprovalQueuePanel />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AgentApprovalQueuePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("loading state", () => {
    it("shows loading indicator while fetching", () => {
      mockApi.listAgentApprovals.mockReturnValue(new Promise(() => {}));
      renderPanel();
      expect(screen.getByText(/loading approvals/i)).toBeInTheDocument();
    });
  });

  describe("empty state", () => {
    it("shows empty message when no pending approvals", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(makeQueueResponse([]));
      renderPanel();
      await waitFor(() =>
        expect(
          screen.getByText(/no pending approvals/i),
        ).toBeInTheDocument(),
      );
    });
  });

  describe("error state", () => {
    it("shows error message and retry button on failure", async () => {
      mockApi.listAgentApprovals.mockRejectedValue(new Error("Network error"));
      renderPanel();
      await waitFor(() =>
        expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument(),
      );
    });
  });

  describe("approval queue display", () => {
    it("renders approval card with risk level, tool name, and summary", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(
        makeQueueResponse([makeQueueItem()]),
      );
      renderPanel();

      await waitFor(() =>
        expect(screen.getByText("Agent wants to write /tmp/output.txt")).toBeInTheDocument(),
      );
      expect(screen.getByText("file_write")).toBeInTheDocument();
      expect(screen.getByText("high")).toBeInTheDocument();
      expect(screen.getByText("Summarise quarterly results")).toBeInTheDocument();
    });

    it("shows approval count badge when items present", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(
        makeQueueResponse([makeQueueItem(), makeQueueItem({ approval_id: "appr-2" })], 2),
      );
      renderPanel();
      await waitFor(() => expect(screen.getByText("2")).toBeInTheDocument());
    });

    it("renders approve, request changes, and reject buttons", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(
        makeQueueResponse([makeQueueItem()]),
      );
      renderPanel();

      await waitFor(() =>
        expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument(),
      );
      expect(
        screen.getByRole("button", { name: /request changes/i }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
    });
  });

  describe("approve action", () => {
    it("calls decideAgentRunApproval with approved status", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(
        makeQueueResponse([makeQueueItem()]),
      );
      mockApi.decideAgentRunApproval.mockResolvedValue({
        ...makeQueueItem(),
        status: "approved",
      });
      renderPanel();

      const approveBtn = await screen.findByRole("button", { name: /approve/i });
      await userEvent.click(approveBtn);

      expect(mockApi.decideAgentRunApproval).toHaveBeenCalledWith(
        "run-1",
        "appr-1",
        expect.objectContaining({ status: "approved" }),
      );
    });

    it("re-fetches queue after successful approve", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(
        makeQueueResponse([makeQueueItem()]),
      );
      mockApi.decideAgentRunApproval.mockResolvedValue({
        ...makeQueueItem(),
        status: "approved",
      });
      renderPanel();

      const approveBtn = await screen.findByRole("button", { name: /approve/i });
      await userEvent.click(approveBtn);

      await waitFor(() =>
        expect(mockApi.listAgentApprovals).toHaveBeenCalledTimes(2),
      );
    });
  });

  describe("reject action", () => {
    it("calls decideAgentRunApproval with rejected status", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(
        makeQueueResponse([makeQueueItem()]),
      );
      mockApi.decideAgentRunApproval.mockResolvedValue({
        ...makeQueueItem(),
        status: "rejected",
      });
      renderPanel();

      const rejectBtn = await screen.findByRole("button", { name: /reject/i });
      await userEvent.click(rejectBtn);

      expect(mockApi.decideAgentRunApproval).toHaveBeenCalledWith(
        "run-1",
        "appr-1",
        expect.objectContaining({ status: "rejected" }),
      );
    });
  });

  describe("changes_requested action", () => {
    it("calls decideAgentRunApproval with changes_requested status", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(
        makeQueueResponse([makeQueueItem()]),
      );
      mockApi.decideAgentRunApproval.mockResolvedValue({
        ...makeQueueItem(),
        status: "changes_requested",
      });
      renderPanel();

      const changesBtn = await screen.findByRole("button", {
        name: /request changes/i,
      });
      await userEvent.click(changesBtn);

      expect(mockApi.decideAgentRunApproval).toHaveBeenCalledWith(
        "run-1",
        "appr-1",
        expect.objectContaining({ status: "changes_requested" }),
      );
    });
  });

  describe("error handling", () => {
    it("shows inline error when decision fails", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(
        makeQueueResponse([makeQueueItem()]),
      );
      mockApi.decideAgentRunApproval.mockRejectedValue(
        new Error("Approval already decided"),
      );
      renderPanel();

      const approveBtn = await screen.findByRole("button", { name: /approve/i });
      await userEvent.click(approveBtn);

      await waitFor(() =>
        expect(
          screen.getByRole("alert"),
        ).toBeInTheDocument(),
      );
    });
  });

  describe("no risk level", () => {
    it("renders without a risk badge when risk_level is null", async () => {
      mockApi.listAgentApprovals.mockResolvedValue(
        makeQueueResponse([makeQueueItem({ risk_level: null })]),
      );
      renderPanel();

      await waitFor(() =>
        expect(screen.getByText("Agent wants to write /tmp/output.txt")).toBeInTheDocument(),
      );
      expect(screen.queryByText("high")).not.toBeInTheDocument();
    });
  });
});
