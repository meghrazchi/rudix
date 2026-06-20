import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminStatusPage } from "@/components/admin/AdminStatusPage";
import { ApiClientError } from "@/lib/api/errors";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getStatusSnapshot: vi.fn(),
  listIncidents: vi.fn(),
  getIncident: vi.fn(),
  createIncident: vi.fn(),
  updateIncident: vi.fn(),
  addIncidentNote: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/incidents", () => ({
  getStatusSnapshot: () => mockApi.getStatusSnapshot(),
  listIncidents: (query?: unknown) => mockApi.listIncidents(query),
  getIncident: (id: string) => mockApi.getIncident(id),
  createIncident: (body: unknown) => mockApi.createIncident(body),
  updateIncident: (id: string, body: unknown) =>
    mockApi.updateIncident(id, body),
  addIncidentNote: (id: string, body: unknown) =>
    mockApi.addIncidentNote(id, body),
}));

const makeAdminSession = (): SessionState => ({
  status: "authenticated",
  session: {
    userId: "user-1",
    email: "admin@example.com",
    organizationId: "org-1",
    organizationName: "Org One",
    role: "admin",
  },
});

const emptySnapshot = {
  organization_id: "org-1",
  generated_at: new Date().toISOString(),
  active_incidents: [],
  recently_resolved: [],
  open_failed_job_count: 0,
  banner: {
    has_active_incident: false,
    has_active_maintenance: false,
    active_incident_count: 0,
    banner_message: null,
    highest_severity: null,
  },
};

const emptyList = { items: [], total: 0, page: 1, page_size: 25 };

const sampleIncident = {
  id: "inc-1",
  organization_id: "org-1",
  title: "Chat is slow",
  status: "investigating",
  severity: "high",
  affected_services: ["chat"],
  message: "We are investigating latency issues.",
  is_public: true,
  started_at: new Date().toISOString(),
  resolved_at: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminStatusPage />
    </QueryClientProvider>,
  );
}

describe("AdminStatusPage", () => {
  beforeEach(() => {
    for (const fn of Object.values(mockApi)) fn.mockReset();
    mockApi.getStatusSnapshot.mockResolvedValue(emptySnapshot);
    mockApi.listIncidents.mockResolvedValue(emptyList);
  });

  describe("permission guard", () => {
    it("shows forbidden state for unauthenticated users", () => {
      mockState.authState = {
        status: "unauthenticated",
        session: null,
      } as SessionState;
      renderPage();
      expect(screen.getByText(/admin access restricted/i)).toBeInTheDocument();
    });

    it("shows forbidden state for member role", () => {
      mockState.authState = {
        status: "authenticated",
        session: {
          userId: "u",
          email: "m@x.com",
          organizationId: "o",
          organizationName: "Org One",
          role: "member",
        },
      } as SessionState;
      renderPage();
      expect(screen.getByText(/admin access restricted/i)).toBeInTheDocument();
    });
  });

  describe("normal state", () => {
    beforeEach(() => {
      mockState.authState = makeAdminSession();
    });

    it("renders heading and refresh button", async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText(/system status/i)).toBeInTheDocument();
      });
      expect(
        screen.getByRole("button", { name: /refresh/i }),
      ).toBeInTheDocument();
    });

    it("renders new incident button", async () => {
      renderPage();
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /new incident/i }),
        ).toBeInTheDocument();
      });
    });

    it("shows empty state when no incidents", async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText(/no incidents match/i)).toBeInTheDocument();
      });
    });

    it("renders incident rows from list response", async () => {
      mockApi.listIncidents.mockResolvedValue({
        items: [sampleIncident],
        total: 1,
        page: 1,
        page_size: 25,
      });
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Chat is slow")).toBeInTheDocument();
      });
    });

    it("renders metric cards from snapshot", async () => {
      mockApi.getStatusSnapshot.mockResolvedValue({
        ...emptySnapshot,
        active_incidents: [sampleIncident],
        banner: {
          has_active_incident: true,
          has_active_maintenance: false,
          active_incident_count: 1,
          banner_message: null,
          highest_severity: "high",
        },
      });
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Degraded")).toBeInTheDocument();
      });
    });
  });

  describe("create incident modal", () => {
    beforeEach(() => {
      mockState.authState = makeAdminSession();
    });

    it("opens modal when new incident button clicked", async () => {
      renderPage();
      await waitFor(() =>
        screen.getByRole("button", { name: /new incident/i }),
      );
      await userEvent.click(
        screen.getByRole("button", { name: /new incident/i }),
      );
      expect(
        screen.getByText(/new incident/i, { selector: "h2" }),
      ).toBeInTheDocument();
    });

    it("closes modal when cancel is clicked", async () => {
      renderPage();
      await waitFor(() =>
        screen.getByRole("button", { name: /new incident/i }),
      );
      await userEvent.click(
        screen.getByRole("button", { name: /new incident/i }),
      );
      await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
      expect(
        screen.queryByText(/new incident/i, { selector: "h2" }),
      ).not.toBeInTheDocument();
    });

    it("submit button disabled when title is empty", async () => {
      renderPage();
      await waitFor(() =>
        screen.getByRole("button", { name: /new incident/i }),
      );
      await userEvent.click(
        screen.getByRole("button", { name: /new incident/i }),
      );
      expect(
        screen.getByRole("button", { name: /create incident/i }),
      ).toBeDisabled();
    });
  });

  describe("error state", () => {
    beforeEach(() => {
      mockState.authState = makeAdminSession();
    });

    it("shows error state when list query fails", async () => {
      mockApi.listIncidents.mockRejectedValue(
        new ApiClientError({
          status: 500,
          code: "server_error",
          message: "Server error",
          details: {},
          requestId: null,
          userMessage: "Server error",
          actionMessage: "Please try again.",
          retryable: false,
        }),
      );
      renderPage();
      await waitFor(() => {
        expect(screen.getByText(/server error/i)).toBeInTheDocument();
      });
    });
  });
});
