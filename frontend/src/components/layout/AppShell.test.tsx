import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/layout/AppShell";
import { APP_ROUTES, type AppNavigationItem } from "@/lib/app-routes";
import type { AuthenticatedSession } from "@/lib/auth-session";

function buildNavItems(activeKey: string): AppNavigationItem[] {
  return APP_ROUTES.map((route) => ({
    ...route,
    isActive: route.key === activeKey,
    hidden: false,
    disabled: false,
    disabledReason: null,
  }));
}

function renderShell({
  session,
  onSignOut = vi.fn(),
}: {
  session: AuthenticatedSession;
  onSignOut?: () => void;
}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const activeRoute = APP_ROUTES.find((route) => route.key === "dashboard") ?? APP_ROUTES[0];
  const navItems = buildNavItems(activeRoute.key);

  return render(
    <QueryClientProvider client={queryClient}>
      <AppShell activeRoute={activeRoute} navItems={navItems} session={session} onSignOut={onSignOut}>
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
  });

  afterEach(() => {
    process.env = originalEnv;
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
    expect(screen.getByRole("menuitem", { name: "Settings" })).toHaveAttribute("href", "/settings");
    expect(screen.getByRole("menuitem", { name: "Admin usage" })).toHaveAttribute("href", "/admin");

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

    expect(await screen.findByRole("menuitem", { name: "Documentation" })).toHaveAttribute(
      "href",
      "https://docs.example.com",
    );
    expect(screen.getByRole("menuitem", { name: "Support" })).toHaveAttribute(
      "href",
      "https://support.example.com",
    );
    expect(screen.getByRole("menuitem", { name: "Keyboard shortcuts" })).toHaveAttribute(
      "href",
      "/shortcuts",
    );
    expect(screen.getByRole("menuitem", { name: "Project README" })).toHaveAttribute(
      "href",
      "https://github.com/example/project#readme",
    );
    expect(screen.queryByRole("link", { name: "Admin usage" })).not.toBeInTheDocument();
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
    const drawer = await screen.findByRole("dialog", { name: "Navigation menu" });
    expect(drawer).toBeInTheDocument();

    const closeButton = screen.getByRole("button", { name: "Close" });
    await waitFor(() => {
      expect(closeButton).toHaveFocus();
    });

    await userEvent.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Navigation menu" })).not.toBeInTheDocument();
    });
  });
});
