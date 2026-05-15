import { getSupportAction } from "@/lib/forbidden";
import type { AppRole } from "@/lib/auth-session";
import type { TopBarNotification } from "@/lib/api/notifications";

export type HelpMenuItem = {
  id: "docs" | "support" | "shortcuts" | "readme";
  label: string;
  href: string;
};

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function isAdminLikeRole(role: AppRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

export function resolveHelpMenuItems(): HelpMenuItem[] {
  const docsUrl = trimToNull(process.env.NEXT_PUBLIC_HELP_DOCS_URL);
  const shortcutsUrl = trimToNull(process.env.NEXT_PUBLIC_HELP_SHORTCUTS_URL);
  const readmeUrl = trimToNull(process.env.NEXT_PUBLIC_HELP_README_URL);
  const supportOverride = trimToNull(process.env.NEXT_PUBLIC_HELP_SUPPORT_URL);
  const supportAction = supportOverride
    ? { href: supportOverride, label: "Support" }
    : getSupportAction();

  const items: HelpMenuItem[] = [];

  if (docsUrl) {
    items.push({ id: "docs", label: "Documentation", href: docsUrl });
  }

  if (supportAction?.href) {
    items.push({ id: "support", label: supportAction.label, href: supportAction.href });
  }

  if (shortcutsUrl) {
    items.push({ id: "shortcuts", label: "Keyboard shortcuts", href: shortcutsUrl });
  }

  if (readmeUrl) {
    items.push({ id: "readme", label: "Project README", href: readmeUrl });
  }

  return items;
}

export function resolveNotificationsEndpoint(): string | null {
  return trimToNull(process.env.NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL);
}

export function filterNotificationsByRole(
  notifications: TopBarNotification[],
  role: AppRole,
): TopBarNotification[] {
  return notifications.filter((notification) => {
    if (!notification.allowed_roles || notification.allowed_roles.length === 0) {
      return true;
    }
    return notification.allowed_roles.includes(role);
  });
}

export function isExternalHref(href: string): boolean {
  return /^https?:\/\//i.test(href) || /^mailto:/i.test(href);
}
