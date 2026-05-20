import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
} from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AppShell } from "@/components/layout/AppShell";
import { APP_ROUTES, type AppNavigationItem } from "@/lib/app-routes";
import type { AuthenticatedSession } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";

const server = setupServer(
  http.get(`${apiBaseUrl}/notifications`, async () => {
    return HttpResponse.json({ items: [] });
  }),
);

function buildNavItems(activeKey: string): AppNavigationItem[] {
  return APP_ROUTES.map((route) => ({
    ...route,
    isActive: route.key === activeKey,
    hidden: false,
    disabled: false,
    disabledReason: null,
  }));
}

function renderShell(session: AuthenticatedSession) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const activeRoute =
    APP_ROUTES.find((route) => route.key === "dashboard") ?? APP_ROUTES[0];
  const navItems = buildNavItems(activeRoute.key);

  return render(
    <QueryClientProvider client={queryClient}>
      <AppShell
        activeRoute={activeRoute}
        navItems={navItems}
        session={session}
        onSignOut={() => undefined}
      >
        <div>Page content</div>
      </AppShell>
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

describe("AppShell notifications menu states", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    process.env = {
      ...originalEnv,
      NEXT_PUBLIC_API_URL: apiBaseUrl,
      NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL: "/notifications",
      NEXT_PUBLIC_HELP_DOCS_URL: "",
      NEXT_PUBLIC_HELP_SUPPORT_URL: "",
      NEXT_PUBLIC_HELP_SHORTCUTS_URL: "",
      NEXT_PUBLIC_HELP_README_URL: "",
      NEXT_PUBLIC_SUPPORT_URL: "",
      NEXT_PUBLIC_SUPPORT_EMAIL: "",
    };
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  it("shows a clear empty state when notification feed has no items", async () => {
    renderShell({
      userId: "user-1",
      email: "member@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-1",
    });

    await userEvent.click(
      screen.getByRole("button", { name: "Notifications" }),
    );
    expect(
      await screen.findByText("No notifications right now."),
    ).toBeInTheDocument();
  });

  it("shows unavailable state when notification endpoint fails", async () => {
    server.use(
      http.get(`${apiBaseUrl}/notifications`, async () =>
        HttpResponse.json({ detail: "Service unavailable" }, { status: 503 }),
      ),
    );

    renderShell({
      userId: "user-2",
      email: "member@example.com",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-2",
    });

    await userEvent.click(
      screen.getByRole("button", { name: "Notifications" }),
    );
    expect(
      await screen.findByText(/temporarily unavailable/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /failed-job alerts will appear here when the backend feed is available/i,
      ),
    ).toBeInTheDocument();
  });
});
