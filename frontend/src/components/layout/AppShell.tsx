"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getTopBarNotifications } from "@/lib/api/notifications";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import type { AppNavigationItem, AppRouteMeta } from "@/lib/app-routes";
import type { AuthenticatedSession } from "@/lib/auth-session";
import {
  filterNotificationsByRole,
  isAdminLikeRole,
  isExternalHref,
  resolveHelpMenuItems,
  resolveNotificationsEndpoint,
} from "@/lib/top-bar";

const BRAND_LOGO_SRC = "/brand/rudix-mark.svg";

type AppShellProps = {
  activeRoute: AppRouteMeta;
  navItems: AppNavigationItem[];
  session: AuthenticatedSession;
  onSignOut: () => void;
  children: ReactNode;
};

function roleLabel(role: AuthenticatedSession["role"]): string {
  if (role === "owner") {
    return "Owner";
  }
  if (role === "admin") {
    return "Admin";
  }
  if (role === "member") {
    return "Member";
  }
  return "Viewer";
}

function routeDisabledReason(reason: AppNavigationItem["disabledReason"]): string {
  if (reason === "insufficient_role") {
    return "Insufficient role";
  }
  if (reason === "unauthenticated") {
    return "Authentication required";
  }
  return "Unavailable";
}

function NavigationIcon({ routeKey }: { routeKey: AppNavigationItem["key"] }) {
  const sharedProps = {
    className: "h-4 w-4 shrink-0",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.9,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  if (routeKey === "dashboard") {
    return (
      <svg {...sharedProps}>
        <rect x="3.8" y="3.8" width="6.6" height="6.6" rx="1.2" />
        <rect x="13.6" y="3.8" width="6.6" height="6.6" rx="1.2" />
        <rect x="3.8" y="13.6" width="6.6" height="6.6" rx="1.2" />
        <rect x="13.6" y="13.6" width="6.6" height="6.6" rx="1.2" />
      </svg>
    );
  }

  if (routeKey === "documents") {
    return (
      <svg {...sharedProps}>
        <path d="M8 3.8h6l4.2 4.2V20a1.8 1.8 0 0 1-1.8 1.8H8A1.8 1.8 0 0 1 6.2 20V5.6A1.8 1.8 0 0 1 8 3.8Z" />
        <path d="M14 3.8V8h4.2M9.2 12.1h5.6M9.2 15.6h5.6" />
      </svg>
    );
  }

  if (routeKey === "chat") {
    return (
      <svg {...sharedProps}>
        <path d="M4.2 6.4A2.2 2.2 0 0 1 6.4 4.2h11.2a2.2 2.2 0 0 1 2.2 2.2v7.2a2.2 2.2 0 0 1-2.2 2.2H11l-4.4 4v-4H6.4a2.2 2.2 0 0 1-2.2-2.2Z" />
        <path d="M8.3 9.4h7.4M8.3 12.4h4.8" />
      </svg>
    );
  }

  if (routeKey === "evaluations") {
    return (
      <svg {...sharedProps}>
        <path d="M4.6 19.8V4.2M4.6 19.8h15.2" />
        <rect x="7.8" y="11.6" width="2.8" height="5.4" rx="0.7" />
        <rect x="12.1" y="8.8" width="2.8" height="8.2" rx="0.7" />
        <rect x="16.4" y="6.1" width="2.8" height="10.9" rx="0.7" />
      </svg>
    );
  }

  if (routeKey === "pipeline") {
    return (
      <svg {...sharedProps}>
        <circle cx="6.3" cy="7" r="1.9" />
        <circle cx="17.7" cy="7" r="1.9" />
        <circle cx="12" cy="16.8" r="1.9" />
        <path d="M8.2 7h7.6M7.3 8.6l3.8 6.3M16.7 8.6l-3.8 6.3" />
      </svg>
    );
  }

  if (routeKey === "settings") {
    return (
      <svg {...sharedProps}>
        <circle cx="12" cy="12" r="2.7" />
        <path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.8-1l-.4-2.6h-4l-.4 2.6a7 7 0 0 0-1.8 1l-2.4-1-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .3 0 .7.1 1l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.8 1l.4 2.6h4l.4-2.6a7 7 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5c.1-.3.1-.7.1-1Z" />
      </svg>
    );
  }

  return (
    <svg {...sharedProps}>
      <path d="M12 3.6 5.6 6.5v5.2c0 4.1 2.5 7.8 6.4 8.9 3.9-1.1 6.4-4.8 6.4-8.9V6.5Z" />
      <path d="m9.3 12 1.8 1.8 3.6-3.7" />
    </svg>
  );
}

type TopBarMenuKey = "notifications" | "help" | "profile";

function notificationSeverityClass(severity: "info" | "warning" | "error"): string {
  if (severity === "error") {
    return "bg-rose-100 text-rose-800";
  }
  if (severity === "warning") {
    return "bg-amber-100 text-amber-800";
  }
  return "bg-slate-100 text-slate-700";
}

function formatNotificationTime(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return value;
  }
  return new Date(parsed).toLocaleString();
}

function NavList({
  navItems,
  onNavigate,
}: {
  navItems: AppNavigationItem[];
  onNavigate?: () => void;
}) {
  return (
    <nav className="grid gap-1">
      {navItems
        .filter((item) => !item.hidden)
        .map((item) => {
          if (item.disabled) {
            return (
              <div
                key={item.key}
                aria-disabled="true"
                title={routeDisabledReason(item.disabledReason)}
                className="rounded-lg border border-dashed border-slate-300 bg-slate-100/70 px-3 py-2 text-sm font-semibold text-slate-500"
              >
                <span className="flex items-center gap-2">
                  <NavigationIcon routeKey={item.key} />
                  <span>{item.label}</span>
                </span>
              </div>
            );
          }

          return (
            <Link
              key={item.key}
              href={item.href}
              onClick={onNavigate}
              className={
                item.isActive
                  ? "rounded-lg border-l-4 border-[#3525cd] bg-[#ece8ff] px-3 py-2 text-sm font-bold text-[#3525cd]"
                  : "rounded-lg px-3 py-2 text-sm font-semibold text-[#56536a] transition hover:bg-[#eceaf8]"
              }
            >
              <span className="flex items-center gap-2">
                <NavigationIcon routeKey={item.key} />
                <span>{item.label}</span>
              </span>
            </Link>
          );
        })}
    </nav>
  );
}

export function AppShell({ activeRoute, navItems, session, onSignOut, children }: AppShellProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<TopBarMenuKey | null>(null);
  const notificationsMenuRef = useRef<HTMLDivElement | null>(null);
  const helpMenuRef = useRef<HTMLDivElement | null>(null);
  const profileMenuRef = useRef<HTMLDivElement | null>(null);

  const helpItems = useMemo(() => resolveHelpMenuItems(), []);
  const notificationsEndpoint = useMemo(() => resolveNotificationsEndpoint(), []);

  const notificationsQuery = useQuery({
    queryKey: notificationsEndpoint ? queryKeys.topBar.notifications(notificationsEndpoint) : ["top-bar", "notifications", "none"],
    queryFn: () => getTopBarNotifications(notificationsEndpoint as string),
    enabled: openMenu === "notifications" && Boolean(notificationsEndpoint),
  });

  const visibleNotifications = useMemo(
    () => filterNotificationsByRole(notificationsQuery.data?.items ?? [], session.role),
    [notificationsQuery.data?.items, session.role],
  );

  const notificationCount = visibleNotifications.length;
  const showNotificationUnavailable = !notificationsEndpoint || notificationsQuery.isError;

  useEffect(() => {
    if (!openMenu) {
      return;
    }

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      const activeMenuContainer =
        openMenu === "notifications"
          ? notificationsMenuRef.current
          : openMenu === "help"
            ? helpMenuRef.current
            : profileMenuRef.current;

      if (!activeMenuContainer) {
        setOpenMenu(null);
        return;
      }

      if (!activeMenuContainer.contains(target)) {
        setOpenMenu(null);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpenMenu(null);
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [openMenu]);

  useEffect(() => {
    if (!openMenu) {
      return;
    }

    const activeMenuContainer =
      openMenu === "notifications"
        ? notificationsMenuRef.current
        : openMenu === "help"
          ? helpMenuRef.current
          : profileMenuRef.current;

    const focusTarget = activeMenuContainer?.querySelector<HTMLElement>("[data-menu-autofocus='true']");
    focusTarget?.focus();
  }, [openMenu]);

  function toggleMenu(menu: TopBarMenuKey): void {
    setOpenMenu((previous) => (previous === menu ? null : menu));
  }

  function closeMenu(): void {
    setOpenMenu(null);
  }

  return (
    <div
      className="min-h-screen bg-[#f5f4ff] text-[#1b1b24]"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <div className="mx-auto flex min-h-screen w-full max-w-[1600px]">
        <aside className="hidden w-64 shrink-0 border-r border-[#d7d4e7] bg-[#f7f5ff] px-5 py-8 lg:block">
          <div className="mb-6">
            <div className="flex items-center gap-2">
              <Image src={BRAND_LOGO_SRC} alt="Rudix logo" width={26} height={26} className="h-6 w-6" />
              <p className="text-2xl font-extrabold text-[#3525cd]">Rudix</p>
            </div>
            <p className="text-sm font-semibold text-[#5e5b72]">Enterprise RAG</p>
          </div>

          <NavList navItems={navItems} />

          <div className="mt-8 rounded-xl border border-[#d8d3f1] bg-white p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Organization</p>
            <p className="mt-1 text-sm font-semibold text-slate-800">
              {session.organizationName ?? session.organizationId ?? "Unassigned"}
            </p>
            <p className="text-xs text-slate-500">{roleLabel(session.role)}</p>
          </div>
        </aside>

        {mobileSidebarOpen ? (
          <div className="fixed inset-0 z-40 bg-[#17172a]/40 lg:hidden" onClick={() => setMobileSidebarOpen(false)}>
            <aside
              className="h-full w-[280px] border-r border-[#d7d4e7] bg-[#f7f5ff] px-4 py-5"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <Image src={BRAND_LOGO_SRC} alt="Rudix logo" width={22} height={22} className="h-5 w-5" />
                    <p className="text-xl font-extrabold text-[#3525cd]">Rudix</p>
                  </div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-[#5e5b72]">
                    Enterprise RAG
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setMobileSidebarOpen(false)}
                  className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700"
                >
                  Close
                </button>
              </div>
              <NavList navItems={navItems} onNavigate={() => setMobileSidebarOpen(false)} />
            </aside>
          </div>
        ) : null}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="border-b border-[#d7d4e7] bg-white px-4 py-4 lg:px-8">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <button
                  type="button"
                  onClick={() => setMobileSidebarOpen(true)}
                  className="rounded border border-slate-300 px-2 py-1 text-sm font-semibold text-slate-700 lg:hidden"
                >
                  Menu
                </button>
                <div className="min-w-0">
                  <h1 className="truncate text-xl font-semibold text-[#3525cd] lg:text-2xl">
                    {activeRoute.label}
                  </h1>
                  <p className="truncate text-xs text-[#6b6880]">{activeRoute.description}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="hidden rounded bg-[#edf1ff] px-2 py-1 text-xs font-semibold text-slate-700 sm:inline">
                  {roleLabel(session.role)}
                </span>

                <div className="relative" ref={notificationsMenuRef}>
                  <button
                    type="button"
                    onClick={() => toggleMenu("notifications")}
                    aria-haspopup="menu"
                    aria-expanded={openMenu === "notifications"}
                    aria-label="Notifications"
                    className="relative rounded border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
                  >
                    Notifications
                    {notificationCount > 0 ? (
                      <span className="ml-2 inline-flex min-w-5 justify-center rounded-full bg-rose-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                        {notificationCount}
                      </span>
                    ) : null}
                  </button>

                  {openMenu === "notifications" ? (
                    <div
                      role="menu"
                      aria-label="Notifications menu"
                      className="absolute right-0 z-50 mt-2 w-[360px] rounded-xl border border-[#d7d4e8] bg-white p-3 shadow-xl"
                    >
                      <p className="mb-2 text-xs font-bold uppercase tracking-[0.14em] text-[#5d58a8]">Notifications</p>

                      {!notificationsEndpoint ? (
                        <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
                          Notifications backend is not configured yet.
                        </p>
                      ) : notificationsQuery.isLoading ? (
                        <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
                          Loading notifications...
                        </p>
                      ) : notificationsQuery.isError ? (
                        <div className="space-y-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2">
                          <p className="text-sm text-rose-700">{getApiErrorMessage(notificationsQuery.error)}</p>
                          <button
                            type="button"
                            data-menu-autofocus="true"
                            onClick={() => {
                              void notificationsQuery.refetch();
                            }}
                            className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-100"
                          >
                            Retry
                          </button>
                        </div>
                      ) : notificationCount === 0 ? (
                        <p
                          data-menu-autofocus="true"
                          className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
                        >
                          No notifications right now.
                        </p>
                      ) : (
                        <ul className="max-h-[320px] space-y-2 overflow-auto">
                          {visibleNotifications.map((notification, index) => {
                            const createdAtLabel = formatNotificationTime(notification.created_at);
                            const content = (
                              <>
                                <div className="flex items-start justify-between gap-2">
                                  <p className="text-sm font-semibold text-[#2f2a46]">{notification.title}</p>
                                  <span
                                    className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${notificationSeverityClass(notification.severity)}`}
                                  >
                                    {notification.severity}
                                  </span>
                                </div>
                                {notification.message ? (
                                  <p className="mt-1 text-xs text-[#5f5a74]">{notification.message}</p>
                                ) : null}
                                {createdAtLabel ? (
                                  <p className="mt-1 text-[11px] text-[#6d6985]">{createdAtLabel}</p>
                                ) : null}
                              </>
                            );

                            if (notification.href) {
                              const external = isExternalHref(notification.href);
                              return (
                                <li key={notification.id}>
                                  <Link
                                    href={notification.href}
                                    role="menuitem"
                                    data-menu-autofocus={index === 0 ? "true" : undefined}
                                    onClick={closeMenu}
                                    target={external ? "_blank" : undefined}
                                    rel={external ? "noreferrer noopener" : undefined}
                                    className="block rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 hover:bg-[#f3f0ff]"
                                  >
                                    {content}
                                  </Link>
                                </li>
                              );
                            }

                            return (
                              <li
                                key={notification.id}
                                role="menuitem"
                                tabIndex={0}
                                data-menu-autofocus={index === 0 ? "true" : undefined}
                                className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2"
                              >
                                {content}
                              </li>
                            );
                          })}
                        </ul>
                      )}

                      {showNotificationUnavailable ? (
                        <p className="mt-2 text-[11px] text-[#7a7692]">
                          Usage warnings and failed-job alerts will appear here when the backend feed is available.
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                <div className="relative" ref={helpMenuRef}>
                  <button
                    type="button"
                    onClick={() => toggleMenu("help")}
                    aria-haspopup="menu"
                    aria-expanded={openMenu === "help"}
                    aria-label="Help"
                    className="rounded border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
                  >
                    Help
                  </button>

                  {openMenu === "help" ? (
                    <div
                      role="menu"
                      aria-label="Help menu"
                      className="absolute right-0 z-50 mt-2 w-[260px] rounded-xl border border-[#d7d4e8] bg-white p-3 shadow-xl"
                    >
                      <p className="mb-2 text-xs font-bold uppercase tracking-[0.14em] text-[#5d58a8]">Help</p>
                      {helpItems.length === 0 ? (
                        <p
                          data-menu-autofocus="true"
                          className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
                        >
                          No help resources configured.
                        </p>
                      ) : (
                        <ul className="space-y-1">
                          {helpItems.map((item, index) => {
                            const external = isExternalHref(item.href);
                            return (
                              <li key={item.id}>
                                <Link
                                  href={item.href}
                                  role="menuitem"
                                  data-menu-autofocus={index === 0 ? "true" : undefined}
                                  onClick={closeMenu}
                                  target={external ? "_blank" : undefined}
                                  rel={external ? "noreferrer noopener" : undefined}
                                  className="block rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                                >
                                  {item.label}
                                </Link>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  ) : null}
                </div>

                <div className="relative" ref={profileMenuRef}>
                  <button
                    type="button"
                    onClick={() => toggleMenu("profile")}
                    aria-haspopup="menu"
                    aria-expanded={openMenu === "profile"}
                    aria-label="Profile menu"
                    className="rounded border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
                  >
                    Profile
                  </button>

                  {openMenu === "profile" ? (
                    <div
                      role="menu"
                      aria-label="Profile menu panel"
                      className="absolute right-0 z-50 mt-2 w-[280px] rounded-xl border border-[#d7d4e8] bg-white p-3 shadow-xl"
                    >
                      <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#5d58a8]">User profile</p>
                      <p className="mt-2 text-sm font-semibold text-[#2f2a46]">{session.email ?? session.userId}</p>
                      <p className="text-xs text-[#68647b]">User ID: {session.userId}</p>
                      <p className="mt-1 text-xs text-[#68647b]">
                        Organization: {session.organizationName ?? session.organizationId ?? "Unassigned"}
                      </p>
                      <p className="text-xs text-[#68647b]">Role: {roleLabel(session.role)}</p>

                      <div className="mt-3 border-t border-[#ebe8f7] pt-2">
                        <Link
                          href="/settings"
                          role="menuitem"
                          data-menu-autofocus="true"
                          onClick={closeMenu}
                          className="block rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                        >
                          Settings
                        </Link>
                        {isAdminLikeRole(session.role) ? (
                          <Link
                            href="/admin"
                            role="menuitem"
                            onClick={closeMenu}
                            className="block rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                          >
                            Admin usage
                          </Link>
                        ) : null}
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            closeMenu();
                            onSignOut();
                          }}
                          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-left text-sm font-semibold text-slate-700 hover:bg-slate-100"
                        >
                          Sign out
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </header>
          <main className="min-h-0 flex-1 overflow-auto">{children}</main>
        </div>
      </div>
    </div>
  );
}
