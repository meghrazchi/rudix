import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BillingSettingsTab } from "@/components/settings/BillingSettingsTab";
import type { SessionState } from "@/lib/auth-session";
import type {
  BillingCapabilities,
  BillingPlanInfo,
  BillingUsageSummary,
  BillingQuota,
  Invoice,
} from "@/lib/api/billing";

// ── Mock: auth session ────────────────────────────────────────────────────────

const mockAuth = vi.hoisted(() => ({
  state: { status: "authenticated", session: null } as SessionState,
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state }),
}));

// ── Mock: runtime config ──────────────────────────────────────────────────────

vi.mock("@/lib/runtime-config", () => ({
  getFrontendRuntimeConfig: () => ({
    apiUrl: "http://localhost:8000/api/v1",
    appUrl: "http://localhost:3000",
    authProvider: "app",
    authProviderRaw: "app",
    features: {
      developerMode: false,
      feedback: false,
      exports: false,
      unavailableBackendEndpoints: false,
    },
  }),
}));

// ── Mock: billing API ─────────────────────────────────────────────────────────

const mockBillingApi = vi.hoisted(() => ({
  capabilities: {
    planEnabled: false,
    usageEnabled: false,
    quotasEnabled: false,
    invoicesEnabled: false,
    billingContactEnabled: false,
    updateBillingContactEnabled: false,
  } as BillingCapabilities,
  getBillingPlanInfo: vi.fn(),
  getBillingUsageSummary: vi.fn(),
  getBillingQuotas: vi.fn(),
  getInvoices: vi.fn(),
  getBillingContact: vi.fn(),
  updateBillingContact: vi.fn(),
}));

vi.mock("@/lib/api/billing", () => ({
  getBillingCapabilities: () => mockBillingApi.capabilities,
  getBillingPlanInfo: (...args: unknown[]) =>
    mockBillingApi.getBillingPlanInfo(...args),
  getBillingUsageSummary: (...args: unknown[]) =>
    mockBillingApi.getBillingUsageSummary(...args),
  getBillingQuotas: (...args: unknown[]) =>
    mockBillingApi.getBillingQuotas(...args),
  getInvoices: (...args: unknown[]) => mockBillingApi.getInvoices(...args),
  getBillingContact: (...args: unknown[]) =>
    mockBillingApi.getBillingContact(...args),
  updateBillingContact: (...args: unknown[]) =>
    mockBillingApi.updateBillingContact(...args),
  isBillingEndpointUnavailableError: () => false,
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderTab() {
  const qc = makeQueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <BillingSettingsTab />
    </QueryClientProvider>,
  );
}

function ownerSession(): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "u1",
      email: "owner@example.com",
      role: "owner",
      organizationId: "org1",
      organizationName: "Acme",
      accessToken: "tok",
      refreshToken: null,
    },
  };
}

function memberSession(): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "u2",
      email: "member@example.com",
      role: "member",
      organizationId: "org1",
      organizationName: "Acme",
      accessToken: "tok",
      refreshToken: null,
    },
  };
}

const basePlan: BillingPlanInfo = {
  plan_name: "Enterprise Pro",
  status: "active",
  billing_cycle: "monthly",
  renewal_date: "2024-11-01T00:00:00Z",
  trial_end_date: null,
  seats_used: 24,
  seats_included: 50,
  storage_used_gb: 842,
  storage_included_gb: 2048,
  monthly_questions_used: 458291,
  monthly_questions_included: 1000000,
  token_allowance_used: 1200000000,
  token_allowance_included: 2500000000,
  evaluation_allowance_used: null,
  evaluation_allowance_included: null,
  agent_allowance_used: null,
  agent_allowance_included: null,
  connector_allowance_used: null,
  connector_allowance_included: null,
  can_manage_subscription: true,
  can_cancel_plan: true,
};

const baseUsage: BillingUsageSummary = {
  range: { from: "2024-10-01", to: "2024-10-31" },
  documents_uploaded: 1200,
  indexed_documents: 1190,
  storage_used_gb: 42.1,
  total_chunks: 58000,
  questions_asked: 458291,
  avg_confidence: 0.9998,
  avg_latency_ms: 242,
  input_tokens: 900000000,
  output_tokens: 300000000,
  estimated_llm_cost_usd: 1284.42,
  evaluation_runs: 35,
  agent_runs: 120,
  connector_sync_jobs: 48,
  failed_indexing_jobs: 2,
};

const baseQuotas: BillingQuota[] = [
  { resource: "seats", label: "Seats", used: 24, limit: 50, unit: "seats" },
  {
    resource: "storage",
    label: "Storage",
    used: 842,
    limit: 2048,
    unit: "GB",
  },
  {
    resource: "questions",
    label: "Monthly Questions",
    used: 900000,
    limit: 1000000,
    unit: "",
  },
];

const baseInvoices: Invoice[] = [
  {
    id: "INV-2024-1001",
    date: "2024-10-01T00:00:00Z",
    amount_usd: 2450.0,
    status: "paid",
    download_url: "https://example.com/invoices/1001.pdf",
  },
  {
    id: "INV-2024-0901",
    date: "2024-09-01T00:00:00Z",
    amount_usd: 2450.0,
    status: "paid",
    download_url: null,
  },
];

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockAuth.state = { status: "authenticated", session: null };
  mockBillingApi.capabilities = {
    planEnabled: false,
    usageEnabled: false,
    quotasEnabled: false,
    invoicesEnabled: false,
    billingContactEnabled: false,
    updateBillingContactEnabled: false,
  };
  vi.clearAllMocks();
});

describe("BillingSettingsTab — access control", () => {
  it("shows forbidden state for member role", () => {
    mockAuth.state = memberSession();
    renderTab();
    expect(
      screen.getByText(/billing settings are available to owners and admins/i),
    ).toBeInTheDocument();
  });

  it("shows forbidden state for viewer role", () => {
    mockAuth.state = {
      status: "authenticated",
      session: {
        userId: "u3",
        email: "viewer@example.com",
        role: "viewer",
        organizationId: "org1",
        organizationName: "Acme",
        accessToken: "tok",
        refreshToken: null,
      },
    };
    renderTab();
    expect(
      screen.getByText(/billing settings are available to owners and admins/i),
    ).toBeInTheDocument();
  });
});

describe("BillingSettingsTab — portal fallback", () => {
  beforeEach(() => {
    mockAuth.state = ownerSession();
  });

  it("shows deployment-controlled plan section when no billing API is available", () => {
    renderTab();
    expect(
      screen.getByText(/plan details are not available/i),
    ).toBeInTheDocument();
  });

  it("renders portal link when NEXT_PUBLIC_SETTINGS_BILLING_URL is set", () => {
    const original = process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL;
    process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL =
      "https://billing.example.com";
    renderTab();
    expect(
      screen.getByRole("link", { name: /open billing portal/i }),
    ).toHaveAttribute("href", "https://billing.example.com");
    process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL = original;
  });

  it("shows no portal link when URL is not configured", () => {
    const original = process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL;
    delete process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL;
    renderTab();
    expect(
      screen.queryByRole("link", { name: /open billing portal/i }),
    ).not.toBeInTheDocument();
    process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL = original;
  });
});

describe("BillingSettingsTab — plan card", () => {
  beforeEach(() => {
    mockAuth.state = ownerSession();
    mockBillingApi.capabilities = {
      planEnabled: true,
      usageEnabled: true,
      quotasEnabled: true,
      invoicesEnabled: true,
      billingContactEnabled: false,
      updateBillingContactEnabled: false,
    };
    mockBillingApi.getBillingUsageSummary.mockResolvedValue(baseUsage);
    mockBillingApi.getBillingQuotas.mockResolvedValue(baseQuotas);
    mockBillingApi.getInvoices.mockResolvedValue(baseInvoices);
  });

  it("renders plan name and active status", async () => {
    mockBillingApi.getBillingPlanInfo.mockResolvedValue(basePlan);
    renderTab();
    await waitFor(() => {
      expect(screen.getByText("Enterprise Pro")).toBeInTheDocument();
      expect(screen.getByText("Active")).toBeInTheDocument();
    });
  });

  it("renders trial badge when status is trialing", async () => {
    mockBillingApi.getBillingPlanInfo.mockResolvedValue({
      ...basePlan,
      status: "trialing",
      trial_end_date: "2024-11-15T00:00:00Z",
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByText("Trial")).toBeInTheDocument();
    });
  });

  it("renders past_due badge", async () => {
    mockBillingApi.getBillingPlanInfo.mockResolvedValue({
      ...basePlan,
      status: "past_due",
    });
    renderTab();
    await waitFor(() => {
      expect(screen.getByText("Past due")).toBeInTheDocument();
    });
  });

  it("shows manage subscription button linking to portal URL", async () => {
    mockBillingApi.getBillingPlanInfo.mockResolvedValue(basePlan);
    const original = process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL;
    process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL =
      "https://billing.example.com";
    renderTab();
    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /manage subscription/i }),
      ).toHaveAttribute("href", "https://billing.example.com");
    });
    process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL = original;
  });

  it("shows loading state while plan is fetching", () => {
    mockBillingApi.getBillingPlanInfo.mockImplementation(
      () => new Promise(() => {}),
    );
    renderTab();
    expect(screen.getByText(/loading plan info/i)).toBeInTheDocument();
  });

  it("shows error state when plan fetch fails", async () => {
    mockBillingApi.getBillingPlanInfo.mockRejectedValue(
      new Error("Network error"),
    );
    renderTab();
    await waitFor(() => {
      expect(screen.getByText(/unable to load/i)).toBeInTheDocument();
    });
  });
});

describe("BillingSettingsTab — usage summary", () => {
  beforeEach(() => {
    mockAuth.state = ownerSession();
    mockBillingApi.capabilities = {
      planEnabled: false,
      usageEnabled: true,
      quotasEnabled: false,
      invoicesEnabled: false,
      billingContactEnabled: false,
      updateBillingContactEnabled: false,
    };
    mockBillingApi.getBillingQuotas.mockResolvedValue([]);
    mockBillingApi.getInvoices.mockResolvedValue([]);
  });

  it("renders usage metrics", async () => {
    mockBillingApi.getBillingUsageSummary.mockResolvedValue(baseUsage);
    renderTab();
    await waitFor(() => {
      expect(screen.getByText("458.3K")).toBeInTheDocument();
    });
  });

  it("shows estimated cost label", async () => {
    mockBillingApi.getBillingUsageSummary.mockResolvedValue(baseUsage);
    renderTab();
    await waitFor(() => {
      expect(
        screen.getByText(/llm cost values are estimates only/i),
      ).toBeInTheDocument();
    });
  });

  it("switches date range and refetches", async () => {
    mockBillingApi.getBillingUsageSummary.mockResolvedValue(baseUsage);
    const user = userEvent.setup();
    renderTab();
    await waitFor(() =>
      expect(mockBillingApi.getBillingUsageSummary).toHaveBeenCalledWith("30d"),
    );
    await user.click(screen.getByRole("button", { name: "7 days" }));
    await waitFor(() =>
      expect(mockBillingApi.getBillingUsageSummary).toHaveBeenCalledWith("7d"),
    );
  });

  it("shows loading state while usage is fetching", () => {
    mockBillingApi.getBillingUsageSummary.mockImplementation(
      () => new Promise(() => {}),
    );
    renderTab();
    expect(screen.getByText(/loading usage data/i)).toBeInTheDocument();
  });
});

describe("BillingSettingsTab — quota warnings", () => {
  beforeEach(() => {
    mockAuth.state = ownerSession();
    mockBillingApi.capabilities = {
      planEnabled: false,
      usageEnabled: false,
      quotasEnabled: true,
      invoicesEnabled: false,
      billingContactEnabled: false,
      updateBillingContactEnabled: false,
    };
    mockBillingApi.getBillingUsageSummary.mockResolvedValue(baseUsage);
    mockBillingApi.getInvoices.mockResolvedValue([]);
  });

  it("shows no warning for quota below 80%", async () => {
    mockBillingApi.getBillingQuotas.mockResolvedValue([
      { resource: "seats", label: "Seats", used: 20, limit: 50, unit: "seats" },
    ]);
    renderTab();
    await waitFor(() => {
      expect(screen.getByText("Seats")).toBeInTheDocument();
    });
    expect(screen.queryByText(/approaching limit/i)).not.toBeInTheDocument();
  });

  it("shows warning at 80% usage", async () => {
    mockBillingApi.getBillingQuotas.mockResolvedValue([
      { resource: "seats", label: "Seats", used: 40, limit: 50, unit: "seats" },
    ]);
    renderTab();
    await waitFor(() => {
      expect(screen.getByText(/approaching limit/i)).toBeInTheDocument();
    });
  });

  it("shows critical warning at 90% usage", async () => {
    mockBillingApi.getBillingQuotas.mockResolvedValue([
      { resource: "seats", label: "Seats", used: 46, limit: 50, unit: "seats" },
    ]);
    renderTab();
    await waitFor(() => {
      expect(screen.getByText(/quota almost exhausted/i)).toBeInTheDocument();
    });
  });

  it("shows quota reached warning at 100% usage", async () => {
    mockBillingApi.getBillingQuotas.mockResolvedValue([
      { resource: "seats", label: "Seats", used: 50, limit: 50, unit: "seats" },
    ]);
    renderTab();
    await waitFor(() => {
      expect(
        screen.getByText(/quota reached — upgrade or reduce usage/i),
      ).toBeInTheDocument();
    });
  });

  it("quota progress bars are accessible with progressbar role", async () => {
    mockBillingApi.getBillingQuotas.mockResolvedValue([
      { resource: "seats", label: "Seats", used: 24, limit: 50, unit: "seats" },
    ]);
    renderTab();
    await waitFor(() => {
      const bars = screen.getAllByRole("progressbar");
      expect(bars.length).toBeGreaterThan(0);
      expect(bars[0]).toHaveAttribute("aria-valuenow");
    });
  });
});

describe("BillingSettingsTab — invoices", () => {
  beforeEach(() => {
    mockAuth.state = ownerSession();
    mockBillingApi.capabilities = {
      planEnabled: false,
      usageEnabled: false,
      quotasEnabled: false,
      invoicesEnabled: true,
      billingContactEnabled: false,
      updateBillingContactEnabled: false,
    };
    mockBillingApi.getBillingUsageSummary.mockResolvedValue(baseUsage);
    mockBillingApi.getBillingQuotas.mockResolvedValue([]);
  });

  it("renders invoice rows", async () => {
    mockBillingApi.getInvoices.mockResolvedValue(baseInvoices);
    renderTab();
    await waitFor(() => {
      expect(screen.getByText("INV-2024-1001")).toBeInTheDocument();
      expect(screen.getByText("INV-2024-0901")).toBeInTheDocument();
    });
  });

  it("renders download link when download_url is present", async () => {
    mockBillingApi.getInvoices.mockResolvedValue(baseInvoices);
    renderTab();
    await waitFor(() => {
      expect(
        screen.getByRole("link", {
          name: /download invoice INV-2024-1001/i,
        }),
      ).toHaveAttribute("href", "https://example.com/invoices/1001.pdf");
    });
  });

  it("shows empty state when no invoices", async () => {
    mockBillingApi.getInvoices.mockResolvedValue([]);
    renderTab();
    await waitFor(() => {
      expect(screen.getByText(/no invoices found/i)).toBeInTheDocument();
    });
  });

  it("shows unavailable message when invoices not enabled", async () => {
    mockBillingApi.capabilities = {
      planEnabled: false,
      usageEnabled: false,
      quotasEnabled: true,
      invoicesEnabled: false,
      billingContactEnabled: false,
      updateBillingContactEnabled: false,
    };
    mockBillingApi.getBillingQuotas.mockResolvedValue([]);
    mockBillingApi.getInvoices.mockResolvedValue([]);
    renderTab();
    expect(
      screen.getByText(/invoice history is not available/i),
    ).toBeInTheDocument();
  });
});
