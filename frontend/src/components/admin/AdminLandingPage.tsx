"use client";

import Link from "next/link";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { canViewAdminUsage } from "@/lib/dashboard";
import { useAuthSession } from "@/lib/use-auth-session";

type AdminSurfaceCard = {
  id: "usage" | "audit" | "system-health" | "monitoring" | "governance";
  title: string;
  description: string;
  href: string;
  available: boolean;
  availabilityNote: string;
};

function trimToNull(value: string | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function resolveAdminSurfaceCards(): AdminSurfaceCard[] {
  const monitoringUrl = trimToNull(
    process.env.NEXT_PUBLIC_ADMIN_MONITORING_URL,
  );

  return [
    {
      id: "usage",
      title: "Usage analytics",
      description:
        "Inspect token usage, estimated cost, and performance trends.",
      href: "/admin/usage",
      available: true,
      availabilityNote: "Available",
    },
    {
      id: "audit",
      title: "Audit logs",
      description: "Review security and product activity across admin events.",
      href: "/admin/audit-logs",
      available: true,
      availabilityNote: "Available",
    },
    {
      id: "system-health",
      title: "System health",
      description:
        "Check API health and readiness from the deployed environment.",
      href: "/admin/system-health",
      available: true,
      availabilityNote: "Available",
    },
    {
      id: "monitoring",
      title: "Monitoring",
      description:
        "Open service monitoring and alerting dashboards for incident response.",
      href: "/admin/monitoring",
      available: Boolean(monitoringUrl),
      availabilityNote: monitoringUrl
        ? "Available"
        : "Unavailable in this deployment",
    },
    {
      id: "governance",
      title: "Agent governance",
      description:
        "Manage agent mode, MCP exposure, tool allowlists, and runtime budgets.",
      href: "/admin/governance",
      available: true,
      availabilityNote: "Available",
    },
  ];
}

export function AdminLandingPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const cards = resolveAdminSurfaceCards();

  if (!canViewAdminUsage(role)) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin area restricted"
          description="Only owner and admin roles can access the admin workspace."
          compact={false}
        />
      </section>
    );
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          Rudix Admin
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          Admin landing
        </h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          Open usage, audit, health, and monitoring surfaces with role-aware
          access controls.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        {cards.map((card) => {
          return (
            <article
              key={card.id}
              className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <h2 className="text-lg font-bold text-[#2a2640]">
                  {card.title}
                </h2>
                <span
                  className={`rounded-full px-2 py-1 text-[11px] font-semibold tracking-wide uppercase ${
                    card.available
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-amber-100 text-amber-800"
                  }`}
                >
                  {card.availabilityNote}
                </span>
              </div>
              <p className="mt-2 text-sm text-[#68647b]">{card.description}</p>
              <div className="mt-4">
                {card.available ? (
                  <Link
                    href={card.href}
                    className="inline-flex rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
                  >
                    Open {card.title}
                  </Link>
                ) : (
                  <Link
                    href={card.href}
                    className="inline-flex rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f8f6ff]"
                  >
                    View setup details
                  </Link>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
