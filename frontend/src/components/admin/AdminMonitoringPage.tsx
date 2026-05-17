"use client";

import Link from "next/link";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isExternalHref } from "@/lib/top-bar";
import { useAuthSession } from "@/lib/use-auth-session";

function trimToNull(value: string | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function resolveMonitoringUrl(): string | null {
  return trimToNull(process.env.NEXT_PUBLIC_ADMIN_MONITORING_URL);
}

export function AdminMonitoringPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const monitoringUrl = resolveMonitoringUrl();
  const hasMonitoringUrl = Boolean(monitoringUrl);
  const external = hasMonitoringUrl ? isExternalHref(monitoringUrl as string) : false;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin monitoring restricted"
          description="Only owner and admin roles can access monitoring resources."
          compact={false}
        />
      </section>
    );
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Admin</p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">Monitoring</h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          Centralized monitoring links can be configured to open your incident and alert dashboards.
        </p>
      </header>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        {hasMonitoringUrl ? (
          <>
            <p className="text-sm text-[#4d4963]">
              Monitoring is configured for this deployment. Open the dashboard to inspect active alerts and service
              telemetry.
            </p>
            <Link
              href={monitoringUrl as string}
              target={external ? "_blank" : undefined}
              rel={external ? "noreferrer noopener" : undefined}
              className="mt-3 inline-flex rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
            >
              Open monitoring dashboard
            </Link>
          </>
        ) : (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <p className="text-sm font-semibold text-amber-900">Monitoring dashboard is not configured.</p>
            <p className="mt-1 text-sm text-amber-800">
              Set <code>NEXT_PUBLIC_ADMIN_MONITORING_URL</code> to expose a direct monitoring link from this page.
            </p>
          </div>
        )}
      </section>
    </section>
  );
}
