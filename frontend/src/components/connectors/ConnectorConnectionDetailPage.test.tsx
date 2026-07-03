import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectorConnectionDetailPage } from "@/components/connectors/ConnectorConnectionDetailPage";
import type { ConnectorConnectionDetail } from "@/lib/api/connectors";
import type {
  SyncJobsListResponse,
  SyncRunsListResponse,
} from "@/lib/api/connector-sync";

const mockConnectorApi = vi.hoisted(() => ({
  getConnectorConnection: vi.fn(),
  refreshConnectorCredential: vi.fn(),
  disconnectConnector: vi.fn(),
}));

const mockSyncApi = vi.hoisted(() => ({
  listSyncJobs: vi.fn(),
  listSyncRuns: vi.fn(),
  retrySyncRun: vi.fn(),
}));

vi.mock("@/lib/api/connectors", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/connectors")>();
  return {
    ...actual,
    getConnectorConnection: (...args: unknown[]) =>
      mockConnectorApi.getConnectorConnection(...args),
    refreshConnectorCredential: (...args: unknown[]) =>
      mockConnectorApi.refreshConnectorCredential(...args),
    disconnectConnector: (...args: unknown[]) =>
      mockConnectorApi.disconnectConnector(...args),
  };
});

vi.mock("@/lib/api/connector-sync", () => ({
  listSyncJobs: (...args: unknown[]) => mockSyncApi.listSyncJobs(...args),
  listSyncRuns: (...args: unknown[]) => mockSyncApi.listSyncRuns(...args),
  retrySyncRun: (...args: unknown[]) => mockSyncApi.retrySyncRun(...args),
  createSyncJob: vi.fn(),
  updateSyncJobStatus: vi.fn(),
  triggerSyncNow: vi.fn(),
  cancelSyncRun: vi.fn(),
  getSyncJob: vi.fn(),
  getSyncRun: vi.fn(),
}));

const routerPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

function makeDetail(): ConnectorConnectionDetail {
  return {
    id: "conn-1",
    provider_key: "confluence",
    provider: {
      key: "confluence",
      display_name: "Confluence",
      enabled_by_default: true,
      has_oauth: true,
      capabilities: {
        auth_type: "oauth2",
        capabilities: ["delta_sync", "attachments", "comments", "acls"],
        rate_limits: [],
        export_formats: [],
        max_page_size: 100,
        notes: null,
      },
      config_schema: {
        type: "object",
        properties: {
          site_url: { type: "string", format: "uri" },
          space_keys: { type: "array", items: { type: "string" } },
          cql_filter: { type: "string" },
          include_comments: { type: "boolean" },
        },
        required: ["site_url"],
        additionalProperties: false,
      },
    },
    display_name: "Engineering Docs",
    external_account_id: "confluence-site-1",
    collection_id: null,
    status: "active",
    auth_config: {
      provider_key: "confluence",
      site_url: "https://acme.atlassian.net",
      space_keys: ["ENG", "DOCS"],
      cql_filter: "type = page",
      include_comments: true,
    },
    last_sync_at: new Date().toISOString(),
    error_message: null,
    source_count: 3,
    indexed_document_count: 8,
    sync_job_count: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    diagnostics: {
      connection_id: "conn-1",
      provider_key: "confluence",
      status: "active",
      error_message: null,
      auth_type: "oauth2",
      credential_status: "active",
      credential_version: 1,
      credential_fingerprint: "fingerprint",
      scopes: ["read:confluence-content.all"],
      expires_at: null,
      metadata: { provider_key: "confluence" },
    },
    source_permission_snapshots: [
      {
        id: "source-1",
        provider_source_id: "space-123",
        name: "Engineering Docs",
        source_type: "wiki_page",
        is_enabled: true,
        permissions: { entries: [{ type: "user", role: "reader" }] },
      },
    ],
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ConnectorConnectionDetailPage connectionId="conn-1" />
    </QueryClientProvider>,
  );
}

describe("ConnectorConnectionDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConnectorApi.getConnectorConnection.mockResolvedValue(makeDetail());
    mockConnectorApi.refreshConnectorCredential.mockResolvedValue({});
    mockConnectorApi.disconnectConnector.mockResolvedValue({});
    mockSyncApi.listSyncJobs.mockResolvedValue({
      items: [],
      total: 0,
    } satisfies SyncJobsListResponse);
    mockSyncApi.listSyncRuns.mockResolvedValue({
      items: [],
      total: 0,
    } satisfies SyncRunsListResponse);
  });

  it("renders scope and diagnostics for a connection", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Engineering Docs")).toBeInTheDocument();
      expect(screen.getByText("Granted Scopes")).toBeInTheDocument();
      expect(
        screen.getByText("read:confluence-content.all"),
      ).toBeInTheDocument();
      expect(screen.getByText("Trust State")).toBeInTheDocument();
      expect(screen.getByText("Healthy")).toBeInTheDocument();
    });
  });

  it("links ask in chat to the connector scoped chat view", async () => {
    renderPage();

    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /ask in chat/i }),
      ).toHaveAttribute(
        "href",
        "/chat?connection_id=conn-1&scope_mode=connectors",
      );
    });
  });

  it("shows a retry action for failed sync runs", async () => {
    mockSyncApi.listSyncJobs.mockResolvedValue({
      items: [
        {
          id: "job-1",
          organization_id: "org-1",
          connection_id: "conn-1",
          external_source_id: null,
          collection_id: null,
          name: "Hourly sync",
          status: "active",
          schedule: { type: "interval", interval_minutes: 60 },
          last_run_at: new Date().toISOString(),
          error_message: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      total: 1,
    } satisfies SyncJobsListResponse);
    mockSyncApi.listSyncRuns.mockResolvedValue({
      items: [
        {
          id: "run-1",
          organization_id: "org-1",
          sync_job_id: "job-1",
          connection_id: "conn-1",
          external_source_id: null,
          status: "failed",
          trigger_type: "manual",
          sync_version: 1,
          started_at: new Date().toISOString(),
          completed_at: new Date().toISOString(),
          items_seen: 12,
          items_upserted: 8,
          items_deleted: 0,
          cursor_before: { page_token: "cursor-1" },
          cursor_after: {},
          error_message: "Provider token expired",
          error_details: { code: "auth_error" },
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      total: 1,
    } satisfies SyncRunsListResponse);
    mockSyncApi.retrySyncRun.mockResolvedValue({
      sync_run_id: "run-2",
      status: "queued",
      message: "Sync retried",
    });

    const user = userEvent.setup();
    renderPage();

    const retryButton = await screen.findByRole("button", { name: /retry/i });
    await user.click(retryButton);

    await waitFor(() => {
      expect(mockSyncApi.retrySyncRun).toHaveBeenCalledWith("run-1");
    });
  });

  it("disconnects the connector without deleting the record", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: /more actions/i }),
    );
    await user.click(screen.getByRole("button", { name: /disconnect/i }));

    await waitFor(() => {
      expect(mockConnectorApi.disconnectConnector).toHaveBeenCalledWith(
        "conn-1",
      );
      expect(routerPush).toHaveBeenCalledWith("/connectors");
    });
  });
});
