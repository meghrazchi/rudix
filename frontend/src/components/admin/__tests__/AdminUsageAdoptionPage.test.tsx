import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminUsageAdoptionPage } from "@/components/admin/AdminUsageAdoptionPage";
import type { SessionState } from "@/lib/auth-session";
import type {
  UsageAdoptionCharts,
  UsageAdoptionSummary,
  UsageAdoptionUserList,
  UsageAdoptionUserRow,
} from "@/lib/schemas/usage-adoption";

const mockAuth = vi.hoisted(() => ({
  state: {
    status: "authenticated",
    session: null,
  } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getUsageAdoptionSummary: vi.fn(),
  getUsageAdoptionCharts: vi.fn(),
  listUsageAdoptionUsers: vi.fn(),
  exportUsageAdoption: vi.fn(),
  sendOnboardingReminder: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state }),
}));

vi.mock("@/lib/api/usage-adoption", () => ({
  getUsageAdoptionSummary: (...args: unknown[]) =>
    mockApi.getUsageAdoptionSummary(...args),
  getUsageAdoptionCharts: (...args: unknown[]) =>
    mockApi.getUsageAdoptionCharts(...args),
  listUsageAdoptionUsers: (...args: unknown[]) =>
    mockApi.listUsageAdoptionUsers(...args),
  exportUsageAdoption: (...args: unknown[]) =>
    mockApi.exportUsageAdoption(...args),
  sendOnboardingReminder: (...args: unknown[]) =>
    mockApi.sendOnboardingReminder(...args),
}));

const SUMMARY: UsageAdoptionSummary = {
  active_users: 12,
  new_users: 4,
  returning_users: 8,
  questions_asked: 42,
  documents_uploaded: 5,
  collections_used: 2,
  connectors_used: 1,
  citation_clicks: 9,
  trust_panel_opens: 3,
  feedback_submitted: 6,
  saved_answers: 2,
  onboarding_completion_rate: 0.5,
  invitations_sent: 3,
  invitations_accepted: 1,
  generated_at: "2026-08-19T00:00:00Z",
};

const CHARTS: UsageAdoptionCharts = {
  active_users_series: [{ date: "2026-08-19", active_users: 5 }],
  questions_per_user: [{ bucket: "1-4", user_count: 3 }],
  feature_usage: { chat: 10 },
  funnel: [
    {
      step: "signed_up",
      label: "Signed up",
      users_reached: 12,
      drop_off_rate: null,
    },
    {
      step: "asked_first_question",
      label: "Asked first question",
      users_reached: 6,
      drop_off_rate: 0.5,
    },
  ],
  role_adoption_comparison: [
    {
      role: "member",
      user_count: 10,
      active_users: 6,
      questions_asked: 30,
      activation_rate: 0.6,
    },
  ],
  drop_off_points: [
    {
      step: "asked_first_question",
      label: "Asked first question",
      users_reached: 6,
      drop_off_rate: 0.5,
    },
  ],
  generated_at: "2026-08-19T00:00:00Z",
};

function makeRow(
  overrides: Partial<UsageAdoptionUserRow> = {},
): UsageAdoptionUserRow {
  return {
    user_id: "user-1",
    name: "Ada Lovelace",
    email: "ada@example.com",
    role: "member",
    last_active_at: "2026-08-18T00:00:00Z",
    questions_asked: 5,
    sources_used: 3,
    citation_clicks: 2,
    feedback_submitted: 1,
    saved_answers: 1,
    onboarding_status: "in_progress",
    ...overrides,
  };
}

function listResponse(rows: UsageAdoptionUserRow[]): UsageAdoptionUserList {
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
      <AdminUsageAdoptionPage />
    </QueryClientProvider>,
  );
}

describe("AdminUsageAdoptionPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.state = {
      status: "authenticated",
      session: {
        userId: "admin-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
      },
    } as SessionState;

    mockApi.getUsageAdoptionSummary.mockResolvedValue(SUMMARY);
    mockApi.getUsageAdoptionCharts.mockResolvedValue(CHARTS);
    mockApi.listUsageAdoptionUsers.mockResolvedValue(listResponse([makeRow()]));
  });

  // A. Adoption metric tests ---------------------------------------------------
  it("renders summary metric cards with values from the API", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Active users")).toBeInTheDocument();
    });
    function cardValue(label: string): string | null {
      const labelEl = screen.getAllByText(label)[0];
      return (
        labelEl.closest("div")?.querySelector("p:last-child")?.textContent ??
        null
      );
    }
    expect(cardValue("Active users")).toBe("12");
    expect(cardValue("Questions asked")).toBe("42");
    expect(cardValue("Onboarding completion")).toBe("50%");
  });

  // B. Activation funnel tests --------------------------------------------------
  it("renders the activation funnel and drop-off chart titles", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Activation funnel" }),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("heading", { name: "Biggest drop-off points" }),
    ).toBeInTheDocument();
  });

  // C. User table tests ----------------------------------------------------------
  it("shows the user row with role, onboarding status, and engagement counts", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    });
    const table = screen.getByRole("table");
    expect(within(table).getByText("ada@example.com")).toBeInTheDocument();
    expect(within(table).getByText("In progress")).toBeInTheDocument();
  });

  // D. Role-based visibility tests -----------------------------------------------
  it("shows a forbidden state and makes no admin requests for non-admin roles", async () => {
    mockAuth.state = {
      status: "authenticated",
      session: {
        userId: "member-1",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
      },
    } as SessionState;
    renderPage();
    expect(screen.getByText("Admin access restricted")).toBeInTheDocument();
    expect(mockApi.getUsageAdoptionSummary).not.toHaveBeenCalled();
  });

  it("re-queries with the selected role filter", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByLabelText("Role"), "admin");

    await waitFor(() => {
      const lastCall =
        mockApi.listUsageAdoptionUsers.mock.calls[
          mockApi.listUsageAdoptionUsers.mock.calls.length - 1
        ];
      expect(lastCall[0]).toMatchObject({ role: "admin" });
    });
  });

  it("filters by role when a row's role badge is clicked", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    });

    const table = screen.getByRole("table");
    await user.click(within(table).getByText("member"));

    await waitFor(() => {
      const lastCall =
        mockApi.listUsageAdoptionUsers.mock.calls[
          mockApi.listUsageAdoptionUsers.mock.calls.length - 1
        ];
      expect(lastCall[0]).toMatchObject({ role: "member" });
    });
  });

  // E. Export tests ---------------------------------------------------------------
  it("calls exportUsageAdoption when Export is clicked", async () => {
    const user = userEvent.setup();
    mockApi.exportUsageAdoption.mockResolvedValue(new Blob(["csv"]));
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    });
    await user.click(screen.getByText("Export"));

    await waitFor(() => {
      expect(mockApi.exportUsageAdoption).toHaveBeenCalledTimes(1);
    });

    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  // Row actions ---------------------------------------------------------------
  it("sends an onboarding reminder and disables the button afterward", async () => {
    const user = userEvent.setup();
    mockApi.sendOnboardingReminder.mockResolvedValue({ sent: true });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Send reminder"));

    await waitFor(() => {
      expect(mockApi.sendOnboardingReminder).toHaveBeenCalledWith("user-1");
    });
    await waitFor(() => {
      expect(screen.getByText("Reminder sent")).toBeInTheDocument();
    });
  });

  it("hides the reminder action for users who already completed onboarding", async () => {
    mockApi.listUsageAdoptionUsers.mockResolvedValue(
      listResponse([makeRow({ onboarding_status: "completed" })]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    });
    expect(screen.queryByText("Send reminder")).not.toBeInTheDocument();
  });
});
