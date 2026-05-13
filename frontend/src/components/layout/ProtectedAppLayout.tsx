"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";

import { AppShell } from "@/components/layout/AppShell";
import {
  APP_ROUTES,
  buildNavigationItems,
  findRouteMeta,
  resolveProtectedRouteRedirect,
} from "@/lib/app-routes";
import { useAuthSession } from "@/lib/use-auth-session";

type ProtectedAppLayoutProps = {
  children: React.ReactNode;
};

function FullScreenStatus({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div
      className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6 text-center"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <div className="max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-8 shadow-sm">
        <p className="mb-2 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix</p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640]">{title}</h1>
        <p className="text-sm text-[#68647b]">{subtitle}</p>
      </div>
    </div>
  );
}

export function ProtectedAppLayout({ children }: ProtectedAppLayoutProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { state, signOut } = useAuthSession();

  const redirectTarget = useMemo(() => resolveProtectedRouteRedirect(pathname, state), [pathname, state]);

  useEffect(() => {
    if (!redirectTarget) {
      return;
    }
    router.replace(redirectTarget);
  }, [redirectTarget, router]);

  if (state.status === "loading") {
    return (
      <FullScreenStatus
        title="Loading session"
        subtitle="Checking your account and organization access for this workspace."
      />
    );
  }

  if (redirectTarget) {
    return (
      <FullScreenStatus
        title="Redirecting"
        subtitle="Applying your authentication and authorization rules."
      />
    );
  }

  if (!state.session) {
    return (
      <FullScreenStatus
        title="Session required"
        subtitle="You need to sign in before viewing authenticated pages."
      />
    );
  }

  const activeRoute = findRouteMeta(pathname) ?? APP_ROUTES[0];
  const navItems = buildNavigationItems(pathname, state.session);

  return (
    <AppShell
      activeRoute={activeRoute}
      navItems={navItems}
      session={state.session}
      onSignOut={() => {
        signOut();
        router.replace("/login");
      }}
    >
      {children}
    </AppShell>
  );
}
