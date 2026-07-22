"use client";

import { useEffect, useMemo } from "react";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { AppShell } from "@/components/layout/AppShell";
import {
  APP_ROUTES,
  buildNavigationItems,
  findRouteMeta,
  resolveProtectedRouteRedirect,
} from "@/lib/app-routes";
import { addFrontendBreadcrumb } from "@/lib/observability";
import { useAuthSession } from "@/lib/use-auth-session";
import { useEffectivePermissions } from "@/lib/use-permissions";

type ProtectedAppLayoutProps = {
  children: React.ReactNode;
};

function FullScreenStatus({
  title,
  subtitle,
}: {
  title: string;
  subtitle: string;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6 text-center">
      <div className="max-w-xl rounded-2xl border border-[#d7d4e8] bg-white p-8 shadow-sm">
        <div className="mb-2 flex items-center justify-center gap-2">
          <Image
            src="/brand/rudix-mark.svg"
            alt="Rudix logo"
            width={18}
            height={18}
            className="h-[18px] w-[18px]"
          />
          <p className="text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            Rudix
          </p>
        </div>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640]">{title}</h1>
        <p className="text-sm text-[#68647b]">{subtitle}</p>
      </div>
    </div>
  );
}

export function ProtectedAppLayout({ children }: ProtectedAppLayoutProps) {
  const t = useTranslations("appShell");
  const router = useRouter();
  const pathname = usePathname();
  const { state, signOut, boundaryEvent } = useAuthSession();

  const { permissions: effectivePermissions } = useEffectivePermissions();

  const redirectTarget = useMemo(() => {
    if (
      state.status !== "loading" &&
      !state.session &&
      boundaryEvent?.redirectTo
    ) {
      return boundaryEvent.redirectTo;
    }
    return resolveProtectedRouteRedirect(pathname, state);
  }, [boundaryEvent?.redirectTo, pathname, state]);
  const sessionRole = state.session?.role ?? null;

  useEffect(() => {
    if (!redirectTarget) {
      return;
    }
    router.replace(redirectTarget);
  }, [redirectTarget, router]);

  useEffect(() => {
    if (state.status !== "authenticated" || !sessionRole || !pathname) {
      return;
    }

    addFrontendBreadcrumb({
      category: "route.transition",
      message: "Navigated within authenticated workspace",
      level: "info",
      data: {
        route: pathname,
        role: sessionRole,
      },
    });
  }, [pathname, sessionRole, state.status]);

  if (state.status === "loading") {
    return (
      <FullScreenStatus
        title={t("loadingSession")}
        subtitle={t("loadingSessionDescription")}
      />
    );
  }

  if (redirectTarget) {
    return (
      <FullScreenStatus
        title={t("redirecting")}
        subtitle={t("redirectingDescription")}
      />
    );
  }

  if (!state.session) {
    return (
      <FullScreenStatus
        title={t("sessionRequired")}
        subtitle={t("sessionRequiredDescription")}
      />
    );
  }

  const activeRoute = findRouteMeta(pathname) ?? APP_ROUTES[0];
  const navItems = buildNavigationItems(
    pathname,
    state.session,
    effectivePermissions,
  );

  return (
    <AppShell
      activeRoute={activeRoute}
      navItems={navItems}
      session={state.session}
      onSignOut={() => {
        void signOut().finally(() => {
          router.replace("/login?reason=signed_out");
        });
      }}
    >
      {children}
    </AppShell>
  );
}
