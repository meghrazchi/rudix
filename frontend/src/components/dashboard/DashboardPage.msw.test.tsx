import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { DashboardPage } from "@/components/dashboard/DashboardPage";
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

const server = setupServer(
  http.get(`${apiBaseUrl}/documents`, async () => {
    return HttpResponse.json({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: null,
      sort_by: "updated_at",
      sort_order: "desc",
    });
  }),
  http.get(`${apiBaseUrl}/chat/sessions`, async () => {
    return HttpResponse.json({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
    });
  }),
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
      <DashboardPage />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  process.env.NEXT_PUBLIC_DASHBOARD_ENABLE_ADMIN_USAGE = "false";
  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "u-1",
      email: "member@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-1",
    },
  };
});

describe("DashboardPage MSW states", () => {
  it("shows loading state while dashboard queries are in flight", async () => {
    server.use(
      http.get(`${apiBaseUrl}/documents`, async () => {
        await delay(200);
        return HttpResponse.json({
          items: [],
          total: 0,
          limit: 200,
          offset: 0,
          status: null,
          sort_by: "updated_at",
          sort_order: "desc",
        });
      }),
      http.get(`${apiBaseUrl}/chat/sessions`, async () => {
        await delay(200);
        return HttpResponse.json({
          items: [],
          total: 0,
          limit: 200,
          offset: 0,
        });
      }),
    );

    renderPage();
    expect(await screen.findAllByText("Loading...")).not.toHaveLength(0);
  });

  it("shows empty state when no documents and chats exist", async () => {
    renderPage();
    expect(await screen.findByText("No activity yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload documents" })).toHaveAttribute(
      "href",
      "/documents",
    );
  });

  it("shows recent activity empty state when no activity data exists", async () => {
    renderPage();
    expect(await screen.findByText("Recent activity")).toBeInTheDocument();
    expect(await screen.findByText("No recent activity available yet.")).toBeInTheDocument();
  });

  it("shows actionable error state with retry control", async () => {
    server.use(
      http.get(`${apiBaseUrl}/documents`, async () =>
        HttpResponse.json({ detail: "Server failure" }, { status: 500 })),
    );

    renderPage();

    const errorStates = await screen.findAllByText("Unable to load");
    expect(errorStates.length).toBeGreaterThan(0);
    const retryButtons = screen.getAllByRole("button", { name: "Retry" });
    expect(retryButtons.length).toBeGreaterThan(0);

    await userEvent.click(retryButtons[0]);
  });
});
