import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
    provider_key: "jira",
    provider: {
      key: "jira",
      display_name: "Jira",
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
          project_keys: { type: "array", items: { type: "string" } },
        },
        required: ["site_url"],
        additionalProperties: false,
      },
    },
    display_name: "Engineering Jira",
    external_account_id: "jira-site-1",
    collection_id: null,
    status: "active",
    auth_config: {
      provider_key: "jira",
      site_url: "https://jira.example.test",
      project_keys: ["ENG", "DOCS"],
      jql_filter: "status != Done",
    },
    last_sync_at: new Date().toISOString(),
    error_message: null,
    source_count: 3,
    sync_job_count: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    diagnostics: {
      connection_id: "conn-1",
      provider_key: "jira",
      status: "active",
      error_message: null,
      auth_type: "oauth2",
      credential_status: "active",
      credential_version: 1,
      credential_fingerprint: "fingerprint",
      scopes: ["read:jira-work"],
      expires_at: null,
      metadata: { provider_key: "jira" },
    },
    source_permission_snapshots: [
      {
        id: "source-1",
        provider_source_id: "jira-123",
        name: "Engineering Docs",
        source_type: "space",
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
      expect(screen.getByText("Engineering Jira")).toBeInTheDocument();
      expect(screen.getByText("Project keys")).toBeInTheDocument();
      expect(screen.getByText("JQL filter")).toBeInTheDocument();
      expect(screen.getByText("read:jira-work")).toBeInTheDocument();
      expect(screen.getByText("Access review hooks")).toBeInTheDocument();
      expect(screen.getByText("Engineering Docs")).toBeInTheDocument();
    });
  });
});
