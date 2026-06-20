import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";

import { HelpCenterDrawer } from "@/components/help/HelpCenterDrawer";
import type { AuthenticatedSession } from "@/lib/auth-session";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const MESSAGES = {
  help: {
    helpCenterTitle: "Help Center",
    close: "Close",
    searchPlaceholder: "Search help topics…",
    searchAriaLabel: "Search help topics",
    topicsLabel: "Topics",
    resourcesLabel: "Resources",
    supportLabel: "Support",
    noArticles: "No topics matched your search.",
    openHelpForTopic: "Open help for this topic",
    contactSupport: "Contact support",
    includeDiagnosticInfo: "Include diagnostic info with support request",
    diagnosticInfoNote:
      "Includes your org ID prefix, role, and browser. No private data or tokens.",
    copyDiagnosticInfo: "Copy diagnostic info",
    copied: "Copied!",
    keyboardShortcutsTitle: "Keyboard shortcuts",
    shortcuts: {
      search: "Open global search",
      openShortcuts: "Open keyboard shortcuts",
      submitMessage: "Send chat message",
      closeOverlay: "Close overlay or menu",
      focusNext: "Move focus forward",
      focusPrevious: "Move focus backward",
      groups: {
        navigation: "Navigation",
        chat: "Chat",
        overlays: "Overlays & Focus",
      },
    },
    articles: {
      upload: { title: "Upload documents", description: "Add PDFs and files." },
      chat: {
        title: "Ask questions",
        description: "Get grounded answers.",
      },
      citations: {
        title: "Verify citations",
        description: "Preview source passages.",
      },
      collections: {
        title: "Manage collections",
        description: "Group documents.",
      },
      evaluations: {
        title: "Run evaluations",
        description: "Measure quality.",
      },
      pipeline: { title: "RAG pipeline", description: "Inspect stages." },
      connectors: {
        title: "Manage connectors",
        description: "Sync external content.",
      },
      agents: {
        title: "Agent workspace",
        description: "View agent runs.",
      },
      users: {
        title: "Manage users",
        description: "Invite and manage team.",
      },
    },
  },
};

const SESSION: AuthenticatedSession = {
  userId: "user-1",
  email: "user@example.com",
  role: "member",
  organizationId: "org-abcdef12",
  organizationName: "Test Org",
  accessToken: "token-1",
};

function renderDrawer({
  isOpen = true,
  onClose = vi.fn(),
  onOpenShortcuts = vi.fn(),
  initialTopic = null,
}: {
  isOpen?: boolean;
  onClose?: () => void;
  onOpenShortcuts?: () => void;
  initialTopic?: Parameters<typeof HelpCenterDrawer>[0]["initialTopic"];
} = {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={MESSAGES}>
      <HelpCenterDrawer
        isOpen={isOpen}
        onClose={onClose}
        onOpenShortcuts={onOpenShortcuts}
        initialTopic={initialTopic}
        session={SESSION}
      />
    </NextIntlClientProvider>,
  );
}

describe("HelpCenterDrawer", () => {
  it("renders nothing when closed", () => {
    renderDrawer({ isOpen: false });
    expect(
      screen.queryByRole("dialog", { name: "Help Center" }),
    ).not.toBeInTheDocument();
  });

  it("renders drawer with search input when open", () => {
    renderDrawer();

    expect(
      screen.getByRole("dialog", { name: "Help Center" }),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Search help topics…"),
    ).toBeInTheDocument();
  });

  it("shows all articles by default", () => {
    renderDrawer();

    expect(screen.getByText("Upload documents")).toBeInTheDocument();
    expect(screen.getByText("Ask questions")).toBeInTheDocument();
    expect(screen.getByText("Verify citations")).toBeInTheDocument();
    expect(screen.getByText("Run evaluations")).toBeInTheDocument();
    expect(screen.getByText("RAG pipeline")).toBeInTheDocument();
    expect(screen.getByText("Manage connectors")).toBeInTheDocument();
    expect(screen.getByText("Agent workspace")).toBeInTheDocument();
    expect(screen.getByText("Manage users")).toBeInTheDocument();
  });

  it("filters articles by search query", async () => {
    renderDrawer();

    const search = screen.getByPlaceholderText("Search help topics…");
    await userEvent.type(search, "connector");

    expect(screen.getByText("Manage connectors")).toBeInTheDocument();
    expect(screen.queryByText("Upload documents")).not.toBeInTheDocument();
    expect(screen.queryByText("Run evaluations")).not.toBeInTheDocument();
  });

  it("shows no-results message when search has no matches", async () => {
    renderDrawer();

    const search = screen.getByPlaceholderText("Search help topics…");
    await userEvent.type(search, "xyznotarealquery");

    expect(
      screen.getByText("No topics matched your search."),
    ).toBeInTheDocument();
  });

  it("highlights the initialTopic article when no query is active", () => {
    renderDrawer({ initialTopic: "run-evaluations" });

    const article = screen.getByText("Run evaluations").closest("a");
    expect(article).toHaveClass("border-[#b8b0f5]");
  });

  it("calls onClose when backdrop is clicked", async () => {
    const onClose = vi.fn();
    const { container } = renderDrawer({ onClose });

    const backdrop = container.firstChild as HTMLElement;
    await userEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when Esc button is clicked", async () => {
    const onClose = vi.fn();
    renderDrawer({ onClose });

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onOpenShortcuts when keyboard shortcuts button is clicked", async () => {
    const onClose = vi.fn();
    const onOpenShortcuts = vi.fn();
    renderDrawer({ onClose, onOpenShortcuts });

    await userEvent.click(
      screen.getByRole("button", { name: /Keyboard shortcuts/i }),
    );
    expect(onOpenShortcuts).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows diagnostic info section when consent is toggled", async () => {
    renderDrawer();

    const toggle = screen.getByRole("checkbox", {
      name: "Include diagnostic info with support request",
    });
    expect(
      screen.queryByRole("button", { name: "Copy diagnostic info" }),
    ).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(
      screen.getByRole("button", { name: "Copy diagnostic info" }),
    ).toBeInTheDocument();
    // Should display masked org ID
    expect(screen.getByText(/org-abcd/)).toBeInTheDocument();
    expect(screen.getByText(/role:member/)).toBeInTheDocument();
  });

  it("does not expose full org ID in diagnostic info", async () => {
    renderDrawer();

    await userEvent.click(
      screen.getByRole("checkbox", {
        name: "Include diagnostic info with support request",
      }),
    );

    // Only the first 8 chars are shown, not the full ID
    expect(screen.queryByText(/org-abcdef12/)).not.toBeInTheDocument();
  });

  it("has aria-modal on the dialog element", () => {
    renderDrawer();

    const drawer = screen.getByRole("dialog", { name: "Help Center" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
  });
});
