import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  filterNotificationsByRole,
  resolveHelpMenuItems,
  resolveNotificationsEndpoint,
} from "@/lib/top-bar";
import type { TopBarNotification } from "@/lib/api/notifications";

describe("top-bar helpers", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  it("builds help menu links from configured environment values", () => {
    process.env.NEXT_PUBLIC_HELP_DOCS_URL = "https://docs.example.com";
    process.env.NEXT_PUBLIC_HELP_CHANGELOG_URL =
      "https://changelog.example.com";
    process.env.NEXT_PUBLIC_HELP_SHORTCUTS_URL = "/shortcuts";
    process.env.NEXT_PUBLIC_HELP_README_URL =
      "https://github.com/example/project#readme";
    process.env.NEXT_PUBLIC_HELP_SUPPORT_URL = "https://support.example.com";
    process.env.NEXT_PUBLIC_SUPPORT_URL = "";
    process.env.NEXT_PUBLIC_SUPPORT_EMAIL = "";

    const items = resolveHelpMenuItems();
    expect(items).toEqual([
      { id: "docs", label: "Documentation", href: "https://docs.example.com" },
      {
        id: "changelog",
        label: "Changelog",
        href: "https://changelog.example.com",
      },
      { id: "support", label: "Support", href: "https://support.example.com" },
      { id: "shortcuts", label: "Keyboard shortcuts", href: "/shortcuts" },
      {
        id: "readme",
        label: "Project README",
        href: "https://github.com/example/project#readme",
      },
    ]);
  });

  it("falls back to support url/email when help support override is not set", () => {
    process.env.NEXT_PUBLIC_HELP_DOCS_URL = "";
    process.env.NEXT_PUBLIC_HELP_CHANGELOG_URL = "";
    process.env.NEXT_PUBLIC_HELP_SHORTCUTS_URL = "";
    process.env.NEXT_PUBLIC_HELP_README_URL = "";
    process.env.NEXT_PUBLIC_HELP_SUPPORT_URL = "";
    process.env.NEXT_PUBLIC_SUPPORT_URL = "";
    process.env.NEXT_PUBLIC_SUPPORT_EMAIL = "help@example.com";

    const items = resolveHelpMenuItems();
    expect(items).toEqual([
      { id: "changelog", label: "Changelog", href: "/changelog" },
      {
        id: "support",
        label: "Email support",
        href: "mailto:help@example.com",
      },
    ]);
  });

  it("resolves notifications endpoint from environment", () => {
    process.env.NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL = " /notifications/feed ";
    expect(resolveNotificationsEndpoint()).toBe("/notifications/feed");

    process.env.NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL = " ";
    expect(resolveNotificationsEndpoint()).toBeNull();
  });

  it("filters notifications by role when allowed_roles are present", () => {
    const notifications: TopBarNotification[] = [
      {
        id: "n-1",
        title: "A",
        message: null,
        created_at: null,
        severity: "info" as const,
        kind: "generic" as const,
        href: null,
      },
      {
        id: "n-2",
        title: "B",
        message: null,
        created_at: null,
        severity: "warning" as const,
        kind: "usage_warning" as const,
        href: null,
        allowed_roles: ["owner", "admin"],
      },
    ];

    expect(
      filterNotificationsByRole(notifications, "member").map((item) => item.id),
    ).toEqual(["n-1"]);
    expect(
      filterNotificationsByRole(notifications, "admin").map((item) => item.id),
    ).toEqual(["n-1", "n-2"]);
  });
});
