"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import Image from "next/image";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { OnboardingChecklist } from "@/components/onboarding/OnboardingChecklist";
import {
  type OnboardingState,
  readOnboardingState,
  createDefaultOnboardingState,
} from "@/lib/onboarding";

import { listChatSessions } from "@/lib/api/chat";
import { listDocuments, type DocumentStatus } from "@/lib/api/documents";
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
import { useOverlayFocus } from "@/lib/use-overlay-focus";

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

function profileDisplayName(session: AuthenticatedSession): string {
  if (session.email && session.email.includes("@")) {
    return session.email.split("@")[0] ?? "User";
  }
  return session.email ?? session.userId;
}

function profileInitials(displayName: string): string {
  const parts = displayName
    .split(/[\s._-]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);

  if (parts.length === 0) {
    return "U";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

function routeDisabledReason(
  reason: AppNavigationItem["disabledReason"],
): string {
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

type CommandResultSection = "navigation" | "documents" | "chat";

const COMMAND_DOCUMENT_LIMIT = 80;
const COMMAND_CHAT_LIMIT = 40;
const COMMAND_MAX_RESULTS_PER_SECTION = 8;
const DOCUMENT_STATUSES: DocumentStatus[] = [
  "uploaded",
  "processing",
  "indexed",
  "failed",
  "deleting",
  "deleted",
];

function toSearchTokens(value: string): string[] {
  return value
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter((token) => token.length > 0);
}

function matchesAllTokens(
  tokens: string[],
  values: Array<string | null>,
): boolean {
  if (tokens.length === 0) {
    return true;
  }
  const normalizedValues = values
    .map((value) => value?.trim().toLowerCase() ?? "")
    .filter((value) => value.length > 0);

  return tokens.every((token) =>
    normalizedValues.some((value) => value.includes(token)),
  );
}

function statusFilterFromTokens(tokens: string[]): DocumentStatus | null {
  if (tokens.length !== 1) {
    return null;
  }
  const token = tokens[0];
  return (
    DOCUMENT_STATUSES.find(
      (status) => status === token || status.startsWith(token),
    ) ?? null
  );
}

function commandSectionLabel(section: CommandResultSection): string {
  if (section === "navigation") {
    return "Pages";
  }
  if (section === "documents") {
    return "Documents";
  }
  return "Recent chats";
}

function documentStatusBadgeClass(status: DocumentStatus): string {
  if (status === "indexed") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (status === "failed" || status === "deleted") {
    return "bg-rose-100 text-rose-800";
  }
  if (status === "deleting") {
    return "bg-fuchsia-100 text-fuchsia-800";
  }
  return "bg-amber-100 text-amber-800";
}

function notificationSeverityClass(
  severity: "info" | "warning" | "error",
): string {
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
              data-onboarding={`nav-${item.key}`}
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

export function AppShell({
  activeRoute,
  navItems,
  session,
  onSignOut,
  children,
}: AppShellProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<TopBarMenuKey | null>(null);
  const [commandMenuOpen, setCommandMenuOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [onboardingState, setOnboardingState] = useState<OnboardingState>(
    createDefaultOnboardingState,
  );
  const [onboardingVisible, setOnboardingVisible] = useState(false);

  useEffect(() => {
    const stored = readOnboardingState(session.userId);
    setOnboardingState(stored);
    if (!stored.dismissed) {
      setOnboardingVisible(true);
    }
  }, [session.userId]);
  const mobileSidebarRef = useRef<HTMLElement | null>(null);
  const commandMenuRef = useRef<HTMLElement | null>(null);
  const notificationsMenuRef = useRef<HTMLDivElement | null>(null);
  const helpMenuRef = useRef<HTMLDivElement | null>(null);
  const profileMenuRef = useRef<HTMLDivElement | null>(null);

  const helpItems = useMemo(() => resolveHelpMenuItems(), []);
  const notificationsEndpoint = useMemo(
    () => resolveNotificationsEndpoint(),
    [],
  );

  const notificationsQuery = useQuery({
    queryKey: notificationsEndpoint
      ? queryKeys.topBar.notifications(notificationsEndpoint)
      : ["top-bar", "notifications", "none"],
    queryFn: () => getTopBarNotifications(notificationsEndpoint as string),
    enabled: openMenu === "notifications" && Boolean(notificationsEndpoint),
  });

  const visibleNotifications = useMemo(
    () =>
      filterNotificationsByRole(
        notificationsQuery.data?.items ?? [],
        session.role,
      ),
    [notificationsQuery.data?.items, session.role],
  );

  const notificationCount = visibleNotifications.length;
  const showNotificationUnavailable =
    !notificationsEndpoint || notificationsQuery.isError;
  const searchTokens = useMemo(
    () => toSearchTokens(commandQuery),
    [commandQuery],
  );
  const statusFilter = useMemo(
    () => statusFilterFromTokens(searchTokens),
    [searchTokens],
  );

  const commandDocumentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      scope: "topbar-command",
      limit: COMMAND_DOCUMENT_LIMIT,
      sort_by: "updated_at",
      sort_order: "desc",
      status: statusFilter,
    }),
    queryFn: () =>
      listDocuments({
        limit: COMMAND_DOCUMENT_LIMIT,
        sort_by: "updated_at",
        sort_order: "desc",
        status: statusFilter ?? undefined,
      }),
    enabled: commandMenuOpen,
  });

  const commandChatSessionsQuery = useQuery({
    queryKey: [
      "top-bar",
      "command",
      "chat-sessions",
      { limit: COMMAND_CHAT_LIMIT },
    ],
    queryFn: () =>
      listChatSessions({
        limit: COMMAND_CHAT_LIMIT,
        offset: 0,
      }),
    enabled: commandMenuOpen,
  });

  const accessibleNavigationItems = useMemo(
    () =>
      navItems.filter((item) => !item.hidden && !item.disabled).slice(0, 12),
    [navItems],
  );

  const navigationResults = useMemo(
    () =>
      accessibleNavigationItems
        .filter((item) =>
          matchesAllTokens(searchTokens, [item.label, item.description]),
        )
        .slice(0, COMMAND_MAX_RESULTS_PER_SECTION),
    [accessibleNavigationItems, searchTokens],
  );

  const documentResults = useMemo(
    () =>
      (commandDocumentsQuery.data?.items ?? [])
        .filter((item) =>
          matchesAllTokens(searchTokens, [item.filename, item.status]),
        )
        .slice(0, COMMAND_MAX_RESULTS_PER_SECTION),
    [commandDocumentsQuery.data?.items, searchTokens],
  );

  const chatResults = useMemo(
    () =>
      (commandChatSessionsQuery.data?.items ?? [])
        .filter((item) => {
          const sessionLabel =
            item.title && item.title.trim().length > 0
              ? item.title
              : "Untitled session";
          return matchesAllTokens(searchTokens, [sessionLabel]);
        })
        .slice(0, COMMAND_MAX_RESULTS_PER_SECTION),
    [commandChatSessionsQuery.data?.items, searchTokens],
  );

  const hasCommandQuery = searchTokens.length > 0;
  const commandMenuLoading =
    commandDocumentsQuery.isLoading || commandChatSessionsQuery.isLoading;
  const commandMenuError =
    commandDocumentsQuery.error ?? commandChatSessionsQuery.error;
  const hasCommandResults =
    navigationResults.length > 0 ||
    documentResults.length > 0 ||
    chatResults.length > 0;

  const closeMobileSidebar = useCallback(() => {
    setMobileSidebarOpen(false);
  }, [setMobileSidebarOpen]);

  const closeCommandMenu = useCallback(() => {
    setCommandMenuOpen(false);
    setCommandQuery("");
  }, []);

  const openCommandMenu = useCallback(() => {
    setOpenMenu(null);
    setCommandMenuOpen(true);
  }, []);

  useOverlayFocus({
    isOpen: mobileSidebarOpen,
    containerRef: mobileSidebarRef,
    onClose: closeMobileSidebar,
  });

  useOverlayFocus({
    isOpen: commandMenuOpen,
    containerRef: commandMenuRef,
    onClose: closeCommandMenu,
    autofocusSelector: "[data-command-autofocus='true']",
  });

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
    function onGlobalCommandShortcut(event: KeyboardEvent): void {
      if (event.defaultPrevented) {
        return;
      }
      if (!event.metaKey && !event.ctrlKey) {
        return;
      }
      if (event.key.toLowerCase() !== "k") {
        return;
      }
      event.preventDefault();
      openCommandMenu();
    }

    document.addEventListener("keydown", onGlobalCommandShortcut);
    return () => {
      document.removeEventListener("keydown", onGlobalCommandShortcut);
    };
  }, [openCommandMenu]);

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

    const focusTarget = activeMenuContainer?.querySelector<HTMLElement>(
      "[data-menu-autofocus='true']",
    );
    focusTarget?.focus();
  }, [openMenu]);

  function toggleMenu(menu: TopBarMenuKey): void {
    setOpenMenu((previous) => (previous === menu ? null : menu));
  }

  function closeMenu(): void {
    setOpenMenu(null);
  }

  const displayName = profileDisplayName(session);
  const displayInitials = profileInitials(displayName);

  return (
    <div
      className="h-screen overflow-hidden bg-[#f5f4ff] text-[#1b1b24]"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <div className="flex h-full w-full">
        <aside className="hidden w-64 shrink-0 border-r border-[#d7d4e7] bg-[#f7f5ff] px-5 py-8 lg:block">
          <div className="mb-6">
            <div className="flex items-center gap-2">
              <Image
                src={BRAND_LOGO_SRC}
                alt="Rudix logo"
                width={26}
                height={26}
                className="h-6 w-6"
              />
              <p className="text-2xl font-extrabold text-[#3525cd]">Rudix</p>
            </div>
            <p className="text-sm font-semibold text-[#5e5b72]">
              Enterprise RAG
            </p>
          </div>

          <NavList navItems={navItems} />

          <div className="mt-8 rounded-xl border border-[#d8d3f1] bg-white p-3">
            <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
              Organization
            </p>
            <p className="mt-1 text-sm font-semibold text-slate-800">
              {session.organizationName ??
                session.organizationId ??
                "Unassigned"}
            </p>
            <p className="text-xs text-slate-500">{roleLabel(session.role)}</p>
          </div>
        </aside>

        {mobileSidebarOpen ? (
          <div
            className="fixed inset-0 z-40 bg-[#17172a]/40 lg:hidden"
            onClick={closeMobileSidebar}
          >
            <aside
              ref={mobileSidebarRef}
              role="dialog"
              aria-modal="true"
              aria-label="Navigation menu"
              className="h-full w-[280px] border-r border-[#d7d4e7] bg-[#f7f5ff] px-4 py-5"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <Image
                      src={BRAND_LOGO_SRC}
                      alt="Rudix logo"
                      width={22}
                      height={22}
                      className="h-5 w-5"
                    />
                    <p className="text-xl font-extrabold text-[#3525cd]">
                      Rudix
                    </p>
                  </div>
                  <p className="text-xs font-semibold tracking-wide text-[#5e5b72] uppercase">
                    Enterprise RAG
                  </p>
                </div>
                <button
                  type="button"
                  data-overlay-autofocus="true"
                  onClick={closeMobileSidebar}
                  className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700"
                >
                  Close
                </button>
              </div>
              <NavList navItems={navItems} onNavigate={closeMobileSidebar} />
            </aside>
          </div>
        ) : null}

        {commandMenuOpen ? (
          <div
            className="fixed inset-0 z-50 bg-[#17172a]/40 px-3 py-6 sm:px-6"
            onClick={closeCommandMenu}
          >
            <section
              ref={commandMenuRef}
              role="dialog"
              aria-modal="true"
              aria-label="Global search and quick navigation"
              className="mx-auto max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex items-center gap-2 border-b border-[#ebe8f7] px-3 py-3 sm:px-4">
                <input
                  data-command-autofocus="true"
                  value={commandQuery}
                  onChange={(event) => setCommandQuery(event.target.value)}
                  placeholder="Search pages, documents, chats, or status (indexed, failed...)"
                  aria-label="Search across pages, documents, and chats"
                  className="h-11 w-full rounded-lg border border-[#d9d4f0] bg-[#faf9ff] px-3 text-sm text-[#1f1e2a] placeholder:text-[#7d7896] focus:border-[#6355d5] focus:outline-none"
                />
                <button
                  type="button"
                  onClick={closeCommandMenu}
                  className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
                >
                  Esc
                </button>
              </div>

              <div className="max-h-[68vh] overflow-auto px-3 py-3 sm:px-4 sm:py-4">
                <p className="mb-3 text-xs text-[#6f6a86]">
                  Quick navigation and organization-scoped search. Use{" "}
                  <span className="font-semibold">Cmd/Ctrl + K</span> anytime.
                </p>

                {commandMenuLoading ? (
                  <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
                    Loading search results...
                  </p>
                ) : commandMenuError ? (
                  <div className="space-y-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2">
                    <p className="text-sm text-rose-700">
                      {getApiErrorMessage(commandMenuError)}
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        void commandDocumentsQuery.refetch();
                        void commandChatSessionsQuery.refetch();
                      }}
                      className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-100"
                    >
                      Retry
                    </button>
                  </div>
                ) : hasCommandResults ? (
                  <div className="space-y-4">
                    {navigationResults.length > 0 ? (
                      <section>
                        <p className="mb-2 text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase">
                          {commandSectionLabel("navigation")}
                        </p>
                        <ul className="space-y-1">
                          {navigationResults.map((item) => (
                            <li key={item.key}>
                              <Link
                                href={item.href}
                                onClick={closeCommandMenu}
                                className="flex items-start justify-between gap-3 rounded-lg border border-[#e6e3f2] bg-[#fcfbff] px-3 py-2 hover:bg-[#f3f0ff]"
                              >
                                <span>
                                  <span className="block text-sm font-semibold text-[#2f2a46]">
                                    {item.label}
                                  </span>
                                  <span className="block text-xs text-[#67637d]">
                                    {item.description}
                                  </span>
                                </span>
                                <span className="rounded bg-[#ece9ff] px-2 py-0.5 text-[10px] font-bold text-[#5042bc] uppercase">
                                  Page
                                </span>
                              </Link>
                            </li>
                          ))}
                        </ul>
                      </section>
                    ) : null}

                    {documentResults.length > 0 ? (
                      <section>
                        <p className="mb-2 text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase">
                          {hasCommandQuery
                            ? commandSectionLabel("documents")
                            : "Recent documents"}
                        </p>
                        <ul className="space-y-1">
                          {documentResults.map((document) => (
                            <li key={document.document_id}>
                              <Link
                                href={`/documents/${encodeURIComponent(document.document_id)}`}
                                onClick={closeCommandMenu}
                                className="flex items-start justify-between gap-3 rounded-lg border border-[#e6e3f2] bg-[#fcfbff] px-3 py-2 hover:bg-[#f3f0ff]"
                              >
                                <span className="min-w-0">
                                  <span className="block truncate text-sm font-semibold text-[#2f2a46]">
                                    {document.filename}
                                  </span>
                                  <span className="block text-xs text-[#67637d]">
                                    {document.file_type.toUpperCase()} • Updated{" "}
                                    {new Date(
                                      document.updated_at,
                                    ).toLocaleString()}
                                  </span>
                                </span>
                                <span
                                  className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${documentStatusBadgeClass(document.status)}`}
                                >
                                  {document.status}
                                </span>
                              </Link>
                            </li>
                          ))}
                        </ul>
                      </section>
                    ) : null}

                    {chatResults.length > 0 ? (
                      <section>
                        <p className="mb-2 text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase">
                          {hasCommandQuery
                            ? commandSectionLabel("chat")
                            : "Recent chats"}
                        </p>
                        <ul className="space-y-1">
                          {chatResults.map((sessionItem) => (
                            <li key={sessionItem.session_id}>
                              <Link
                                href={`/chat?session_id=${encodeURIComponent(sessionItem.session_id)}`}
                                onClick={closeCommandMenu}
                                className="flex items-start justify-between gap-3 rounded-lg border border-[#e6e3f2] bg-[#fcfbff] px-3 py-2 hover:bg-[#f3f0ff]"
                              >
                                <span className="min-w-0">
                                  <span className="block truncate text-sm font-semibold text-[#2f2a46]">
                                    {sessionItem.title?.trim().length
                                      ? sessionItem.title
                                      : "Untitled session"}
                                  </span>
                                  <span className="block text-xs text-[#67637d]">
                                    {sessionItem.message_count} messages •
                                    Updated{" "}
                                    {new Date(
                                      sessionItem.updated_at,
                                    ).toLocaleString()}
                                  </span>
                                </span>
                                <span className="rounded bg-[#ece9ff] px-2 py-0.5 text-[10px] font-bold text-[#5042bc] uppercase">
                                  Chat
                                </span>
                              </Link>
                            </li>
                          ))}
                        </ul>
                      </section>
                    ) : null}
                  </div>
                ) : (
                  <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
                    {hasCommandQuery
                      ? "No matching results. Try a filename, status, chat title, or page name."
                      : "No recent documents or chats yet. Upload a document or ask your first question."}
                  </p>
                )}
              </div>
            </section>
          </div>
        ) : null}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="border-b border-[#e5e3f1] bg-white px-4 py-3 lg:px-8">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <button
                  type="button"
                  onClick={() => setMobileSidebarOpen(true)}
                  className="rounded border border-slate-300 px-2 py-1 text-sm font-semibold text-slate-700 lg:hidden"
                >
                  Menu
                </button>
                <h1 className="truncate text-xl font-semibold text-[#3525cd] lg:text-2xl">
                  {activeRoute.label}
                </h1>
              </div>
              <div className="flex items-center gap-2 sm:gap-3">
                <button
                  type="button"
                  onClick={openCommandMenu}
                  aria-label="Open global search"
                  className="relative inline-flex h-11 min-w-[220px] items-center rounded-xl border border-[#e5e3f1] bg-[#f8f7ff] pl-10 pr-2 text-left text-sm font-medium text-[#4a4662] outline-none transition hover:bg-[#f2f0fb] focus-visible:ring-2 focus-visible:ring-[#3525cd]/20 sm:w-80 lg:w-[26rem]"
                >
                  <span
                    aria-hidden="true"
                    className="material-symbols-outlined absolute left-3 text-[20px] text-[#777587]"
                  >
                    search
                  </span>
                  <span className="mr-2 flex-1 truncate">
                    Search knowledge base...
                  </span>
                  <span className="ml-2 hidden shrink-0 whitespace-nowrap rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-[#6f6b87] sm:inline">
                    ⌘/Ctrl K
                  </span>
                </button>

                <div className="relative" ref={notificationsMenuRef}>
                  <button
                    type="button"
                    onClick={() => toggleMenu("notifications")}
                    aria-haspopup="menu"
                    aria-expanded={openMenu === "notifications"}
                    aria-label="Notifications"
                    className="relative inline-flex h-10 w-10 items-center justify-center rounded-full text-[#65617b] transition hover:bg-[#f3f1ff]"
                  >
                    <span
                      aria-hidden="true"
                      className="material-symbols-outlined text-[20px]"
                    >
                      notifications
                    </span>
                    {notificationCount > 0 ? (
                      <span className="absolute -right-1 -top-1 inline-flex min-w-5 justify-center rounded-full bg-rose-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
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
                      <p className="mb-2 text-xs font-bold tracking-[0.14em] text-[#5d58a8] uppercase">
                        Notifications
                      </p>

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
                          <p className="text-sm text-rose-700">
                            {getApiErrorMessage(notificationsQuery.error)}
                          </p>
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
                            const createdAtLabel = formatNotificationTime(
                              notification.created_at,
                            );
                            const content = (
                              <>
                                <div className="flex items-start justify-between gap-2">
                                  <p className="text-sm font-semibold text-[#2f2a46]">
                                    {notification.title}
                                  </p>
                                  <span
                                    className={`rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase ${notificationSeverityClass(notification.severity)}`}
                                  >
                                    {notification.severity}
                                  </span>
                                </div>
                                {notification.message ? (
                                  <p className="mt-1 text-xs text-[#5f5a74]">
                                    {notification.message}
                                  </p>
                                ) : null}
                                {createdAtLabel ? (
                                  <p className="mt-1 text-[11px] text-[#6d6985]">
                                    {createdAtLabel}
                                  </p>
                                ) : null}
                              </>
                            );

                            if (notification.href) {
                              const external = isExternalHref(
                                notification.href,
                              );
                              return (
                                <li key={notification.id}>
                                  <Link
                                    href={notification.href}
                                    role="menuitem"
                                    data-menu-autofocus={
                                      index === 0 ? "true" : undefined
                                    }
                                    onClick={closeMenu}
                                    target={external ? "_blank" : undefined}
                                    rel={
                                      external
                                        ? "noreferrer noopener"
                                        : undefined
                                    }
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
                                data-menu-autofocus={
                                  index === 0 ? "true" : undefined
                                }
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
                          Usage warnings and failed-job alerts will appear here
                          when the backend feed is available.
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
                    data-onboarding="help-button"
                    className="inline-flex h-10 w-10 items-center justify-center rounded-full text-[#65617b] transition hover:bg-[#f3f1ff]"
                  >
                    <span
                      aria-hidden="true"
                      className="material-symbols-outlined text-[20px]"
                    >
                      help_outline
                    </span>
                  </button>

                  {openMenu === "help" ? (
                    <div
                      role="menu"
                      aria-label="Help menu"
                      className="absolute right-0 z-50 mt-2 w-[260px] rounded-xl border border-[#d7d4e8] bg-white p-3 shadow-xl"
                    >
                      <p className="mb-2 text-xs font-bold tracking-[0.14em] text-[#5d58a8] uppercase">
                        Help
                      </p>
                      <ul className="space-y-1">
                        <li>
                          <button
                            type="button"
                            role="menuitem"
                            data-menu-autofocus="true"
                            data-onboarding="checklist-trigger"
                            onClick={() => {
                              closeMenu();
                              setOnboardingVisible(true);
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                          >
                            <svg
                              className="h-3.5 w-3.5 shrink-0 text-[#3525cd]"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth={2.2}
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              aria-hidden
                            >
                              <path d="M9 11l3 3L22 4" />
                              <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
                            </svg>
                            Getting started
                          </button>
                        </li>
                        {helpItems.map((item, index) => {
                          const external = isExternalHref(item.href);
                          return (
                            <li key={item.id}>
                              <Link
                                href={item.href}
                                role="menuitem"
                                data-menu-autofocus={
                                  index === 0 && helpItems.length > 0
                                    ? undefined
                                    : undefined
                                }
                                onClick={closeMenu}
                                target={external ? "_blank" : undefined}
                                rel={
                                  external ? "noreferrer noopener" : undefined
                                }
                                className="block rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                              >
                                {item.label}
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ) : null}
                </div>

                <span className="hidden h-8 w-px bg-[#e5e3f1] md:block" />

                <div className="relative" ref={profileMenuRef}>
                  <button
                    type="button"
                    onClick={() => toggleMenu("profile")}
                    aria-haspopup="menu"
                    aria-expanded={openMenu === "profile"}
                    aria-label="Profile menu"
                    className="inline-flex items-center gap-2 rounded-xl border border-[#e5e3f1] px-2 py-1.5 text-[#4a4662] transition hover:bg-[#f3f1ff]"
                  >
                    <span className="hidden text-right xl:block">
                      <span className="block text-sm font-semibold">
                        {displayName}
                      </span>
                      <span className="block text-[10px] font-semibold tracking-wide text-[#7b7793] uppercase">
                        {roleLabel(session.role)}
                      </span>
                    </span>
                    <span className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-[#d9d6e8] bg-[#f4f2ff] text-xs font-bold text-[#3525cd]">
                      {displayInitials}
                    </span>
                  </button>

                  {openMenu === "profile" ? (
                    <div
                      role="menu"
                      aria-label="Profile menu panel"
                      className="absolute right-0 z-50 mt-2 w-[280px] rounded-xl border border-[#d7d4e8] bg-white p-3 shadow-xl"
                    >
                      <p className="text-xs font-bold tracking-[0.14em] text-[#5d58a8] uppercase">
                        User profile
                      </p>
                      <p className="mt-2 text-sm font-semibold text-[#2f2a46]">
                        {session.email ?? session.userId}
                      </p>
                      <p className="text-xs text-[#68647b]">
                        User ID: {session.userId}
                      </p>
                      <p className="mt-1 text-xs text-[#68647b]">
                        Organization:{" "}
                        {session.organizationName ??
                          session.organizationId ??
                          "Unassigned"}
                      </p>
                      <p className="text-xs text-[#68647b]">
                        Role: {roleLabel(session.role)}
                      </p>

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

      {onboardingVisible ? (
        <div className="fixed bottom-5 right-5 z-40 w-[340px]">
          <OnboardingChecklist
            session={session}
            state={onboardingState}
            onStateChange={setOnboardingState}
            onDismiss={() => setOnboardingVisible(false)}
          />
        </div>
      ) : null}
    </div>
  );
}
