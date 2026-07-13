"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import {
  BarChart2,
  FileText,
  Folder,
  LayoutGrid,
  MessageSquare,
  Plug,
  Network,
  Settings,
  Shield,
  Workflow,
  type LucideProps,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { HelpCenterDrawer } from "@/components/help/HelpCenterDrawer";
import { KeyboardShortcutsModal } from "@/components/help/KeyboardShortcutsModal";
import { OnboardingChecklist } from "@/components/onboarding/OnboardingChecklist";
import { HelpCenterContext, type HelpTopic } from "@/lib/help-center-context";
import { ProfileMenu } from "@/components/layout/ProfileMenu";
import { ServiceStatusBanner } from "@/components/admin/ServiceStatusBanner";
import { SkipLink } from "@/components/layout/SkipLink";
import { WorkspaceSwitcherCard } from "@/components/workspace/WorkspaceSwitcherCard";
import {
  type OnboardingState,
  readOnboardingState,
  createDefaultOnboardingState,
} from "@/lib/onboarding";
import { clearAuthSensitiveQueryState } from "@/lib/api/query";

import { listChatSessions } from "@/lib/api/chat";
import { listDocuments, type DocumentStatus } from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import type {
  AppNavigationItem,
  AppRouteMeta,
  AppRouteKey,
} from "@/lib/app-routes";
import type { AuthenticatedSession } from "@/lib/auth-session";
import {
  type HelpMenuItem,
  isExternalHref,
  resolveHelpMenuItems,
} from "@/lib/top-bar";
import {
  NotificationCenter,
  useNotificationUnreadCount,
} from "@/components/layout/NotificationCenter";
import { trackPageView } from "@/lib/analytics";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

const BRAND_LOGO_SRC = "/brand/rudix-mark.svg";

type AppShellProps = {
  activeRoute: AppRouteMeta;
  navItems: AppNavigationItem[];
  session: AuthenticatedSession;
  onSignOut: () => void;
  children: ReactNode;
};

function useRouteDisabledReason() {
  const t = useTranslations("navigation");
  return function routeDisabledReason(
    reason: AppNavigationItem["disabledReason"],
  ): string {
    if (reason === "insufficient_role") return t("insufficientRole");
    if (reason === "insufficient_permission")
      return t("insufficientPermission");
    if (reason === "unauthenticated") return t("authRequired");
    return t("sectionUnavailable");
  };
}

const NAV_ICONS: Partial<
  Record<AppNavigationItem["key"], ComponentType<LucideProps>>
> = {
  dashboard: LayoutGrid,
  documents: FileText,
  collections: Folder,
  graph: Network,
  chat: MessageSquare,
  evaluations: BarChart2,
  reports: BarChart2,
  pipeline: Workflow,
  connectors: Plug,
  settings: Settings,
};

function NavigationIcon({ routeKey }: { routeKey: AppNavigationItem["key"] }) {
  const Icon = NAV_ICONS[routeKey] ?? Shield;
  return <Icon className="h-4 w-4 shrink-0" strokeWidth={1.9} aria-hidden />;
}

function routeKeyToFeatureArea(
  routeKey: AppNavigationItem["key"],
):
  | "dashboard"
  | "documents"
  | "chat"
  | "evaluations"
  | "settings"
  | "connectors" {
  if (routeKey === "chat" || routeKey === "agent-workspace") {
    return "chat";
  }
  if (routeKey === "evaluations") {
    return "evaluations";
  }
  if (routeKey === "connectors") {
    return "connectors";
  }
  if (
    routeKey === "settings" ||
    routeKey === "user-profile" ||
    routeKey === "admin"
  ) {
    return "settings";
  }
  if (
    routeKey === "documents" ||
    routeKey === "collections" ||
    routeKey === "graph"
  ) {
    return "documents";
  }
  return "dashboard";
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

function useCommandSectionLabel() {
  const t = useTranslations("appShell");
  return function commandSectionLabel(section: CommandResultSection): string {
    if (section === "navigation") return t("pages");
    if (section === "documents") return t("documents");
    return t("recentChats");
  };
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

function useNavLabelMap(): Record<AppRouteKey, string> {
  const tNav = useTranslations("navigation");
  return useMemo(
    () => ({
      dashboard: tNav("dashboard"),
      documents: tNav("documents"),
      collections: tNav("collections"),
      graph: tNav("graph"),
      chat: tNav("chat"),
      "agent-workspace": tNav("agentWorkspace"),
      evaluations: tNav("evaluations"),
      reports: tNav("reports"),
      pipeline: tNav("pipeline"),
      connectors: tNav("connectors"),
      "user-profile": tNav("userProfile"),
      settings: tNav("settings"),
      admin: tNav("admin"),
    }),
    [tNav],
  );
}

function useNavDescriptionMap(): Record<AppRouteKey, string> {
  const tNav = useTranslations("navigation");
  return useMemo(
    () => ({
      dashboard: tNav("descriptions.dashboard"),
      documents: tNav("descriptions.documents"),
      collections: tNav("descriptions.collections"),
      graph: tNav("descriptions.graph"),
      chat: tNav("descriptions.chat"),
      "agent-workspace": tNav("descriptions.agentWorkspace"),
      evaluations: tNav("descriptions.evaluations"),
      reports: tNav("descriptions.reports"),
      pipeline: tNav("descriptions.pipeline"),
      connectors: tNav("descriptions.connectors"),
      "user-profile": tNav("descriptions.userProfile"),
      settings: tNav("descriptions.settings"),
      admin: tNav("descriptions.admin"),
    }),
    [tNav],
  );
}

function useHelpItemLabelMap(): Record<HelpMenuItem["id"], string> {
  const tNav = useTranslations("navigation");
  return useMemo(
    () => ({
      docs: tNav("helpItems.docs"),
      changelog: tNav("helpItems.changelog"),
      status: tNav("helpItems.status"),
      support: tNav("helpItems.support"),
      shortcuts: tNav("helpItems.shortcuts"),
      readme: tNav("helpItems.readme"),
    }),
    [tNav],
  );
}

function NavList({
  navItems,
  onNavigate,
  collapsed = false,
  ariaLabel,
}: {
  navItems: AppNavigationItem[];
  onNavigate?: () => void;
  collapsed?: boolean;
  ariaLabel?: string;
}) {
  const getDisabledReason = useRouteDisabledReason();
  const navLabel = useNavLabelMap();
  return (
    <nav aria-label={ariaLabel} className="grid gap-1">
      {navItems
        .filter((item) => !item.hidden)
        .map((item) => {
          const label = navLabel[item.key] ?? item.label;
          if (item.disabled) {
            return (
              <div
                key={item.key}
                role="link"
                tabIndex={0}
                aria-disabled="true"
                aria-label={`${label} — ${getDisabledReason(item.disabledReason)}`}
                title={getDisabledReason(item.disabledReason)}
                className={
                  collapsed
                    ? "flex cursor-not-allowed justify-center rounded-lg border border-dashed border-slate-300 bg-slate-100/70 py-2 text-slate-500"
                    : "cursor-not-allowed rounded-lg border border-dashed border-slate-300 bg-slate-100/70 px-3 py-2 text-sm font-semibold text-slate-500"
                }
              >
                <span className={collapsed ? "" : "flex items-center gap-2"}>
                  <NavigationIcon routeKey={item.key} />
                  {!collapsed && <span aria-hidden="true">{label}</span>}
                </span>
              </div>
            );
          }

          return (
            <Link
              key={item.key}
              href={item.href}
              onClick={onNavigate}
              title={collapsed ? label : undefined}
              aria-current={item.isActive ? "page" : undefined}
              data-onboarding={`nav-${item.key}`}
              className={
                collapsed
                  ? item.isActive
                    ? "flex justify-center rounded-lg border-l-4 border-[#3525cd] bg-[#ece8ff] py-2 text-[#3525cd] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                    : "flex justify-center rounded-lg py-2 text-[#56536a] transition hover:bg-[#eceaf8] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                  : item.isActive
                    ? "rounded-lg border-l-4 border-[#3525cd] bg-[#ece8ff] px-3 py-2 text-sm font-bold text-[#3525cd] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                    : "rounded-lg px-3 py-2 text-sm font-semibold text-[#56536a] transition hover:bg-[#eceaf8] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
              }
            >
              <span className={collapsed ? "" : "flex items-center gap-2"}>
                <NavigationIcon routeKey={item.key} />
                {!collapsed && <span>{label}</span>}
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
  const pathname = usePathname();
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("sidebar_collapsed") === "true";
  });
  const [openMenu, setOpenMenu] = useState<TopBarMenuKey | null>(null);
  const [commandMenuOpen, setCommandMenuOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [onboardingState, setOnboardingState] = useState<OnboardingState>(
    createDefaultOnboardingState,
  );
  const [onboardingVisible, setOnboardingVisible] = useState(false);
  const [helpCenterOpen, setHelpCenterOpen] = useState(false);
  const [helpCenterTopic, setHelpCenterTopic] = useState<HelpTopic | null>(
    null,
  );
  const [shortcutsModalOpen, setShortcutsModalOpen] = useState(false);

  useEffect(() => {
    const stored = readOnboardingState(session.userId);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOnboardingState(stored);
    if (!stored.dismissed) {
      setOnboardingVisible(true);
    }
  }, [session.userId]);

  const prevOrgIdRef = useRef(session.organizationId);
  useEffect(() => {
    if (prevOrgIdRef.current === session.organizationId) return;
    prevOrgIdRef.current = session.organizationId;
    void clearAuthSensitiveQueryState();
  }, [session.organizationId]);
  const mobileSidebarRef = useRef<HTMLElement | null>(null);
  const commandMenuRef = useRef<HTMLElement | null>(null);
  const notificationsMenuRef = useRef<HTMLDivElement | null>(null);
  const helpMenuRef = useRef<HTMLDivElement | null>(null);
  const profileMenuRef = useRef<HTMLDivElement | null>(null);

  const t = useTranslations("appShell");
  const tCommon = useTranslations("common");
  const tNav = useTranslations("navigation");
  const getCommandSectionLabel = useCommandSectionLabel();
  const navLabel = useNavLabelMap();
  const navDescription = useNavDescriptionMap();
  const helpItemLabel = useHelpItemLabelMap();
  const helpItems = useMemo(() => resolveHelpMenuItems(), []);
  const unreadNotificationCount = useNotificationUnreadCount();
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
          matchesAllTokens(searchTokens, [
            navLabel[item.key] ?? item.label,
            navDescription[item.key] ?? item.description,
          ]),
        )
        .slice(0, COMMAND_MAX_RESULTS_PER_SECTION),
    [accessibleNavigationItems, navDescription, navLabel, searchTokens],
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

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("sidebar_collapsed", String(next));
      return next;
    });
  }, []);

  const closeCommandMenu = useCallback(() => {
    setCommandMenuOpen(false);
    setCommandQuery("");
  }, []);

  const openCommandMenu = useCallback(() => {
    setOpenMenu(null);
    setCommandMenuOpen(true);
  }, []);

  const openHelpCenter = useCallback((topic?: HelpTopic) => {
    setOpenMenu(null);
    setHelpCenterTopic(topic ?? null);
    setHelpCenterOpen(true);
  }, []);

  const closeHelpCenter = useCallback(() => {
    setHelpCenterOpen(false);
    setHelpCenterTopic(null);
  }, []);

  const openKeyboardShortcuts = useCallback(() => {
    setOpenMenu(null);
    setHelpCenterOpen(false);
    setShortcutsModalOpen(true);
  }, []);

  const closeKeyboardShortcuts = useCallback(() => {
    setShortcutsModalOpen(false);
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

  // Announce route changes to screen readers.
  useEffect(() => {
    const announcer = document.getElementById("a11y-announcer");
    if (!announcer) return;
    const pageName = navLabel[activeRoute.key] ?? activeRoute.label;
    announcer.textContent = "";
    const rafId = requestAnimationFrame(() => {
      announcer.textContent = t("navigatedTo", { page: pageName });
    });
    return () => cancelAnimationFrame(rafId);
  }, [activeRoute, navLabel, t]);

  useEffect(() => {
    void trackPageView({
      pageKey: activeRoute.key,
      route: pathname ?? activeRoute.href ?? "",
      surface: "app",
      featureArea: routeKeyToFeatureArea(activeRoute.key),
    });
  }, [activeRoute, pathname]);

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
    function onShortcutsKey(event: KeyboardEvent): void {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey) {
        return;
      }
      if (event.key !== "?") {
        return;
      }
      const target = event.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }
      event.preventDefault();
      openKeyboardShortcuts();
    }

    document.addEventListener("keydown", onShortcutsKey);
    return () => {
      document.removeEventListener("keydown", onShortcutsKey);
    };
  }, [openKeyboardShortcuts]);

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

  const mainOverflowClass =
    activeRoute.key === "chat" ? "overflow-hidden" : "overflow-auto";

  const commandSectionLabelFor = (section: CommandResultSection): string =>
    getCommandSectionLabel(section);

  return (
    <div
      className="h-screen overflow-hidden bg-[#f5f4ff] text-[#1b1b24]"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <SkipLink />
      {/* Polite live region for route change announcements */}
      <div
        id="a11y-announcer"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      />
      {/* Assertive live region for urgent announcements */}
      <div
        id="a11y-announcer-assertive"
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
        className="sr-only"
      />
      <div className="flex h-full w-full">
        <aside
          className={`relative hidden shrink-0 flex-col border-r border-[#d7d4e7] bg-[#f7f5ff] py-6 transition-all duration-200 lg:flex ${sidebarCollapsed ? "w-14 px-2" : "w-64 px-5"}`}
        >
          {/* floating toggle button on the right edge */}
          <button
            type="button"
            onClick={toggleSidebar}
            aria-label={
              sidebarCollapsed ? t("expandSidebar") : t("collapseSidebar")
            }
            title={sidebarCollapsed ? t("expandSidebar") : t("collapseSidebar")}
            className="absolute top-6 -right-3 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-[#d7d4e7] bg-white text-[#56536a] shadow-sm transition hover:bg-[#eceaf8] hover:text-[#3525cd] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
          >
            <span className="material-symbols-outlined text-[16px]">
              {sidebarCollapsed ? "chevron_right" : "chevron_left"}
            </span>
          </button>

          <div
            className={`mb-6 ${sidebarCollapsed ? "flex justify-center" : ""}`}
          >
            {sidebarCollapsed ? (
              <Image
                src={BRAND_LOGO_SRC}
                alt="Rudix logo"
                width={26}
                height={26}
                className="h-6 w-6"
                title="Rudix"
              />
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <Image
                    src={BRAND_LOGO_SRC}
                    alt="Rudix logo"
                    width={26}
                    height={26}
                    className="h-6 w-6"
                  />
                  <p className="text-2xl font-extrabold text-[#3525cd]">
                    Rudix
                  </p>
                </div>
                <p className="text-sm font-semibold text-[#5e5b72]">
                  {t("enterpriseRag")}
                </p>
              </>
            )}
          </div>

          <div className="flex-1 overflow-hidden">
            <NavList
              navItems={navItems}
              collapsed={sidebarCollapsed}
              ariaLabel={t("primaryNav")}
            />
          </div>

          {!sidebarCollapsed && <WorkspaceSwitcherCard session={session} />}
        </aside>

        {mobileSidebarOpen ? (
          <div
            className="fixed inset-0 z-40 bg-[#17172a]/40 lg:hidden"
            onClick={closeMobileSidebar}
          >
            <aside
              id="mobile-sidebar"
              ref={mobileSidebarRef}
              role="dialog"
              aria-modal="true"
              aria-label={t("navigationMenu")}
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
                    {t("enterpriseRag")}
                  </p>
                </div>
                <button
                  type="button"
                  data-overlay-autofocus="true"
                  aria-label={t("closeMenu")}
                  onClick={closeMobileSidebar}
                  className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                >
                  {t("close")}
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
              aria-label={t("commandMenuAriaLabel")}
              className="mx-auto max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex items-center gap-2 border-b border-[#ebe8f7] px-3 py-3 sm:px-4">
                <input
                  data-command-autofocus="true"
                  value={commandQuery}
                  onChange={(event) => setCommandQuery(event.target.value)}
                  placeholder={t("searchKnowledgeBase")}
                  aria-label={t("searchAriaLabel")}
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
                  {t("quickNavHint", { shortcut: "Cmd/Ctrl + K" })}
                </p>

                {commandMenuLoading ? (
                  <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
                    {t("loadingResults")}
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
                      {tCommon("retry")}
                    </button>
                  </div>
                ) : hasCommandResults ? (
                  <div className="space-y-4">
                    {navigationResults.length > 0 ? (
                      <section aria-labelledby="cmd-section-nav">
                        <p
                          id="cmd-section-nav"
                          className="mb-2 text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase"
                        >
                          {commandSectionLabelFor("navigation")}
                        </p>
                        <ul className="space-y-1">
                          {navigationResults.map((item) => (
                            <li key={item.key}>
                              <Link
                                href={item.href}
                                onClick={closeCommandMenu}
                                className="flex items-start justify-between gap-3 rounded-lg border border-[#e6e3f2] bg-[#fcfbff] px-3 py-2 hover:bg-[#f3f0ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                              >
                                <span>
                                  <span className="block text-sm font-semibold text-[#2f2a46]">
                                    {navLabel[item.key] ?? item.label}
                                  </span>
                                  <span className="block text-xs text-[#67637d]">
                                    {navDescription[item.key] ??
                                      item.description}
                                  </span>
                                </span>
                                <span className="rounded bg-[#ece9ff] px-2 py-0.5 text-[10px] font-bold text-[#5042bc] uppercase">
                                  {tCommon("page")}
                                </span>
                              </Link>
                            </li>
                          ))}
                        </ul>
                      </section>
                    ) : null}

                    {documentResults.length > 0 ? (
                      <section aria-labelledby="cmd-section-docs">
                        <p
                          id="cmd-section-docs"
                          className="mb-2 text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase"
                        >
                          {hasCommandQuery
                            ? commandSectionLabelFor("documents")
                            : t("recentDocuments")}
                        </p>
                        <ul className="space-y-1">
                          {documentResults.map((document) => (
                            <li key={document.document_id}>
                              <Link
                                href={`/documents/${encodeURIComponent(document.document_id)}`}
                                onClick={closeCommandMenu}
                                className="flex items-start justify-between gap-3 rounded-lg border border-[#e6e3f2] bg-[#fcfbff] px-3 py-2 hover:bg-[#f3f0ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                              >
                                <span className="min-w-0">
                                  <span className="block truncate text-sm font-semibold text-[#2f2a46]">
                                    {document.filename}
                                  </span>
                                  <span className="block text-xs text-[#67637d]">
                                    {document.file_type.toUpperCase()} •{" "}
                                    {t("updated")}{" "}
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
                      <section aria-labelledby="cmd-section-chat">
                        <p
                          id="cmd-section-chat"
                          className="mb-2 text-[11px] font-bold tracking-[0.12em] text-[#625d7e] uppercase"
                        >
                          {hasCommandQuery
                            ? commandSectionLabelFor("chat")
                            : t("recentChats")}
                        </p>
                        <ul className="space-y-1">
                          {chatResults.map((sessionItem) => (
                            <li key={sessionItem.session_id}>
                              <Link
                                href={`/chat?session_id=${encodeURIComponent(sessionItem.session_id)}`}
                                onClick={closeCommandMenu}
                                className="flex items-start justify-between gap-3 rounded-lg border border-[#e6e3f2] bg-[#fcfbff] px-3 py-2 hover:bg-[#f3f0ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                              >
                                <span className="min-w-0">
                                  <span className="block truncate text-sm font-semibold text-[#2f2a46]">
                                    {sessionItem.title?.trim().length
                                      ? sessionItem.title
                                      : t("untitledSession")}
                                  </span>
                                  <span className="block text-xs text-[#67637d]">
                                    {sessionItem.message_count} {t("messages")}{" "}
                                    • {t("updated")}{" "}
                                    {new Date(
                                      sessionItem.updated_at,
                                    ).toLocaleString()}
                                  </span>
                                </span>
                                <span className="rounded bg-[#ece9ff] px-2 py-0.5 text-[10px] font-bold text-[#5042bc] uppercase">
                                  {tNav("chat")}
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
                    {hasCommandQuery ? t("noResults") : t("noDocumentsOrChats")}
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
                  aria-label={t("openMenu")}
                  aria-expanded={mobileSidebarOpen}
                  aria-controls="mobile-sidebar"
                  className="rounded border border-slate-300 px-2 py-1 text-sm font-semibold text-slate-700 focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none lg:hidden"
                >
                  {t("menu")}
                </button>
                <h1 className="truncate text-xl font-semibold text-[#3525cd] lg:text-2xl">
                  {navLabel[activeRoute.key] ?? activeRoute.label}
                </h1>
              </div>
              <div className="flex items-center gap-2 sm:gap-3">
                {/* Icon-only search trigger on small screens */}
                <button
                  type="button"
                  onClick={openCommandMenu}
                  aria-label={t("openSearch")}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-[#e5e3f1] bg-[#f8f7ff] text-[#777587] transition hover:bg-[#f2f0fb] focus-visible:ring-2 focus-visible:ring-[#3525cd]/20 focus-visible:outline-none sm:hidden"
                >
                  <span
                    aria-hidden="true"
                    className="material-symbols-outlined text-[20px]"
                  >
                    search
                  </span>
                </button>
                {/* Full search bar on sm+ screens */}
                <button
                  type="button"
                  onClick={openCommandMenu}
                  aria-label={t("openSearch")}
                  className="relative hidden h-11 items-center rounded-xl border border-[#e5e3f1] bg-[#f8f7ff] pr-2 pl-10 text-left text-sm font-medium text-[#4a4662] transition outline-none hover:bg-[#f2f0fb] focus-visible:ring-2 focus-visible:ring-[#3525cd]/20 sm:inline-flex sm:w-72 lg:w-[26rem]"
                >
                  <span
                    aria-hidden="true"
                    className="material-symbols-outlined absolute left-3 text-[20px] text-[#777587]"
                  >
                    search
                  </span>
                  <span className="mr-2 flex-1 truncate">
                    {t("searchKnowledgeBase")}
                  </span>
                  <span className="ml-2 hidden shrink-0 rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap text-[#6f6b87] md:inline">
                    ⌘/Ctrl K
                  </span>
                </button>

                <div className="relative" ref={notificationsMenuRef}>
                  <button
                    type="button"
                    onClick={() => toggleMenu("notifications")}
                    aria-haspopup="menu"
                    aria-expanded={openMenu === "notifications"}
                    aria-label={
                      unreadNotificationCount > 0
                        ? t("notificationsUnread", {
                            count: unreadNotificationCount,
                          })
                        : t("notifications")
                    }
                    className="relative inline-flex h-10 w-10 cursor-pointer items-center justify-center rounded-full text-[#65617b] transition hover:bg-[#f3f1ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                  >
                    <span
                      aria-hidden="true"
                      className="material-symbols-outlined text-[20px]"
                    >
                      notifications
                    </span>
                    {unreadNotificationCount > 0 ? (
                      <span
                        aria-hidden="true"
                        className="absolute -top-1 -right-1 inline-flex min-w-5 justify-center rounded-full bg-rose-600 px-1.5 py-0.5 text-[10px] font-bold text-white"
                      >
                        {unreadNotificationCount > 99
                          ? "99+"
                          : unreadNotificationCount}
                      </span>
                    ) : null}
                  </button>

                  <NotificationCenter
                    isOpen={openMenu === "notifications"}
                    onNavigate={closeMenu}
                    menuRef={notificationsMenuRef}
                  />
                </div>

                <div className="relative" ref={helpMenuRef}>
                  <button
                    type="button"
                    onClick={() => toggleMenu("help")}
                    aria-haspopup="menu"
                    aria-expanded={openMenu === "help"}
                    aria-label={t("help")}
                    data-onboarding="help-button"
                    className="inline-flex h-10 w-10 cursor-pointer items-center justify-center rounded-full text-[#65617b] transition hover:bg-[#f3f1ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
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
                      aria-label={t("help")}
                      className="absolute right-0 z-50 mt-2 w-[260px] rounded-xl border border-[#d7d4e8] bg-white p-3 shadow-xl"
                    >
                      <p className="mb-2 text-xs font-bold tracking-[0.14em] text-[#5d58a8] uppercase">
                        {t("help")}
                      </p>
                      <ul className="space-y-1">
                        <li>
                          <button
                            type="button"
                            role="menuitem"
                            data-menu-autofocus="true"
                            onClick={() => {
                              closeMenu();
                              openHelpCenter();
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                          >
                            <span
                              aria-hidden="true"
                              className="material-symbols-outlined text-[16px] text-[#3525cd]"
                            >
                              menu_book
                            </span>
                            {t("helpCenter")}
                          </button>
                        </li>
                        <li>
                          <button
                            type="button"
                            role="menuitem"
                            onClick={() => {
                              closeMenu();
                              openKeyboardShortcuts();
                            }}
                            className="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                          >
                            <span className="flex items-center gap-2">
                              <span
                                aria-hidden="true"
                                className="material-symbols-outlined text-[16px] text-[#3525cd]"
                              >
                                keyboard
                              </span>
                              {helpItemLabel["shortcuts"] ??
                                t("keyboardShortcuts")}
                            </span>
                            <kbd className="rounded border border-[#d3cff0] bg-[#f7f5ff] px-1.5 py-0.5 text-[10px] font-semibold text-[#5d58a8]">
                              ?
                            </kbd>
                          </button>
                        </li>
                        <li>
                          <button
                            type="button"
                            role="menuitem"
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
                            {tNav("gettingStarted")}
                          </button>
                        </li>
                        {helpItems
                          .filter((item) => item.id !== "shortcuts")
                          .map((item) => {
                            const external = isExternalHref(item.href);
                            return (
                              <li key={item.id}>
                                <Link
                                  href={item.href}
                                  role="menuitem"
                                  onClick={closeMenu}
                                  target={external ? "_blank" : undefined}
                                  rel={
                                    external ? "noreferrer noopener" : undefined
                                  }
                                  className="block rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                                >
                                  {helpItemLabel[item.id] ?? item.label}
                                </Link>
                              </li>
                            );
                          })}
                      </ul>
                    </div>
                  ) : null}
                </div>

                <span className="hidden h-8 w-px bg-[#e5e3f1] md:block" />

                <ProfileMenu
                  session={session}
                  isOpen={openMenu === "profile"}
                  onToggle={() => toggleMenu("profile")}
                  onClose={closeMenu}
                  onSignOut={onSignOut}
                  menuRef={profileMenuRef}
                />
              </div>
            </div>
          </header>
          <ServiceStatusBanner />
          <main
            id="main-content"
            tabIndex={-1}
            className={`min-h-0 flex-1 focus:outline-none ${mainOverflowClass}`}
          >
            <HelpCenterContext.Provider
              value={{ openHelpCenter, openKeyboardShortcuts }}
            >
              {children}
            </HelpCenterContext.Provider>
          </main>
        </div>
      </div>

      {onboardingVisible ? (
        <div className="fixed right-4 bottom-4 z-40 w-[calc(100vw-2rem)] max-w-[340px] sm:right-5 sm:bottom-5">
          <OnboardingChecklist
            session={session}
            state={onboardingState}
            onStateChange={setOnboardingState}
            onDismiss={() => setOnboardingVisible(false)}
          />
        </div>
      ) : null}

      <HelpCenterDrawer
        isOpen={helpCenterOpen}
        onClose={closeHelpCenter}
        initialTopic={helpCenterTopic}
        onOpenShortcuts={openKeyboardShortcuts}
        session={session}
      />

      <KeyboardShortcutsModal
        isOpen={shortcutsModalOpen}
        onClose={closeKeyboardShortcuts}
      />
    </div>
  );
}
