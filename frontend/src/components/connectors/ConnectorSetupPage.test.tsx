import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectorSetupPage } from "@/components/connectors/ConnectorSetupPage";
import type { ProviderSummary } from "@/lib/api/connector-providers";

const mockApi = vi.hoisted(() => ({
  getProvider: vi.fn(),
  beginConnectorOAuthConnect: vi.fn(),
  createConnectorConnection: vi.fn(),
}));

vi.mock("@/lib/api/connector-providers", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/connector-providers")>();
  return {
    ...actual,
    getProvider: (...args: unknown[]) => mockApi.getProvider(...args),
  };
});

vi.mock("@/lib/api/connectors", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/connectors")>();
  return {
    ...actual,
    beginConnectorOAuthConnect: (...args: unknown[]) =>
      mockApi.beginConnectorOAuthConnect(...args),
    createConnectorConnection: (...args: unknown[]) =>
      mockApi.createConnectorConnection(...args),
  };
});

const routerPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

function makeProvider(): ProviderSummary {
  return {
    key: "linear",
    display_name: "Linear",
    enabled_by_default: true,
    has_oauth: false,
    capabilities: {
      auth_type: "api_token",
      capabilities: ["delta_sync", "comments", "rate_limits"],
      rate_limits: [],
      export_formats: [],
      max_page_size: null,
      notes: "API token based provider.",
    },
    config_schema: {
      type: "object",
      properties: {
        api_token: { type: "string", title: "API token" },
        base_url: { type: "string", format: "uri", title: "Base URL" },
      },
      required: ["api_token", "base_url"],
      additionalProperties: false,
    },
  };
}

function makeConfluenceProvider(): ProviderSummary {
  return {
    key: "confluence",
    display_name: "Confluence",
    enabled_by_default: true,
    has_oauth: true,
    capabilities: {
      auth_type: "oauth2",
      capabilities: ["attachments", "comments", "acls", "delta_sync"],
      rate_limits: [],
      export_formats: [],
      max_page_size: 100,
      notes: "Confluence Cloud.",
    },
    config_schema: {
      type: "object",
      properties: {
        site_url: {
          type: "string",
          format: "uri",
          title: "Confluence site URL",
        },
        space_keys: {
          type: "array",
          items: { type: "string" },
          title: "Space keys",
        },
        cql_filter: {
          type: "string",
          title: "CQL filter",
        },
        include_comments: {
          type: "boolean",
          title: "Include page comments",
        },
      },
      required: ["site_url"],
      additionalProperties: false,
    },
  };
}

describe("ConnectorSetupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getProvider.mockResolvedValue(makeProvider());
    mockApi.beginConnectorOAuthConnect.mockResolvedValue({
      state: "state-1",
      authorization_url: "https://auth.example.test/authorize",
      expires_at: new Date().toISOString(),
      scopes: ["read:confluence-content.all"],
    });
    mockApi.createConnectorConnection.mockResolvedValue({
      id: "conn-linear-1",
      provider_key: "linear",
      provider: makeProvider(),
      display_name: "Linear Cloud",
      external_account_id: "linear-account",
      collection_id: null,
      status: "active",
      auth_config: {
        provider_key: "linear",
        api_token: "token-123",
        base_url: "https://linear.example.test",
      },
      last_sync_at: null,
      error_message: null,
      source_count: 0,
      sync_job_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  });

  it("renders provider-driven fields and creates a non-oauth connection", async () => {
    const user = userEvent.setup();
    render(<ConnectorSetupPage providerKey="linear" />);

    await waitFor(() => {
      expect(screen.getByText("Connect Linear")).toBeInTheDocument();
    });

    await user.clear(screen.getByLabelText(/Connection name/i));
    await user.type(screen.getByLabelText(/Connection name/i), "Linear Cloud");

    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => {
      expect(screen.getByLabelText(/API token/i)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/API token/i), "token-123");
    await user.type(
      screen.getByLabelText(/Base URL/i),
      "https://linear.example.test",
    );

    await user.click(screen.getByRole("button", { name: /next/i }));
    await user.click(
      screen.getByRole("button", { name: /complete connection/i }),
    );

    await waitFor(() => {
      expect(mockApi.createConnectorConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          provider_key: "linear",
          display_name: "Linear Cloud",
          config: {
            api_token: "token-123",
            base_url: "https://linear.example.test",
          },
        }),
      );
      expect(routerPush).toHaveBeenCalledWith("/connectors/conn-linear-1");
    });
  });

  it("renders confluence fields and starts the OAuth flow with config", async () => {
    mockApi.getProvider.mockResolvedValue(makeConfluenceProvider());
    const user = userEvent.setup();
    render(<ConnectorSetupPage providerKey="confluence" />);

    await waitFor(() => {
      expect(screen.getByText("Connect Confluence")).toBeInTheDocument();
    });

    await user.clear(screen.getByLabelText(/Connection name/i));
    await user.type(
      screen.getByLabelText(/Connection name/i),
      "Confluence Knowledge Base",
    );

    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => {
      expect(screen.getByLabelText(/Confluence site URL/i)).toBeInTheDocument();
    });

    await user.type(
      screen.getByLabelText(/Confluence site URL/i),
      "https://acme.atlassian.net",
    );
    await user.type(screen.getByLabelText(/Space keys/i), "docs, eng");
    await user.type(screen.getByLabelText(/CQL filter/i), 'label = "docs"');
    await user.click(screen.getByLabelText(/Include page comments/i));

    await user.click(screen.getByRole("button", { name: /next/i }));
    await user.click(
      screen.getByRole("button", { name: /complete connection/i }),
    );

    await waitFor(() => {
      expect(mockApi.beginConnectorOAuthConnect).toHaveBeenCalledWith(
        expect.objectContaining({
          provider_key: "confluence",
          redirect_uri:
            "http://localhost:8000/api/v1/connectors/oauth/callback",
          display_name: "Confluence Knowledge Base",
          config: {
            site_url: "https://acme.atlassian.net",
            space_keys: ["DOCS", "ENG"],
            cql_filter: 'label = "docs"',
            include_comments: true,
          },
        }),
      );
    });
  });
});
