import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminSourceHealthPage } from "@/components/admin/AdminSourceHealthPage";
import type { SessionState } from "@/lib/auth-session";
import type {
  SourceHealthCharts,
  SourceHealthList,
  SourceHealthRow,
  SourceHealthSummary,
} from "@/lib/schemas/source-health";

const mockAuth = vi.hoisted(() => ({
  state: {
    status: "authenticated",
    session: null,
  } as SessionState,
}));

const mockPermissions = vi.hoisted(() => ({
  role: "admin" as string | null,
  permissions: new Set<string>(["documents:manage", "collections:manage"]),
  hasPermission: (p: string) => mockPermissions.permissions.has(p),
  hasAnyPermission: (...perms: string[]) =>
    perms.some((p) => mockPermissions.permissions.has(p)),
  hasAllPermissions: (...perms: string[]) =>
    perms.every((p) => mockPermissions.permissions.has(p)),
  isLoading: false,
  customRoleId: null as string | null,
}));

const mockApi = vi.hoisted(() => ({
  getSourceHealthSummary: vi.fn(),
  getSourceHealthCharts: vi.fn(),
  listSourceHealth: vi.fn(),
  getSourceHealthError: vi.fn(),
  exportSourceHealth: vi.fn(),
}));

const mockDocumentsApi = vi.hoisted(() => ({
  reindexDocument: vi.fn(),
  retryDocumentOcr: vi.fn(),
  updateDocumentTrustStatus: vi.fn(),
}));

const mockCollectionsApi = vi.hoisted(() => ({
  updateCollection: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state }),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => mockPermissions,
  useEffectivePermissions: () => mockPermissions,
}));

vi.mock("@/lib/api/source-health", () => ({
  getSourceHealthSummary: (...args: unknown[]) =>
    mockApi.getSourceHealthSummary(...args),
  getSourceHealthCharts: (...args: unknown[]) =>
    mockApi.getSourceHealthCharts(...args),
  listSourceHealth: (...args: unknown[]) => mockApi.listSourceHealth(...args),
  getSourceHealthError: (...args: unknown[]) =>
    mockApi.getSourceHealthError(...args),
  exportSourceHealth: (...args: unknown[]) =>
    mockApi.exportSourceHealth(...args),
}));

vi.mock("@/lib/api/documents", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/documents")>(
    "@/lib/api/documents",
  );
  return {
    ...actual,
    reindexDocument: (...args: unknown[]) =>
      mockDocumentsApi.reindexDocument(...args),
    retryDocumentOcr: (...args: unknown[]) =>
      mockDocumentsApi.retryDocumentOcr(...args),
    updateDocumentTrustStatus: (...args: unknown[]) =>
      mockDocumentsApi.updateDocumentTrustStatus(...args),
  };
});

vi.mock("@/lib/api/collections", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/collections")>(
    "@/lib/api/collections",
  );
  return {
    ...actual,
    updateCollection: (...args: unknown[]) =>
      mockCollectionsApi.updateCollection(...args),
  };
});

const SUMMARY: SourceHealthSummary = {
  total_sources: 12,
  indexed: 8,
  failed_indexing: 1,
  pending: 2,
  ocr_required: 3,
  ocr_low_confidence: 1,
  table_extraction_warnings: 1,
  missing_metadata: 2,
  stale: 1,
  deprecated: 1,
  expired: 0,
  unreviewed: 2,
  needs_review: 3,
  generated_at: "2026-08-19T00:00:00Z",
};

const CHARTS: SourceHealthCharts = {
  status_distribution: [{ status: "indexed", count: 8 }],
  indexing_failures: [{ date: "2026-08-01", failed_count: 1 }],
  stale_by_collection: [
    { collection_id: "col-1", collection_name: "Policies", stale_count: 1 },
  ],
  ocr_quality_distribution: [{ ocr_quality_status: "low", count: 1 }],
  review_needs_by_owner: [
    { owner_id: "user-1", owner_name: "Ada Lovelace", needs_review_count: 2 },
  ],
  connector_freshness: [
    {
      connection_id: "conn-1",
      connector_name: "Confluence",
      provider_key: "confluence",
      last_successful_sync_at: "2026-08-10T00:00:00Z",
      days_since_last_sync: 9,
      status: "active",
    },
  ],
  generated_at: "2026-08-19T00:00:00Z",
};

function makeRow(overrides: Partial<SourceHealthRow> = {}): SourceHealthRow {
  return {
    source_type: "file",
    source_id: "doc-1",
    source_name: "handbook.pdf",
    connector_name: null,
    collection_id: null,
    collection_name: null,
    owner_id: "user-1",
    owner_name: "Ada Lovelace",
    status: "indexed",
    last_indexed_at: "2026-08-15T00:00:00Z",
    last_updated_at: "2026-08-16T00:00:00Z",
    freshness: "fresh",
    trust_status: "current",
    ocr_quality: "high",
    review_status: "current",
    graph_indexed: "completed",
    missing_metadata: false,
    error_message: null,
    available_actions: [
      "reindex",
      "assign_reviewer",
      "mark_verified",
      "mark_deprecated",
      "open_document",
    ],
    ...overrides,
  };
}

function listResponse(rows: SourceHealthRow[]): SourceHealthList {
  return { rows, total: rows.length, page: 1, page_size: 25 };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminSourceHealthPage />
    </QueryClientProvider>,
  );
}

describe("AdminSourceHealthPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPermissions.role = "admin";
    mockPermissions.permissions = new Set([
      "documents:manage",
      "collections:manage",
    ]);
    mockAuth.state = {
      status: "authenticated",
      session: {
        userId: "user-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
      },
    } as SessionState;

    mockApi.getSourceHealthSummary.mockResolvedValue(SUMMARY);
    mockApi.getSourceHealthCharts.mockResolvedValue(CHARTS);
    mockApi.listSourceHealth.mockResolvedValue(listResponse([makeRow()]));
  });

  // A. Source health metric tests -------------------------------------------
  it("renders summary metric cards with values from the API", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Total sources")).toBeInTheDocument();
    });
    function cardValue(label: string): string | null {
      const labelEl = screen.getByText(label);
      return (
        labelEl.closest("div")?.querySelector("p:last-child")?.textContent ??
        null
      );
    }
    expect(cardValue("Total sources")).toBe("12");
    expect(cardValue("Indexed")).toBe("8");
    expect(cardValue("Failed indexing")).toBe("1");
  });

  // B. Indexing status tests --------------------------------------------------
  it("shows the source status and freshness badges from the row", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("handbook.pdf")).toBeInTheDocument();
    });
    const table = screen.getByRole("table");
    expect(within(table).getByText("indexed")).toBeInTheDocument();
    expect(within(table).getByText("fresh")).toBeInTheDocument();
  });

  // C. OCR warning display tests -----------------------------------------------
  it("shows a Retry OCR action when ocr_quality is low", async () => {
    mockApi.listSourceHealth.mockResolvedValue(
      listResponse([
        makeRow({
          source_id: "doc-ocr",
          source_name: "scanned.pdf",
          ocr_quality: "low",
          available_actions: ["reindex", "ocr_retry", "view_error"],
          error_message: "OCR confidence below threshold",
        }),
      ]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("scanned.pdf")).toBeInTheDocument();
    });
    const table = screen.getByRole("table");
    expect(within(table).getByText("low")).toBeInTheDocument();
    expect(screen.getByText("Retry OCR")).toBeInTheDocument();
    expect(screen.getByText("View error")).toBeInTheDocument();
  });

  // D. Row action calls the underlying API and refreshes the list -------------
  it("calls reindexDocument and refetches the list when Re-index is clicked", async () => {
    const user = userEvent.setup();
    mockDocumentsApi.reindexDocument.mockResolvedValue({});
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("handbook.pdf")).toBeInTheDocument();
    });
    await user.click(screen.getByText("Re-index"));

    await waitFor(() => {
      expect(mockDocumentsApi.reindexDocument).toHaveBeenCalledWith("doc-1");
    });
    await waitFor(() => {
      expect(mockApi.listSourceHealth).toHaveBeenCalledTimes(2);
    });
  });

  // E. Source table filter tests -----------------------------------------------
  it("re-queries with the selected source type filter", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("handbook.pdf")).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByLabelText("Source type"), "connector");

    await waitFor(() => {
      const lastCall =
        mockApi.listSourceHealth.mock.calls[
          mockApi.listSourceHealth.mock.calls.length - 1
        ];
      expect(lastCall[0]).toMatchObject({ source_type: "connector" });
    });
  });

  it("re-queries with missing_metadata=true when the checkbox is toggled", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("handbook.pdf")).toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Missing metadata only"));

    await waitFor(() => {
      const lastCall =
        mockApi.listSourceHealth.mock.calls[
          mockApi.listSourceHealth.mock.calls.length - 1
        ];
      expect(lastCall[0]).toMatchObject({ missing_metadata: true });
    });
  });

  // F. Role-based action tests --------------------------------------------------
  it("hides mutating actions when the user lacks documents:manage", async () => {
    mockPermissions.permissions = new Set([]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("handbook.pdf")).toBeInTheDocument();
    });
    expect(screen.queryByText("Re-index")).not.toBeInTheDocument();
    expect(screen.queryByText("Mark verified")).not.toBeInTheDocument();
    // The row is still visible and still links to the document (view-only).
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("shows a forbidden state for non-admin roles", () => {
    mockAuth.state = {
      status: "authenticated",
      session: {
        userId: "user-2",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
      },
    } as SessionState;
    renderPage();
    expect(screen.getByText("Admin access restricted")).toBeInTheDocument();
    expect(mockApi.getSourceHealthSummary).not.toHaveBeenCalled();
  });

  // G. Charts render ------------------------------------------------------------
  it("renders chart section titles", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Source status distribution" }),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("heading", { name: "OCR quality" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Connector-backed freshness" }),
    ).toBeInTheDocument();
  });

  // H. Collection row action maps to updateCollection ---------------------------
  it("marks a collection row verified via updateCollection with review_status=trusted", async () => {
    const user = userEvent.setup();
    mockApi.listSourceHealth.mockResolvedValue(
      listResponse([
        makeRow({
          source_type: "collection",
          source_id: "col-1",
          source_name: "Policies",
          ocr_quality: null,
          available_actions: [
            "assign_reviewer",
            "mark_verified",
            "mark_deprecated",
            "open_collection",
          ],
        }),
      ]),
    );
    mockCollectionsApi.updateCollection.mockResolvedValue({});
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Policies")).toBeInTheDocument();
    });
    const row = screen.getByText("Policies").closest("tr");
    expect(row).not.toBeNull();
    await user.click(within(row as HTMLElement).getByText("Mark verified"));

    await waitFor(() => {
      expect(mockCollectionsApi.updateCollection).toHaveBeenCalledWith(
        "col-1",
        { review_status: "trusted" },
      );
    });
  });
});
