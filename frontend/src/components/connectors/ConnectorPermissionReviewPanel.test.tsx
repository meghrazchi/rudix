import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectorPermissionReviewPanel } from "@/components/connectors/ConnectorPermissionReviewPanel";
import type { PermissionReview } from "@/lib/api/connectors";

// ── Mock: connectors API ──────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  getPermissionReview: vi.fn(),
  confirmPermissionReview: vi.fn(),
}));

vi.mock("@/lib/api/connectors", () => ({
  getPermissionReview: (...args: unknown[]) =>
    mockApi.getPermissionReview(...args),
  confirmPermissionReview: (...args: unknown[]) =>
    mockApi.confirmPermissionReview(...args),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

const CONNECTION_ID = "conn-perm-001";

function makeReview(
  overrides: Partial<PermissionReview> = {},
): PermissionReview {
  return {
    id: "review-1",
    connection_id: CONNECTION_ID,
    is_confirmed: false,
    is_broad_scope: false,
    scope_warnings: [],
    permission_snapshot: {
      provider_key: "google_drive",
      scopes_granted: [],
      sync_direction: "read_only",
      retention_policy: "indexed_until_connector_removed",
      collection_id: null,
      analyzed_at: new Date().toISOString(),
    },
    reviewed_by_user_id: null,
    reviewed_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ConnectorPermissionReviewPanel connectionId={CONNECTION_ID} />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ConnectorPermissionReviewPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    mockApi.getPermissionReview.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByText(/loading permission review/i)).toBeInTheDocument();
  });

  it("shows pending badge when review is not confirmed", async () => {
    mockApi.getPermissionReview.mockResolvedValue(makeReview());
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/pending review/i)).toBeInTheDocument(),
    );
  });

  it("shows confirmed badge when review is confirmed", async () => {
    mockApi.getPermissionReview.mockResolvedValue(
      makeReview({
        is_confirmed: true,
        reviewed_at: new Date().toISOString(),
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/^confirmed$/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/pending review/i)).not.toBeInTheDocument();
  });

  it("shows confirm button when not confirmed", async () => {
    mockApi.getPermissionReview.mockResolvedValue(makeReview());
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByTestId("confirm-permission-review"),
      ).toBeInTheDocument(),
    );
  });

  it("does not show confirm button when already confirmed", async () => {
    mockApi.getPermissionReview.mockResolvedValue(
      makeReview({ is_confirmed: true }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.queryByTestId("confirm-permission-review"),
      ).not.toBeInTheDocument(),
    );
  });

  it("calls confirmPermissionReview on button click and updates state", async () => {
    const user = userEvent.setup();
    const confirmedReview = makeReview({
      is_confirmed: true,
      reviewed_at: new Date().toISOString(),
    });
    mockApi.getPermissionReview.mockResolvedValue(makeReview());
    mockApi.confirmPermissionReview.mockResolvedValue(confirmedReview);

    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByTestId("confirm-permission-review"),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("confirm-permission-review"));
    expect(mockApi.confirmPermissionReview).toHaveBeenCalledWith(CONNECTION_ID);

    await waitFor(() =>
      expect(screen.getByText(/permissions confirmed/i)).toBeInTheDocument(),
    );
  });

  it("shows broad scope warning banner when is_broad_scope is true and not confirmed", async () => {
    mockApi.getPermissionReview.mockResolvedValue(
      makeReview({
        is_broad_scope: true,
        scope_warnings: [
          {
            code: "org_wide_access",
            message: "Grants access to entire organisation",
            scope: "https://www.googleapis.com/auth/drive.readonly",
          },
        ],
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(/broad permission scope detected/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows individual scope warnings", async () => {
    mockApi.getPermissionReview.mockResolvedValue(
      makeReview({
        scope_warnings: [
          {
            code: "write_permission",
            message: "Grants write or delete access",
            scope: "write:files",
          },
        ],
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(/grants write or delete access/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows granted scopes from snapshot", async () => {
    mockApi.getPermissionReview.mockResolvedValue(
      makeReview({
        permission_snapshot: {
          provider_key: "google_drive",
          scopes_granted: ["https://www.googleapis.com/auth/drive.readonly"],
          sync_direction: "read_only",
          retention_policy: "indexed_until_connector_removed",
          collection_id: null,
          source_filters: {
            folder_ids: ["folder-1", "folder-2"],
          },
          analyzed_at: new Date().toISOString(),
        },
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText("https://www.googleapis.com/auth/drive.readonly"),
      ).toBeInTheDocument(),
    );
  });

  it("shows selected source filters from snapshot", async () => {
    mockApi.getPermissionReview.mockResolvedValue(
      makeReview({
        permission_snapshot: {
          provider_key: "google_drive",
          scopes_granted: [],
          sync_direction: "read_only",
          retention_policy: "indexed_until_connector_removed",
          collection_id: null,
          source_filters: {
            folder_ids: ["folder-1", "folder-2"],
          },
          analyzed_at: new Date().toISOString(),
        },
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/selected source filters/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/folder ids:/i)).toBeInTheDocument();
    expect(screen.getByText(/folder-1, folder-2/i)).toBeInTheDocument();
  });

  it("shows policy summary cards", async () => {
    mockApi.getPermissionReview.mockResolvedValue(makeReview());
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/sync direction/i)).toBeInTheDocument();
      expect(screen.getByText(/retention/i)).toBeInTheDocument();
      expect(screen.getByText(/access/i)).toBeInTheDocument();
    });
  });

  it("shows error state when API fails", async () => {
    mockApi.getPermissionReview.mockRejectedValue(new Error("Network error"));
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(/unable to load permission review/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows error message when confirm fails", async () => {
    const user = userEvent.setup();
    mockApi.getPermissionReview.mockResolvedValue(makeReview());
    mockApi.confirmPermissionReview.mockRejectedValue(
      new Error("Confirm failed"),
    );

    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByTestId("confirm-permission-review"),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("confirm-permission-review"));
    await waitFor(() =>
      expect(screen.getByText(/confirm failed/i)).toBeInTheDocument(),
    );
  });
});
