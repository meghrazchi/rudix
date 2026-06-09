import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CapabilityBadge,
  ProviderCapabilityBadges,
  ProviderCard,
  ProviderPicker,
  ProviderSetupHints,
} from "@/components/connectors/ProviderCapabilityBadges";
import type {
  ConnectorCapabilityKey,
  ProvidersListResponse,
  ProviderSummary,
} from "@/lib/api/connector-providers";

// ── Mock: connector-providers API ────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  listProviders: vi.fn(),
  getProvider: vi.fn(),
  hasCapability: vi.fn(),
}));

vi.mock("@/lib/api/connector-providers", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/connector-providers")>();
  return {
    ...actual,
    listProviders: (...args: unknown[]) => mockApi.listProviders(...args),
    getProvider: (...args: unknown[]) => mockApi.getProvider(...args),
  };
});

// ── Helpers ───────────────────────────────────────────────────────────────────

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
      capabilities: ["delta_sync", "acls", "attachments", "rate_limits"],
      rate_limits: [
        {
          name: "rest_api",
          max_requests: 500,
          window_seconds: 60,
          burst: null,
        },
      ],
      export_formats: [],
      max_page_size: 100,
      notes: null,
    },
    config_schema: {
      type: "object",
      properties: {},
      required: [],
      additionalProperties: false,
    },
    ...overrides,
  };
}

function makeProvidersResponse(
  providers: ProviderSummary[],
): ProvidersListResponse {
  return { items: providers, total: providers.length };
}

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

// ── CapabilityBadge ───────────────────────────────────────────────────────────

describe("CapabilityBadge", () => {
  it("renders the label for a known capability", () => {
    render(<CapabilityBadge capability="delta_sync" />);
    expect(screen.getByText("Incremental sync")).toBeInTheDocument();
  });

  it("shows tooltip title when showTooltip is true", () => {
    render(<CapabilityBadge capability="acls" showTooltip />);
    const badge = screen.getByText("Permission-aware");
    expect(badge).toHaveAttribute("title");
  });

  it("omits title when showTooltip is false", () => {
    render(<CapabilityBadge capability="acls" showTooltip={false} />);
    const badge = screen.getByText("Permission-aware");
    expect(badge).not.toHaveAttribute("title");
  });

  it("renders nothing for an unknown capability", () => {
    const { container } = render(
      <CapabilityBadge capability={"unknown_cap" as ConnectorCapabilityKey} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

// ── ProviderCapabilityBadges ──────────────────────────────────────────────────

describe("ProviderCapabilityBadges", () => {
  it("renders all capability badges for a provider", () => {
    const provider = makeProvider();
    render(<ProviderCapabilityBadges provider={provider} />);
    expect(screen.getByText("Incremental sync")).toBeInTheDocument();
    expect(screen.getByText("Permission-aware")).toBeInTheDocument();
    expect(screen.getByText("Attachments")).toBeInTheDocument();
    expect(screen.getByText("Rate-limit aware")).toBeInTheDocument();
  });

  it("renders Microsoft-specific capability badges", () => {
    const provider = makeProvider({
      key: "microsoft-sharepoint-onedrive",
      display_name: "SharePoint / OneDrive",
      capabilities: {
        ...makeProvider().capabilities,
        capabilities: ["files", "deletions", "deep_links"],
      },
    });
    render(<ProviderCapabilityBadges provider={provider} />);
    expect(screen.getByText("Files")).toBeInTheDocument();
    expect(screen.getByText("Deletions")).toBeInTheDocument();
    expect(screen.getByText("Deep links")).toBeInTheDocument();
  });

  it("filters to onlyCapabilities when provided", () => {
    const provider = makeProvider();
    render(
      <ProviderCapabilityBadges
        provider={provider}
        onlyCapabilities={["delta_sync"]}
      />,
    );
    expect(screen.getByText("Incremental sync")).toBeInTheDocument();
    expect(screen.queryByText("Permission-aware")).not.toBeInTheDocument();
  });

  it("renders nothing when provider has no capabilities", () => {
    const provider = makeProvider({
      capabilities: { ...makeProvider().capabilities, capabilities: [] },
    });
    const { container } = render(
      <ProviderCapabilityBadges provider={provider} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when all filtered capabilities absent", () => {
    const provider = makeProvider();
    const { container } = render(
      <ProviderCapabilityBadges
        provider={provider}
        onlyCapabilities={["webhooks"]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

// ── ProviderSetupHints ────────────────────────────────────────────────────────

describe("ProviderSetupHints", () => {
  it("shows incremental sync hint when delta_sync is present", () => {
    const provider = makeProvider();
    render(<ProviderSetupHints provider={provider} />);
    expect(screen.getByText(/Incremental syncs/i)).toBeInTheDocument();
  });

  it("shows webhook hint when webhooks capability is present", () => {
    const provider = makeProvider({
      capabilities: {
        ...makeProvider().capabilities,
        capabilities: ["webhooks"],
      },
    });
    render(<ProviderSetupHints provider={provider} />);
    expect(screen.getByText(/webhook/i)).toBeInTheDocument();
  });

  it("shows acl hint when acls capability is present", () => {
    const provider = makeProvider();
    render(<ProviderSetupHints provider={provider} />);
    expect(screen.getByText(/Permission data/i)).toBeInTheDocument();
  });

  it("shows export format hint when multiple formats exist", () => {
    const provider = makeProvider({
      capabilities: {
        ...makeProvider().capabilities,
        capabilities: ["export_formats"],
        export_formats: [
          { format: "storage", mime_type: "text/html" },
          { format: "atlas_doc", mime_type: "application/json" },
        ],
      },
    });
    render(<ProviderSetupHints provider={provider} />);
    expect(screen.getByText(/2 export formats/i)).toBeInTheDocument();
  });

  it("renders nothing for a provider with no relevant capabilities", () => {
    const provider = makeProvider({
      capabilities: {
        ...makeProvider().capabilities,
        capabilities: [],
        export_formats: [],
      },
    });
    const { container } = render(<ProviderSetupHints provider={provider} />);
    expect(container).toBeEmptyDOMElement();
  });
});

// ── ProviderCard ──────────────────────────────────────────────────────────────

describe("ProviderCard", () => {
  it("renders the provider display name", () => {
    render(<ProviderCard provider={makeProvider()} />);
    expect(screen.getByText("Confluence")).toBeInTheDocument();
  });

  it("shows OAuth badge when has_oauth is true", () => {
    render(<ProviderCard provider={makeProvider({ has_oauth: true })} />);
    expect(screen.getByText("OAuth")).toBeInTheDocument();
  });

  it("hides OAuth badge when has_oauth is false", () => {
    render(<ProviderCard provider={makeProvider({ has_oauth: false })} />);
    expect(screen.queryByText("OAuth")).not.toBeInTheDocument();
  });

  it("applies selected ring style when selected=true", () => {
    const { container } = render(
      <ProviderCard provider={makeProvider()} selected />,
    );
    expect(container.firstChild).toHaveClass("ring-1");
  });

  it("calls onClick when card is clicked", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<ProviderCard provider={makeProvider()} onClick={onClick} />);
    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

// ── ProviderPicker ────────────────────────────────────────────────────────────

describe("ProviderPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state while fetching", () => {
    mockApi.listProviders.mockReturnValue(new Promise(() => {}));
    renderWithQuery(<ProviderPicker selectedKey={null} onSelect={vi.fn()} />);
    expect(screen.getByText("Loading providers…")).toBeInTheDocument();
  });

  it("shows error state when fetch fails", async () => {
    mockApi.listProviders.mockRejectedValue(new Error("network error"));
    renderWithQuery(<ProviderPicker selectedKey={null} onSelect={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText("Failed to load providers.")).toBeInTheDocument();
    });
  });

  it("renders cards for each enabled provider", async () => {
    const confluence = makeProvider({
      key: "confluence",
      display_name: "Confluence",
    });
    mockApi.listProviders.mockResolvedValue(
      makeProvidersResponse([confluence]),
    );

    renderWithQuery(<ProviderPicker selectedKey={null} onSelect={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText("Confluence")).toBeInTheDocument();
    });
  });

  it("marks the selected provider card with selected style", async () => {
    const confluence = makeProvider({ key: "confluence" });
    mockApi.listProviders.mockResolvedValue(
      makeProvidersResponse([confluence]),
    );

    renderWithQuery(
      <ProviderPicker selectedKey="confluence" onSelect={vi.fn()} />,
    );
    await waitFor(() => {
      expect(screen.getByRole("button")).toHaveClass("ring-1");
    });
  });

  it("calls onSelect with the provider key when a card is clicked", async () => {
    const user = userEvent.setup();
    const confluence = makeProvider({ key: "confluence" });
    mockApi.listProviders.mockResolvedValue(
      makeProvidersResponse([confluence]),
    );
    const onSelect = vi.fn();

    renderWithQuery(<ProviderPicker selectedKey={null} onSelect={onSelect} />);
    await waitFor(() => screen.getByText("Confluence"));
    await user.click(screen.getByRole("button"));
    expect(onSelect).toHaveBeenCalledWith("confluence");
  });

  it("hides disabled providers from the picker", async () => {
    const disabled = makeProvider({
      key: "legacy",
      display_name: "Legacy",
      enabled_by_default: false,
    });
    mockApi.listProviders.mockResolvedValue(makeProvidersResponse([disabled]));

    renderWithQuery(<ProviderPicker selectedKey={null} onSelect={vi.fn()} />);
    await waitFor(() => {
      expect(screen.queryByText("Legacy")).not.toBeInTheDocument();
    });
  });
});
