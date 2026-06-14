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
    provider_key: "confluence",
    provider: makeProvider(),
    display_name: "Engineering Confluence",
    external_account_id: "confluence-site-1",
    collection_id: null,
    status: "active",
    auth_config: { provider_key: "confluence", space_keys: ["ENG"] },
    last_sync_at: new Date().toISOString(),
    error_message: null,
    source_count: 3,
    indexed_document_count: 8,
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
      expect(screen.getByText("Confluence")).toBeInTheDocument();
      expect(screen.getByText("Engineering Confluence")).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /connected sources/i }),
      ).toBeInTheDocument();
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

  it("shows Google Drive as connectable in the catalog", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Google Drive")).toBeInTheDocument();
      const description = screen.getByText(
        "Index Docs, Sheets, and shared corporate drive folders.",
      );
      const card = description.closest("div");
      expect(card).not.toBeNull();
      expect(
        within(card as HTMLElement).getByRole("button", { name: "Connect" }),
      ).toBeInTheDocument();
    });
  });

  it("shows Microsoft SharePoint / OneDrive as connectable in the catalog", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("SharePoint / OneDrive")).toBeInTheDocument();
      const description = screen.getByText(
        "Connect Microsoft 365 sites, document libraries, and OneDrive files.",
      );
      const card = description.closest("div");
      expect(card).not.toBeNull();
      expect(
        within(card as HTMLElement).getByRole("button", { name: "Connect" }),
      ).toBeInTheDocument();
    });
  });

  it("links the Google Drive catalog button to the setup wizard", async () => {
    renderPage();

    const user = userEvent.setup();
    const description = await screen.findByText(
      "Index Docs, Sheets, and shared corporate drive folders.",
    );
    const card = description.closest("div");
    expect(card).not.toBeNull();

    await user.click(
      within(card as HTMLElement).getByRole("button", { name: "Connect" }),
    );

    await waitFor(() => {
      expect(routerPush).toHaveBeenCalledWith("/connectors/new/google_drive");
    });
  });

  it("links the Microsoft catalog button to the setup wizard", async () => {
    renderPage();

    const user = userEvent.setup();
    const description = await screen.findByText(
      "Connect Microsoft 365 sites, document libraries, and OneDrive files.",
    );
    const card = description.closest("div");
    expect(card).not.toBeNull();

    await user.click(
      within(card as HTMLElement).getByRole("button", { name: "Connect" }),
    );

    await waitFor(() => {
      expect(routerPush).toHaveBeenCalledWith(
        "/connectors/new/microsoft-sharepoint-onedrive",
      );
    });
  });

  it("deletes an active connected source", async () => {
    mockApi.listConnectorConnections
      .mockResolvedValueOnce(makeConnectionsResponse([makeConnection()]))
      .mockResolvedValueOnce(makeConnectionsResponse([]));

    renderPage();

    const user = userEvent.setup();
    const deleteButton = await screen.findByRole("button", {
      name: "Delete connected source Engineering Confluence",
    });
    await user.click(deleteButton);

    await waitFor(() => {
      expect(mockApi.disconnectConnector).toHaveBeenCalledWith("conn-1");
      expect(
        screen.queryByText("Engineering Confluence"),
      ).not.toBeInTheDocument();
    });
  });

  it("shows paused connections in the table", async () => {
    mockApi.listConnectorConnections.mockResolvedValue(
      makeConnectionsResponse([
        makeConnection({
          id: "conn-2",
          status: "paused",
          display_name: "Paused Confluence",
        }),
      ]),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Paused Confluence")).toBeInTheDocument();
      expect(screen.getByText("PAUSED")).toBeInTheDocument();
    });
  });

  it("shows error connections in the table with error badge", async () => {
    mockApi.listConnectorConnections.mockResolvedValue(
      makeConnectionsResponse([
        makeConnection({
          id: "conn-3",
          status: "error",
          display_name: "Broken Confluence",
          error_message: "Token expired",
        }),
      ]),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Broken Confluence")).toBeInTheDocument();
      expect(screen.getByText("ERROR")).toBeInTheDocument();
    });
  });

  it("counts all connections including paused and error in the table", async () => {
    mockApi.listConnectorConnections.mockResolvedValue(
      makeConnectionsResponse([
        makeConnection({
          id: "conn-a",
          status: "active",
          display_name: "Active Source",
        }),
        makeConnection({
          id: "conn-b",
          status: "paused",
          display_name: "Paused Source",
        }),
        makeConnection({
          id: "conn-c",
          status: "error",
          display_name: "Error Source",
        }),
      ]),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Active Source")).toBeInTheDocument();
      expect(screen.getByText("Paused Source")).toBeInTheDocument();
      expect(screen.getByText("Error Source")).toBeInTheDocument();
    });
  });

  it("reflects failed count in the Failed syncs stat card", async () => {
    mockApi.listConnectorConnections.mockResolvedValue(
      makeConnectionsResponse([
        makeConnection({ id: "conn-ok", status: "active" }),
        makeConnection({
          id: "conn-fail",
          status: "error",
          display_name: "Broken Confluence",
          error_message: "Token expired",
        }),
      ]),
    );

    renderPage();

    await waitFor(() => {
      // 1 failed connection — stat card shows "01"
      const failedLabel = screen.getByText("Failed syncs");
      const statCard = failedLabel.closest("div")?.parentElement;
      expect(statCard).toBeTruthy();
      expect(
        within(statCard as HTMLElement).getByText("01"),
      ).toBeInTheDocument();
    });
  });

  it("shows the empty catalog browse link when no connections exist", async () => {
    mockApi.listConnectorConnections.mockResolvedValue(
      makeConnectionsResponse([]),
    );

    renderPage();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /browse the catalog/i }),
      ).toBeInTheDocument();
    });
  });
});
