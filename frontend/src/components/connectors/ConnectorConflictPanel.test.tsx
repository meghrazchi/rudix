import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectorConflictPanel } from "@/components/connectors/ConnectorConflictPanel";
import type { SyncConflict, SyncConflictsListResponse } from "@/lib/api/connector-sync";

// ── Mock: connector-sync API ──────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  listSyncConflicts: vi.fn(),
  resolveSyncConflict: vi.fn(),
}));

vi.mock("@/lib/api/connector-sync", () => ({
  listSyncConflicts: (...args: unknown[]) => mockApi.listSyncConflicts(...args),
  resolveSyncConflict: (...args: unknown[]) =>
    mockApi.resolveSyncConflict(...args),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

const CONNECTION_ID = "conn-test-123";

function makeConflict(overrides: Partial<SyncConflict> = {}): SyncConflict {
  return {
    id: "conflict-1",
    organization_id: "org-1",
    connection_id: CONNECTION_ID,
    external_item_id: "item-1",
    sync_run_id: "run-1",
    provider_item_id: "provider/item/path/abc",
    conflict_type: "acl_changed",
    status: "open",
    conflict_detail: { previous_acl_hash: "aaa", new_acl_hash: "bbb" },
    resolved_by_user_id: null,
    resolved_at: null,
    resolution_strategy: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function emptyResponse(): SyncConflictsListResponse {
  return { items: [], total: 0 };
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ConnectorConflictPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("shows loading state initially", () => {
    mockApi.listSyncConflicts.mockReturnValue(new Promise(() => {}));
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    expect(screen.getByText(/loading conflicts/i)).toBeInTheDocument();
  });

  it("shows empty state when no open conflicts", async () => {
    mockApi.listSyncConflicts.mockResolvedValue(emptyResponse());
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(screen.getByText(/no open conflicts/i)).toBeInTheDocument(),
    );
  });

  it("renders a list of open conflicts", async () => {
    const conflict = makeConflict();
    mockApi.listSyncConflicts.mockResolvedValue({ items: [conflict], total: 1 });
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(screen.getByText(conflict.provider_item_id)).toBeInTheDocument(),
    );
    expect(screen.getByText(/acl changed/i)).toBeInTheDocument();
  });

  it("shows open count badge when conflicts exist", async () => {
    mockApi.listSyncConflicts.mockResolvedValue({
      items: [makeConflict(), makeConflict({ id: "conflict-2" })],
      total: 2,
    });
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() => expect(screen.getByText("2 open")).toBeInTheDocument());
  });

  it("shows permission_revoked type with correct label", async () => {
    const conflict = makeConflict({ conflict_type: "permission_revoked" });
    mockApi.listSyncConflicts.mockResolvedValue({ items: [conflict], total: 1 });
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(screen.getByText(/permission revoked/i)).toBeInTheDocument(),
    );
  });

  it("expands conflict detail when expand button is clicked", async () => {
    const user = userEvent.setup();
    const conflict = makeConflict({
      conflict_detail: { previous_acl_hash: "old-acl", new_acl_hash: "new-acl" },
    });
    mockApi.listSyncConflicts.mockResolvedValue({ items: [conflict], total: 1 });
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);

    await waitFor(() =>
      expect(screen.getByLabelText(/expand detail/i)).toBeInTheDocument(),
    );
    await user.click(screen.getByLabelText(/expand detail/i));

    expect(screen.getByText(/previous acl hash/i)).toBeInTheDocument();
    expect(screen.getByText("old-acl")).toBeInTheDocument();
  });

  it("calls resolveSyncConflict with 'resolved' when Resolve is clicked", async () => {
    const user = userEvent.setup();
    const conflict = makeConflict();
    mockApi.listSyncConflicts.mockResolvedValue({ items: [conflict], total: 1 });
    mockApi.resolveSyncConflict.mockResolvedValue({
      ...conflict,
      status: "resolved",
    });

    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(screen.getAllByText("Resolve").length).toBeGreaterThan(0),
    );

    await user.click(screen.getAllByText("Resolve")[0]);
    await waitFor(() => {
      expect(mockApi.resolveSyncConflict).toHaveBeenCalledWith(
        CONNECTION_ID,
        conflict.id,
        expect.objectContaining({ resolution: "resolved" }),
      );
    });
  });

  it("calls resolveSyncConflict with 'dismissed' when Dismiss is clicked", async () => {
    const user = userEvent.setup();
    const conflict = makeConflict();
    mockApi.listSyncConflicts.mockResolvedValue({ items: [conflict], total: 1 });
    mockApi.resolveSyncConflict.mockResolvedValue({
      ...conflict,
      status: "dismissed",
    });

    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(screen.getAllByText("Dismiss").length).toBeGreaterThan(0),
    );

    await user.click(screen.getAllByText("Dismiss")[0]);
    await waitFor(() => {
      expect(mockApi.resolveSyncConflict).toHaveBeenCalledWith(
        CONNECTION_ID,
        conflict.id,
        expect.objectContaining({ resolution: "dismissed" }),
      );
    });
  });

  it("does not show Resolve/Dismiss for already-resolved conflicts", async () => {
    const conflict = makeConflict({ status: "resolved" });
    mockApi.listSyncConflicts.mockResolvedValue({ items: [conflict], total: 1 });
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(screen.getByText(conflict.provider_item_id)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Resolve")).not.toBeInTheDocument();
    expect(screen.queryByText("Dismiss")).not.toBeInTheDocument();
  });

  it("filters by Resolved tab", async () => {
    const user = userEvent.setup();
    mockApi.listSyncConflicts
      .mockResolvedValueOnce(emptyResponse()) // initial open query
      .mockResolvedValue({
        items: [makeConflict({ status: "resolved" })],
        total: 1,
      });

    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(screen.getByText(/no open conflicts/i)).toBeInTheDocument(),
    );

    await user.click(screen.getByText("Resolved"));
    await waitFor(() =>
      expect(mockApi.listSyncConflicts).toHaveBeenCalledWith(
        CONNECTION_ID,
        "resolved",
        50,
      ),
    );
  });

  it("shows error state when API fails", async () => {
    mockApi.listSyncConflicts.mockRejectedValue(new Error("Network error"));
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(
        screen.getByText(/failed to load conflicts/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows truncation hint when total > returned items", async () => {
    const items = Array.from({ length: 5 }, (_, i) =>
      makeConflict({ id: `conflict-${i}`, provider_item_id: `item-${i}` }),
    );
    mockApi.listSyncConflicts.mockResolvedValue({ items, total: 50 });
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(screen.getByText(/showing 5 of 50/i)).toBeInTheDocument(),
    );
  });

  it("passes status query param when filter tab is active", async () => {
    mockApi.listSyncConflicts.mockResolvedValue(emptyResponse());
    wrap(<ConnectorConflictPanel connectionId={CONNECTION_ID} />);
    await waitFor(() =>
      expect(mockApi.listSyncConflicts).toHaveBeenCalledWith(
        CONNECTION_ID,
        "open",
        50,
      ),
    );
  });
});
