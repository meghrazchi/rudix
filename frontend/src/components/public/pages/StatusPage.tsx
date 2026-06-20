"use client";

import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import { PublicActionLink } from "@/components/public/PublicActionLink";
import type {
  PublicComponentState,
  PublicStatusIncident,
  PublicStatusSnapshot,
} from "@/lib/api/public-status";

type StatusPageProps = {
  snapshot: PublicStatusSnapshot | null;
  loadError: string | null;
};

const STATE_BADGE_CLASSES: Record<PublicComponentState, string> = {
  operational: "border-emerald-200 bg-emerald-50 text-emerald-800",
  degraded: "border-amber-200 bg-amber-50 text-amber-800",
  outage: "border-rose-200 bg-rose-50 text-rose-800",
  maintenance: "border-sky-200 bg-sky-50 text-sky-800",
  unknown: "border-slate-200 bg-slate-50 text-slate-700",
};

const STATE_DOT_CLASSES: Record<PublicComponentState, string> = {
  operational: "bg-emerald-500",
  degraded: "bg-amber-500",
  outage: "bg-rose-500",
  maintenance: "bg-sky-500",
  unknown: "bg-slate-500",
};

const STATE_LABELS: Record<PublicComponentState, string> = {
  operational: "Operational",
  degraded: "Degraded",
  outage: "Outage",
  maintenance: "Maintenance",
  unknown: "Unknown",
};

function formatDateTime(value: string | null): string | null {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function StatusBadge({ state }: { state: PublicComponentState }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-[11px] font-bold tracking-[0.12em] uppercase ${STATE_BADGE_CLASSES[state]}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${STATE_DOT_CLASSES[state]}`}
      />
      {STATE_LABELS[state]}
    </span>
  );
}

function incidentBadgeState(
  incident: PublicStatusIncident,
): PublicComponentState {
  if (incident.kind === "maintenance") {
    return "maintenance";
  }
  if (incident.severity === "critical" || incident.severity === "high") {
    return "outage";
  }
  if (incident.severity === "medium" || incident.severity === "low") {
    return "degraded";
  }
  return "unknown";
}

function IncidentCard({
  incident,
  supportingText,
}: {
  incident: PublicStatusIncident;
  supportingText?: string;
}) {
  const startedAt = formatDateTime(incident.started_at);
  const resolvedAt = formatDateTime(incident.resolved_at);
  const services =
    incident.affected_services.length > 0
      ? incident.affected_services.join(", ")
      : "All public services";

  return (
    <article className="rounded-2xl border border-[#dbe0ea] bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold tracking-[0.12em] text-[#6a7285] uppercase">
            {incident.kind === "maintenance" ? "Maintenance" : "Incident"}
          </p>
          <h3 className="mt-1 text-lg font-bold text-[#11131a]">
            {incident.title}
          </h3>
        </div>
        <StatusBadge state={incidentBadgeState(incident)} />
      </div>

      <p className="mt-3 text-sm leading-6 text-[#4f5669]">
        {incident.message ?? "Update pending."}
      </p>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs font-bold tracking-[0.12em] text-[#747b8d] uppercase">
            Services
          </dt>
          <dd className="mt-1 text-[#2a3040]">{services}</dd>
        </div>
        <div>
          <dt className="text-xs font-bold tracking-[0.12em] text-[#747b8d] uppercase">
            Severity
          </dt>
          <dd className="mt-1 text-[#2a3040]">{incident.severity}</dd>
        </div>
        <div>
          <dt className="text-xs font-bold tracking-[0.12em] text-[#747b8d] uppercase">
            Started
          </dt>
          <dd className="mt-1 text-[#2a3040]">{startedAt ?? "Recently"}</dd>
        </div>
        <div>
          <dt className="text-xs font-bold tracking-[0.12em] text-[#747b8d] uppercase">
            Resolved
          </dt>
          <dd className="mt-1 text-[#2a3040]">{resolvedAt ?? "Open"}</dd>
        </div>
      </dl>

      {supportingText ? (
        <p className="mt-4 text-xs leading-5 text-[#6b7285]">
          {supportingText}
        </p>
      ) : null}
    </article>
  );
}

function ComponentCard({
  label,
  status,
  summary,
  services,
  updatedAt,
}: {
  label: string;
  status: PublicComponentState;
  summary: string;
  services: string[];
  updatedAt: string | null;
}) {
  const updatedLabel = formatDateTime(updatedAt);

  return (
    <article className="rounded-2xl border border-[#dbe0ea] bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-bold text-[#11131a]">{label}</h3>
          <p className="mt-1 text-sm leading-6 text-[#566073]">{summary}</p>
        </div>
        <StatusBadge state={status} />
      </div>

      <div className="mt-4 rounded-xl bg-[#f7f9fc] px-4 py-3 text-sm text-[#364155]">
        <p className="font-semibold">Affected services</p>
        <p className="mt-1">
          {services.length > 0 ? services.join(", ") : "None reported"}
        </p>
      </div>

      <p className="mt-3 text-xs text-[#6b7285]">
        {updatedLabel ? `Updated ${updatedLabel}` : "Updated recently"}
      </p>
    </article>
  );
}

function EmptySection({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-[#d8deea] bg-white px-5 py-6 text-sm text-[#5d6578]">
      <h3 className="text-base font-bold text-[#11131a]">{title}</h3>
      <p className="mt-2 leading-6">{description}</p>
    </div>
  );
}

export function StatusPage({ snapshot, loadError }: StatusPageProps) {
  const links = resolvePublicSiteLinks();
  const currentState =
    snapshot?.overall_status ?? (loadError ? "unknown" : "operational");
  const generatedAt = formatDateTime(snapshot?.generated_at ?? null);
  const currentIncidents = snapshot?.current_incidents ?? [];
  const scheduledMaintenance = snapshot?.scheduled_maintenance ?? [];
  const recentHistory = snapshot?.recent_history ?? [];

  const heroSummary =
    snapshot?.summary ??
    (loadError
      ? "Live status information is temporarily unavailable. The page will recover automatically when the public status API is back online."
      : "Rudix status information is currently unavailable.");

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
      <section className="grid gap-6 lg:grid-cols-[1.3fr_0.7fr]">
        <article className="rounded-[2rem] border border-[#dbe0ea] bg-[linear-gradient(135deg,#0f172a_0%,#111827_60%,#1f2937_100%)] p-7 text-white shadow-[0_24px_70px_rgba(15,23,42,0.18)]">
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-white/80 uppercase">
              Public status
            </span>
            <StatusBadge state={currentState} />
          </div>

          <h1 className="mt-5 text-4xl leading-tight font-black tracking-[-0.03em] lg:text-6xl">
            {snapshot?.headline ?? "Status data unavailable"}
          </h1>
          <p className="mt-4 max-w-3xl text-sm leading-7 text-white/80 lg:text-base">
            {heroSummary}
          </p>

          <div className="mt-7 flex flex-wrap gap-3">
            <PublicActionLink
              href={links.contact}
              className="rounded-full bg-white px-5 py-3 text-sm font-semibold text-[#111827] transition hover:bg-[#eef2f7]"
            >
              Contact support
            </PublicActionLink>
            <PublicActionLink
              href={links.changelog}
              className="rounded-full border border-white/20 bg-white/5 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              View changelog
            </PublicActionLink>
          </div>
        </article>

        <aside className="rounded-[2rem] border border-[#dbe0ea] bg-white p-6 shadow-sm">
          <p className="text-xs font-bold tracking-[0.14em] text-[#667085] uppercase">
            Snapshot
          </p>
          <dl className="mt-5 grid gap-4">
            <div className="rounded-2xl bg-[#f8fafc] px-4 py-4">
              <dt className="text-xs font-bold tracking-[0.12em] text-[#768096] uppercase">
                Current incidents
              </dt>
              <dd className="mt-1 text-3xl font-black text-[#11131a]">
                {currentIncidents.length}
              </dd>
            </div>
            <div className="rounded-2xl bg-[#f8fafc] px-4 py-4">
              <dt className="text-xs font-bold tracking-[0.12em] text-[#768096] uppercase">
                Scheduled maintenance
              </dt>
              <dd className="mt-1 text-3xl font-black text-[#11131a]">
                {scheduledMaintenance.length}
              </dd>
            </div>
            <div className="rounded-2xl bg-[#f8fafc] px-4 py-4">
              <dt className="text-xs font-bold tracking-[0.12em] text-[#768096] uppercase">
                Last published update
              </dt>
              <dd className="mt-1 text-sm font-semibold text-[#11131a]">
                {generatedAt ?? "Recently"}
              </dd>
            </div>
          </dl>
        </aside>
      </section>

      <section className="mt-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-bold tracking-[0.16em] text-[#667085] uppercase">
              Component status
            </p>
            <h2 className="mt-2 text-2xl font-black text-[#11131a]">
              How the public-facing Rudix services are behaving
            </h2>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-[#556074]">
            Component states are rolled up from the latest public incidents and
            maintenance notices. Internal hostnames, logs, and dependency names
            are intentionally omitted.
          </p>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {snapshot?.components.map((component) => (
            <ComponentCard
              key={component.key}
              label={component.label}
              status={component.status}
              summary={component.summary}
              services={component.affected_services}
              updatedAt={component.updated_at}
            />
          ))}
        </div>
      </section>

      <section className="mt-10 grid gap-6 lg:grid-cols-2">
        <div>
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-bold tracking-[0.16em] text-[#667085] uppercase">
                Current incidents
              </p>
              <h2 className="mt-2 text-2xl font-black text-[#11131a]">
                Live operational incidents
              </h2>
            </div>
          </div>
          <div className="mt-4 space-y-4">
            {currentIncidents.length > 0 ? (
              currentIncidents.map((incident) => (
                <IncidentCard
                  key={`${incident.title}-${incident.started_at}`}
                  incident={incident}
                  supportingText="We will keep this section updated until the issue is resolved."
                />
              ))
            ) : (
              <EmptySection
                title="No active incidents"
                description="There are no currently reported incidents affecting public Rudix services."
              />
            )}
          </div>
        </div>

        <div className="space-y-6">
          <div>
            <p className="text-[11px] font-bold tracking-[0.16em] text-[#667085] uppercase">
              Scheduled maintenance
            </p>
            <h2 className="mt-2 text-2xl font-black text-[#11131a]">
              Planned or in-progress maintenance
            </h2>
          </div>
          <div className="space-y-4">
            {scheduledMaintenance.length > 0 ? (
              scheduledMaintenance.map((incident) => (
                <IncidentCard
                  key={`${incident.title}-${incident.started_at}`}
                  incident={incident}
                  supportingText="Maintenance notices are published here before and during service windows when possible."
                />
              ))
            ) : (
              <EmptySection
                title="No scheduled maintenance"
                description="We do not have any public maintenance windows to report right now."
              />
            )}
          </div>
        </div>
      </section>

      <section className="mt-10">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-bold tracking-[0.16em] text-[#667085] uppercase">
              Recent history
            </p>
            <h2 className="mt-2 text-2xl font-black text-[#11131a]">
              Recently resolved incidents
            </h2>
          </div>
        </div>
        <div className="mt-4">
          {recentHistory.length > 0 ? (
            <div className="grid gap-4 md:grid-cols-2">
              {recentHistory.map((incident) => (
                <IncidentCard
                  key={`${incident.title}-${incident.resolved_at ?? incident.started_at}`}
                  incident={incident}
                  supportingText="This history is limited to public incidents from the last 30 days."
                />
              ))}
            </div>
          ) : (
            <EmptySection
              title="No recent incidents"
              description="There are no public incident updates in the recent history window."
            />
          )}
        </div>
      </section>

      <section className="mt-10 rounded-[2rem] border border-[#dbe0ea] bg-white px-6 py-5 shadow-sm">
        <p className="text-sm leading-7 text-[#526073]">
          {snapshot?.uptime_notice ?? ""}
        </p>
        {loadError ? (
          <p className="mt-3 text-sm font-medium text-[#8b5e00]">
            Live data could not be refreshed. Showing the latest public-safe
            copy.
          </p>
        ) : null}
      </section>
    </div>
  );
}
