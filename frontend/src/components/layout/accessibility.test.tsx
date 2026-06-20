/**
 * F177 — Accessibility pass: automated checks for landmark structure,
 * skip navigation, aria-current, live regions, keyboard focus, and modal behavior.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/layout/AppShell";
import { APP_ROUTES, type AppNavigationItem } from "@/lib/app-routes";
import type { AuthenticatedSession } from "@/lib/auth-session";
import enMessages from "@/i18n/messages/en.json";
import * as chatApi from "@/lib/api/chat";
import * as documentsApi from "@/lib/api/documents";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const MEMBER_SESSION: AuthenticatedSession = {
  userId: "u-001",
  email: "member@example.com",
  role: "member",
  organizationId: "org-1",
  organizationName: "Acme",
};

const ADMIN_SESSION: AuthenticatedSession = {
  userId: "u-002",
  email: "admin@example.com",
  role: "admin",
  organizationId: "org-1",
  organizationName: "Acme",
};

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
  session = MEMBER_SESSION,
  activeRouteKey = "dashboard",
}: {
  session?: AuthenticatedSession;
  activeRouteKey?: AppNavigationItem["key"];
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const activeRoute =
    APP_ROUTES.find((r) => r.key === activeRouteKey) ?? APP_ROUTES[0];
  const navItems = buildNavItems(activeRoute.key, session);

  return render(
    <NextIntlClientProvider locale="en" messages={enMessages}>
      <QueryClientProvider client={queryClient}>
        <AppShell
          activeRoute={activeRoute}
          navItems={navItems}
          session={session}
          onSignOut={vi.fn()}
        >
          <div>Page content</div>
        </AppShell>
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(documentsApi, "listDocuments").mockResolvedValue({
    items: [],
    total: 0,
    limit: 80,
    offset: 0,
    sort_by: "updated_at",
    sort_order: "desc",
  } as Awaited<ReturnType<typeof documentsApi.listDocuments>>);
  vi.spyOn(chatApi, "listChatSessions").mockResolvedValue({
    items: [],
    total: 0,
    limit: 40,
    offset: 0,
  } as Awaited<ReturnType<typeof chatApi.listChatSessions>>);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Skip navigation link
// ---------------------------------------------------------------------------

describe("skip navigation link", () => {
  it("renders a skip link targeting #main-content", () => {
    renderShell();
    const skipLink = screen.getByRole("link", {
      name: /skip to main content/i,
    });
    expect(skipLink).toBeInTheDocument();
    expect(skipLink).toHaveAttribute("href", "#main-content");
  });

  it("main landmark has id='main-content' so the skip link target exists", () => {
    renderShell();
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "main-content");
  });

  it("main has tabIndex=-1 so it can receive programmatic focus", () => {
    renderShell();
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("tabindex", "-1");
  });
});

// ---------------------------------------------------------------------------
// Landmark structure
// ---------------------------------------------------------------------------

describe("landmark structure", () => {
  it("has exactly one main landmark", () => {
    renderShell();
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("desktop sidebar navigation has an accessible label", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: /primary navigation/i });
    expect(nav).toBeInTheDocument();
  });

  it("top bar is a header landmark", () => {
    renderShell();
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// aria-current on active navigation item
// ---------------------------------------------------------------------------

describe("aria-current page indicator", () => {
  it("active nav link has aria-current='page'", () => {
    renderShell({ activeRouteKey: "dashboard" });
    const dashboardLink = screen.getAllByRole("link", {
      name: /dashboard/i,
    })[0];
    expect(dashboardLink).toHaveAttribute("aria-current", "page");
  });

  it("inactive nav links do NOT have aria-current", () => {
    renderShell({ activeRouteKey: "dashboard" });
    // Find a non-active route that is accessible
    const documentsLinks = screen.getAllByRole("link", { name: /documents/i });
    // The first nav link that is not the active one
    const inactiveLink = documentsLinks.find(
      (el) => !el.getAttribute("aria-current"),
    );
    expect(inactiveLink).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// Disabled nav items are keyboard-reachable
// ---------------------------------------------------------------------------

describe("disabled navigation items", () => {
  it("disabled nav items are in the tab order with role=link aria-disabled", () => {
    // Member cannot access admin routes, so at least one item should be disabled
    renderShell({ session: MEMBER_SESSION });
    const disabledLinks = screen
      .queryAllByRole("link")
      .filter((el) => el.getAttribute("aria-disabled") === "true");

    // If member has disabled items, each should have tabindex=0
    for (const el of disabledLinks) {
      expect(el).toHaveAttribute("tabindex", "0");
    }
  });
});

// ---------------------------------------------------------------------------
// Route change announcer live region
// ---------------------------------------------------------------------------

describe("route change live region", () => {
  it("polite live region with id='a11y-announcer' exists", () => {
    renderShell();
    const region = document.getElementById("a11y-announcer");
    expect(region).toBeInTheDocument();
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveAttribute("role", "status");
  });

  it("assertive live region with id='a11y-announcer-assertive' exists", () => {
    renderShell();
    const region = document.getElementById("a11y-announcer-assertive");
    expect(region).toBeInTheDocument();
    expect(region).toHaveAttribute("aria-live", "assertive");
    expect(region).toHaveAttribute("role", "alert");
  });
});

// ---------------------------------------------------------------------------
// Notification button aria-label
// ---------------------------------------------------------------------------

describe("notifications button", () => {
  it("has an accessible label when no unread notifications", async () => {
    const notificationCenter = await import("@/lib/api/notification-center");
    vi.spyOn(notificationCenter, "getUnreadCount").mockResolvedValue({
      unread_count: 0,
    });

    renderShell();
    const btn = screen.getByRole("button", { name: /notifications/i });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-haspopup", "menu");
  });
});

// ---------------------------------------------------------------------------
// Mobile sidebar dialog
// ---------------------------------------------------------------------------

describe("mobile sidebar dialog", () => {
  it("mobile menu button is labelled and controls the sidebar", async () => {
    renderShell();
    const menuBtn = screen.getByRole("button", {
      name: /open navigation menu/i,
    });
    expect(menuBtn).toBeInTheDocument();
    expect(menuBtn).toHaveAttribute("aria-expanded", "false");
    expect(menuBtn).toHaveAttribute("aria-controls", "mobile-sidebar");
  });

  it("clicking menu button opens the sidebar dialog", async () => {
    const user = userEvent.setup();
    renderShell();
    const menuBtn = screen.getByRole("button", {
      name: /open navigation menu/i,
    });
    await user.click(menuBtn);
    const dialog = screen.getByRole("dialog", { name: /navigation menu/i });
    expect(dialog).toBeInTheDocument();
  });

  it("mobile sidebar close button has accessible label", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(
      screen.getByRole("button", { name: /open navigation menu/i }),
    );
    const closeBtn = screen.getByRole("button", {
      name: /close navigation menu/i,
    });
    expect(closeBtn).toBeInTheDocument();
  });

  it("pressing Escape closes the mobile sidebar", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(
      screen.getByRole("button", { name: /open navigation menu/i }),
    );
    expect(
      screen.getByRole("dialog", { name: /navigation menu/i }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: /navigation menu/i }),
      ).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Command menu dialog
// ---------------------------------------------------------------------------

describe("command menu dialog", () => {
  it("opens via keyboard shortcut and search input has accessible label", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.keyboard("{Meta>}k{/Meta}");
    const dialog = screen.getByRole("dialog", {
      name: /global search and quick navigation/i,
    });
    expect(dialog).toBeInTheDocument();
    const searchInput = within(dialog).getByRole("textbox", {
      name: /search across pages/i,
    });
    expect(searchInput).toBeInTheDocument();
  });

  it("pressing Escape closes the command menu", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.keyboard("{Meta>}k{/Meta}");
    expect(
      screen.getByRole("dialog", { name: /global search/i }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: /global search/i }),
      ).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Profile menu
// ---------------------------------------------------------------------------

describe("profile menu", () => {
  it("profile button has aria-haspopup and aria-expanded", () => {
    renderShell({ session: ADMIN_SESSION });
    const profileBtn = screen.getByRole("button", { name: /profile menu/i });
    expect(profileBtn).toHaveAttribute("aria-haspopup", "menu");
    expect(profileBtn).toHaveAttribute("aria-expanded", "false");
  });

  it("profile menu items have role=menuitem", async () => {
    const user = userEvent.setup();
    renderShell({ session: ADMIN_SESSION });
    await user.click(screen.getByRole("button", { name: /profile menu/i }));
    const menu = screen.getByRole("menu", { name: /profile menu panel/i });
    const items = within(menu).getAllByRole("menuitem");
    expect(items.length).toBeGreaterThan(0);
  });
});
