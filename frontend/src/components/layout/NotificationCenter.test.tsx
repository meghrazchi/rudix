import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationCenter } from "@/components/layout/NotificationCenter";
import * as notifApi from "@/lib/api/notification-center";
import type { NotificationListResponse } from "@/lib/api/notification-center";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api/notification-center", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/api/notification-center")>();
  return {
    ...original,
    listNotifications: vi.fn(),
    getUnreadCount: vi.fn(),
    markNotificationRead: vi.fn(),
    markNotificationUnread: vi.fn(),
    markAllNotificationsRead: vi.fn(),
  };
});

function buildNotification(
  overrides: Partial<notifApi.NotificationResponse> = {},
): notifApi.NotificationResponse {
  return {
    notification_id: "notif-1",
    event_type: "upload_indexed",
    severity: "info",
    title: "Document indexed",
    message: "5 pages, 12 chunks ready for search.",
    href: "/documents?highlight=doc-1",
    source_id: "doc-1",
    is_read: false,
    created_at: new Date(Date.now() - 60_000).toISOString(),
    ...overrides,
  };
}

function buildResponse(
  items: notifApi.NotificationResponse[],
  unread_count?: number,
): NotificationListResponse {
  return {
    items,
    total: items.length,
    limit: 20,
    offset: 0,
    unread_count: unread_count ?? items.filter((n) => !n.is_read).length,
  };
}

function renderCenter({
  isOpen = true,
  onNavigate = vi.fn(),
}: {
  isOpen?: boolean;
  onNavigate?: () => void;
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <NotificationCenter isOpen={isOpen} onNavigate={onNavigate} />
    </QueryClientProvider>,
  );
}

describe("NotificationCenter", () => {
  beforeEach(() => {
    vi.mocked(notifApi.getUnreadCount).mockResolvedValue({ unread_count: 0 });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe("empty state", () => {
    it("shows empty message when there are no notifications", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([]),
      );

      renderCenter();

      expect(
        await screen.findByText(/all caught up/),
      ).toBeInTheDocument();
    });
  });

  describe("feed states", () => {
    it("shows loading state while fetching", async () => {
      vi.mocked(notifApi.listNotifications).mockImplementation(
        () => new Promise(() => {}),
      );

      renderCenter();

      expect(screen.getByText(/Loading notifications/)).toBeInTheDocument();
    });

    it("renders notification title and message", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([buildNotification()]),
      );

      renderCenter();

      expect(await screen.findByText("Document indexed")).toBeInTheDocument();
      expect(
        screen.getByText("5 pages, 12 chunks ready for search."),
      ).toBeInTheDocument();
    });

    it("shows unread count badge in header", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse(
          [
            buildNotification({ notification_id: "n1", title: "First" }),
            buildNotification({ notification_id: "n2", title: "Second" }),
          ],
          2,
        ),
      );

      renderCenter();

      await screen.findByText("First");
      const badges = screen.getAllByText("2");
      expect(badges.length).toBeGreaterThan(0);
    });

    it("does not show 'Mark all read' when all notifications are read", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([buildNotification({ is_read: true })], 0),
      );

      renderCenter();

      await screen.findByText("Document indexed");
      expect(
        screen.queryByRole("button", { name: "Mark all read" }),
      ).not.toBeInTheDocument();
    });

    it("shows error state on fetch failure with retry button", async () => {
      vi.mocked(notifApi.listNotifications).mockRejectedValue(
        new Error("Network error"),
      );

      renderCenter();

      expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    });

    it("renders notification href as a menuitem link", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([buildNotification({ href: "/documents?highlight=doc-1" })]),
      );

      renderCenter();

      await screen.findByText("Document indexed");
      const link = screen.getByRole("menuitem", { name: /Document indexed/ });
      expect(link).toHaveAttribute("href", "/documents?highlight=doc-1");
    });

    it("shows upload_failed notification with error severity badge", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([
          buildNotification({
            event_type: "upload_failed",
            severity: "error",
            title: "Document processing failed",
          }),
        ]),
      );

      renderCenter();

      await screen.findByText("Document processing failed");
      const badges = screen.getAllByText("error");
      expect(badges.some((b) => b.className.includes("rose"))).toBe(true);
    });

    it("does not render when isOpen is false", () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([buildNotification()]),
      );

      renderCenter({ isOpen: false });

      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    });
  });

  describe("mark read / unread", () => {
    it("calls markNotificationRead when 'Mark read' button is clicked", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([buildNotification()]),
      );
      vi.mocked(notifApi.markNotificationRead).mockResolvedValue({
        notification_id: "notif-1",
        is_read: true,
      });

      const user = userEvent.setup();
      renderCenter();

      await screen.findByText("Document indexed");
      await user.click(screen.getByRole("button", { name: "Mark read" }));

      await waitFor(() => {
        expect(notifApi.markNotificationRead).toHaveBeenCalledWith(
          "notif-1",
          expect.anything(),
        );
      });
    });

    it("calls markNotificationUnread when 'Mark unread' button is clicked", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([buildNotification({ is_read: true })], 0),
      );
      vi.mocked(notifApi.markNotificationUnread).mockResolvedValue({
        notification_id: "notif-1",
        is_read: false,
      });

      const user = userEvent.setup();
      renderCenter();

      await screen.findByText("Document indexed");
      await user.click(screen.getByRole("button", { name: "Mark unread" }));

      await waitFor(() => {
        expect(notifApi.markNotificationUnread).toHaveBeenCalledWith(
          "notif-1",
          expect.anything(),
        );
      });
    });

    it("calls markAllNotificationsRead when 'Mark all read' is clicked", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse(
          [
            buildNotification({ notification_id: "n1", title: "First" }),
            buildNotification({ notification_id: "n2", title: "Second" }),
          ],
          2,
        ),
      );
      vi.mocked(notifApi.markAllNotificationsRead).mockResolvedValue({
        marked_count: 2,
      });

      const user = userEvent.setup();
      renderCenter();

      await screen.findByText("First");
      await user.click(screen.getByRole("button", { name: "Mark all read" }));

      await waitFor(() => {
        expect(notifApi.markAllNotificationsRead).toHaveBeenCalledTimes(1);
      });
    });
  });

  describe("preferences placeholder", () => {
    it("opens preferences panel when settings button is clicked", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([]),
      );

      const user = userEvent.setup();
      renderCenter();

      await screen.findByText(/all caught up/);
      await user.click(
        screen.getByRole("button", { name: "Notification preferences" }),
      );

      expect(
        screen.getByText("Notification preferences"),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Per-category preferences are coming soon/),
      ).toBeInTheDocument();
    });

    it("closes preferences panel when close button is clicked", async () => {
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([]),
      );

      const user = userEvent.setup();
      renderCenter();

      await screen.findByText(/all caught up/);
      await user.click(
        screen.getByRole("button", { name: "Notification preferences" }),
      );
      expect(
        screen.getByText("Notification preferences"),
      ).toBeInTheDocument();

      await user.click(
        screen.getByRole("button", { name: "Close preferences" }),
      );
      await waitFor(() => {
        expect(
          screen.queryByText("Per-category preferences are coming soon"),
        ).not.toBeInTheDocument();
      });
    });
  });

  describe("onNavigate callback", () => {
    it("calls onNavigate when a linked notification is clicked", async () => {
      const onNavigate = vi.fn();
      vi.mocked(notifApi.listNotifications).mockResolvedValue(
        buildResponse([buildNotification({ href: "/documents" })]),
      );

      const user = userEvent.setup();
      renderCenter({ onNavigate });

      await screen.findByText("Document indexed");
      await user.click(
        screen.getByRole("menuitem", { name: /Document indexed/ }),
      );

      expect(onNavigate).toHaveBeenCalledTimes(1);
    });
  });
});
