import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectorsPage } from "@/components/connectors/ConnectorsPage";
import type { ProviderSummary } from "@/lib/api/connector-providers";
import type {
  ConnectorConnectionSummary,
  ConnectorConnectionsListResponse,
} from "@/lib/api/connectors";

const mockApi = vi.hoisted(() => ({
  listProviders: vi.fn(),
  listConnectorConnections: vi.fn(),
  disconnectConnector: vi.fn(),
}));

vi.mock("@/lib/api/connector-providers", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/connector-providers")>();
  return {
    ...actual,
    listProviders: (...args: unknown[]) => mockApi.listProviders(...args),
  };
});

vi.mock("@/lib/api/connectors", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/connectors")>();
  return {
    ...actual,
    listConnectorConnections: (...args: unknown[]) =>
      mockApi.listConnectorConnections(...args),
    disconnectConnector: (...args: unknown[]) =>
      mockApi.disconnectConnector(...args),
  };
});

const routerPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

function makeProvider(
  overrides: Partial<ProviderSummary> = {},
): ProviderSummary {
  return {
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
      },
      required: ["site_url"],
      additionalProperties: false,
    },
    ...overrides,
  };
}

function makeConnection(
  overrides: Partial<ConnectorConnectionSummary> = {},
): ConnectorConnectionSummary {
  return {
    id: "conn-1",
    provider_key: "jira",
    provider: makeProvider(),
    display_name: "Engineering Jira",
    external_account_id: "jira-site-1",
    collection_id: null,
    status: "active",
    auth_config: { provider_key: "jira", project_keys: ["ENG"] },
    last_sync_at: new Date().toISOString(),
    error_message: null,
    source_count: 3,
    sync_job_count: 2,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function makeConnectionsResponse(
  connections: ConnectorConnectionSummary[],
): ConnectorConnectionsListResponse {
  return { items: connections, total: connections.length };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ConnectorsPage />
    </QueryClientProvider>,
  );
}

describe("ConnectorsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockApi.listProviders.mockResolvedValue({
      items: [makeProvider()],
      total: 1,
    });
    mockApi.listConnectorConnections.mockResolvedValue(
      makeConnectionsResponse([makeConnection()]),
    );
    mockApi.disconnectConnector.mockResolvedValue({});
  });

  it("renders the connector catalog and connection table", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Jira")).toBeInTheDocument();
      expect(screen.getByText("Engineering Jira")).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /connected sources/i }),
      ).toBeInTheDocument();
    });
  });

  it("links the catalog button to the setup wizard", async () => {
    renderPage();

    const user = userEvent.setup();
    const confluenceDescription = await screen.findByText(
      "Import wiki pages, team spaces, and technical documents.",
    );
    const card = confluenceDescription.closest("div");
    expect(card).not.toBeNull();

    await user.click(
      within(card as HTMLElement).getByRole("button", { name: "Connect" }),
    );

    await waitFor(() => {
      expect(routerPush).toHaveBeenCalledWith("/connectors/new/confluence");
    });
  });

  it("shows Confluence as connectable in the catalog", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Confluence")).toBeInTheDocument();
      const confluenceDescription = screen.getByText(
        "Import wiki pages, team spaces, and technical documents.",
      );
      const card = confluenceDescription.closest("div");
      expect(card).not.toBeNull();
      expect(
        within(card as HTMLElement).getByRole("button", { name: "Connect" }),
      ).toBeInTheDocument();
    });
  });

  it("deletes an active connected source", async () => {
    mockApi.listConnectorConnections
      .mockResolvedValueOnce(makeConnectionsResponse([makeConnection()]))
      .mockResolvedValueOnce(makeConnectionsResponse([]));

    renderPage();

    const user = userEvent.setup();
    const deleteButton = await screen.findByRole("button", {
      name: "Delete connected source Engineering Jira",
    });
    await user.click(deleteButton);

    await waitFor(() => {
      expect(mockApi.disconnectConnector).toHaveBeenCalledWith("conn-1");
      expect(screen.queryByText("Engineering Jira")).not.toBeInTheDocument();
    });
  });
});
