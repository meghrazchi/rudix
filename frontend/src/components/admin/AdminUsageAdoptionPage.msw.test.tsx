import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AdminUsageAdoptionPage } from "@/components/admin/AdminUsageAdoptionPage";
import type { SessionState } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

let reminderCallCount = 0;
let usersRequestCount = 0;

const SUMMARY = {
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

const CHARTS = {
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
  ],
  role_adoption_comparison: [],
  drop_off_points: [],
  generated_at: "2026-08-19T00:00:00Z",
};

function usersResponse() {
  return {
    rows: [
      {
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
      },
    ],
    total: 1,
    page: 1,
    page_size: 25,
  };
}

const server = setupServer(
  http.get(`${apiBaseUrl}/auth/effective-permissions`, () =>
    HttpResponse.json({
      permissions: [],
      role: "admin",
      custom_role_id: null,
    }),
  ),
  http.get(`${apiBaseUrl}/admin/usage-adoption/summary`, () =>
    HttpResponse.json(SUMMARY),
  ),
  http.get(`${apiBaseUrl}/admin/usage-adoption/charts`, () =>
    HttpResponse.json(CHARTS),
  ),
  http.get(`${apiBaseUrl}/admin/usage-adoption/users`, () => {
    usersRequestCount += 1;
    return HttpResponse.json(usersResponse());
  }),
  http.post(
    `${apiBaseUrl}/admin/usage-adoption/users/user-1/onboarding-reminder`,
    () => {
      reminderCallCount += 1;
      return HttpResponse.json({ sent: true });
    },
  ),
);

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

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  reminderCallCount = 0;
  usersRequestCount = 0;
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;

  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "admin-user",
      email: "admin@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "access-token",
    },
  };
});

describe("AdminUsageAdoptionPage MSW", () => {
  it("loads summary, charts, and the user table over the network", async () => {
    renderPage();

    await screen.findByText("Usage & adoption");
    await screen.findByText("Active users");
    await screen.findByText("Ada Lovelace");
    expect(usersRequestCount).toBe(1);
  });

  it("sends an onboarding reminder over the network", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Ada Lovelace");
    await user.click(await screen.findByText("Send reminder"));

    await waitFor(() => {
      expect(reminderCallCount).toBe(1);
    });
    await screen.findByText("Reminder sent");
  });

  it("shows a forbidden state and makes no admin requests for non-admin roles", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "member-user",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "access-token",
      },
    };
    renderPage();

    await screen.findByText("Admin access restricted");
    expect(usersRequestCount).toBe(0);
  });
});
