"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";

import type { AppNavigationItem, AppRouteMeta } from "@/lib/app-routes";
import type { AuthenticatedSession } from "@/lib/auth-session";

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
                {item.label}
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
              {item.label}
            </Link>
          );
        })}
    </nav>
  );
}

export function AppShell({ activeRoute, navItems, session, onSignOut, children }: AppShellProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <div
      className="min-h-screen bg-[#f5f4ff] text-[#1b1b24]"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <div className="mx-auto flex min-h-screen w-full max-w-[1600px]">
        <aside className="hidden w-64 shrink-0 border-r border-[#d7d4e7] bg-[#f7f5ff] px-5 py-8 lg:block">
          <div className="mb-6">
            <p className="text-2xl font-extrabold text-[#3525cd]">Rudix</p>
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
                  <p className="text-xl font-extrabold text-[#3525cd]">Rudix</p>
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
                <button
                  type="button"
                  onClick={onSignOut}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
                >
                  Sign out
                </button>
              </div>
            </div>
          </header>
          <main className="min-h-0 flex-1 overflow-auto">{children}</main>
        </div>
      </div>
    </div>
  );
}
