import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/layout/AppShell";
import { APP_ROUTES, type AppNavigationItem } from "@/lib/app-routes";
import type { AuthenticatedSession } from "@/lib/auth-session";
import * as chatApi from "@/lib/api/chat";
import * as documentsApi from "@/lib/api/documents";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function buildNavItems(
  activeKey: string,
  session: AuthenticatedSession,
): AppNavigationItem[] {
  return APP_ROUTES.map((route) => ({
    ...route,
    isActive: route.key === activeKey,
    hidden: false,
    disabled: !route.allowedRoles.includes(session.role),
    disabledReason: route.allowedRoles.includes(session.role)
      ? null
      : "insufficient_role",
  }));
}

function renderShell({
  session,
  onSignOut = vi.fn(),
  activeRouteKey = "dashboard",
}: {
  session: AuthenticatedSession;
  onSignOut?: () => void;
  activeRouteKey?: AppNavigationItem["key"];
}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const activeRoute =
    APP_ROUTES.find((route) => route.key === activeRouteKey) ?? APP_ROUTES[0];
  const navItems = buildNavItems(activeRoute.key, session);

  return render(
    <QueryClientProvider client={queryClient}>
      <AppShell
        activeRoute={activeRoute}
        navItems={navItems}
        session={session}
        onSignOut={onSignOut}
      >
        <div>Page content</div>
      </AppShell>
    </QueryClientProvider>,
  );
}

describe("AppShell top bar menus", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    process.env = {
      ...originalEnv,
      NEXT_PUBLIC_HELP_DOCS_URL: "https://docs.example.com",
      NEXT_PUBLIC_HELP_SUPPORT_URL: "https://support.example.com",
      NEXT_PUBLIC_HELP_SHORTCUTS_URL: "/shortcuts",
      NEXT_PUBLIC_HELP_README_URL: "https://github.com/example/project#readme",
      NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL: "",
    };
    vi.spyOn(documentsApi, "listDocuments").mockResolvedValue({
      items: [
        {
          document_id: "doc-1",
          filename: "Retention Policy.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 12,
          chunk_count: 40,
          error_message: null,
          error_details: null,
          created_at: "2026-05-20T10:00:00Z",
          updated_at: "2026-05-20T10:05:00Z",
        },
      ],
      total: 1,
      limit: 80,
      offset: 0,
      status: null,
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.spyOn(chatApi, "listChatSessions").mockResolvedValue({
      items: [
        {
          session_id: "session-1",
          title: "Retention policy questions",
          message_count: 6,
          created_at: "2026-05-20T09:00:00Z",
          updated_at: "2026-05-20T09:30:00Z",
        },
      ],
      total: 1,
      limit: 40,
      offset: 0,
    });
  });

  afterEach(() => {
    process.env = originalEnv;
    vi.restoreAllMocks();
  });

  it("shows profile context and runs logout action from profile menu", async () => {
    const onSignOut = vi.fn();
    renderShell({
      onSignOut,
      session: {
        userId: "user-1",
        email: "owner@example.com",
        role: "owner",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    });

    const profileButton = screen.getByRole("button", { name: "Profile menu" });
    profileButton.focus();
    await userEvent.keyboard("{Enter}");

    expect(await screen.findByText("User profile")).toBeInTheDocument();
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    expect(screen.getByText("User ID: user-1")).toBeInTheDocument();
    expect(screen.getByText("Organization: Org One")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Settings" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(
      screen.getByRole("menuitem", { name: "Admin usage" }),
    ).toHaveAttribute("href", "/admin");

    await userEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(onSignOut).toHaveBeenCalledTimes(1);
  });

  it("shows configured help menu links", async () => {
    renderShell({
      session: {
        userId: "user-2",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-2",
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "Help" }));

    expect(
      await screen.findByRole("menuitem", { name: "Documentation" }),
    ).toHaveAttribute("href", "https://docs.example.com");
    expect(screen.getByRole("menuitem", { name: "Support" })).toHaveAttribute(
      "href",
      "https://support.example.com",
    );
    expect(
      screen.getByRole("menuitem", { name: "Keyboard shortcuts" }),
    ).toHaveAttribute("href", "/shortcuts");
    expect(
      screen.getByRole("menuitem", { name: "Project README" }),
    ).toHaveAttribute("href", "https://github.com/example/project#readme");
    expect(
      screen.queryByRole("link", { name: "Admin usage" }),
    ).not.toBeInTheDocument();
  });

  it("opens and closes the mobile navigation drawer with keyboard support", async () => {
    renderShell({
      session: {
        userId: "user-3",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-3",
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "Menu" }));
    const drawer = await screen.findByRole("dialog", {
      name: "Navigation menu",
    });
    expect(drawer).toBeInTheDocument();

    const closeButton = screen.getByRole("button", { name: "Close" });
    await waitFor(() => {
      expect(closeButton).toHaveFocus();
    });

    await userEvent.keyboard("{Escape}");
    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Navigation menu" }),
      ).not.toBeInTheDocument();
    });
  });

  it("opens command menu via keyboard shortcut and renders quick results", async () => {
    renderShell({
      session: {
        userId: "user-4",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-4",
      },
    });

    fireEvent.keyDown(document, { key: "k", ctrlKey: true });

    expect(
      await screen.findByRole("dialog", {
        name: "Global search and quick navigation",
      }),
    ).toBeInTheDocument();

    expect(
      await screen.findByRole("link", { name: /Dashboard/i }),
    ).toHaveAttribute("href", "/dashboard");
    expect(
      screen.getByRole("link", { name: /Retention Policy\.pdf/i }),
    ).toHaveAttribute("href", "/documents/doc-1");
    expect(
      screen.getByRole("link", { name: /Retention policy questions/i }),
    ).toHaveAttribute("href", "/chat?session_id=session-1");
  });

  it("hides admin quick navigation results for non-admin users", async () => {
    renderShell({
      session: {
        userId: "user-5",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-5",
      },
    });

    await userEvent.click(
      screen.getByRole("button", { name: "Open global search" }),
    );
    await userEvent.type(
      screen.getByRole("textbox", {
        name: "Search across pages, documents, and chats",
      }),
      "admin",
    );

    expect(
      screen.queryByRole("link", { name: /^Admin$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "No matching results. Try a filename, status, chat title, or page name.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps the chat route from scrolling the app main container", () => {
    renderShell({
      activeRouteKey: "chat",
      session: {
        userId: "user-6",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-6",
      },
    });

    expect(screen.getByRole("main")).toHaveClass("overflow-hidden");
    expect(screen.getByRole("main")).not.toHaveClass("overflow-auto");
  });
});
