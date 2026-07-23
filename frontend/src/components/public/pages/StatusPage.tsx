"use client";

import { useFormatter, useTranslations } from "next-intl";

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

function parseDateTime(value: string | null): Date | null {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  return parsed;
}

function StatusBadge({ state }: { state: PublicComponentState }) {
  const t = useTranslations("public.status");

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-[11px] font-bold tracking-[0.12em] uppercase ${STATE_BADGE_CLASSES[state]}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${STATE_DOT_CLASSES[state]}`}
      />
      {t(`states.${state}`)}
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
  const t = useTranslations("public.status");
  const format = useFormatter();
  const startedAt = parseDateTime(incident.started_at);
  const resolvedAt = parseDateTime(incident.resolved_at);
  const services =
    incident.affected_services.length > 0
      ? incident.affected_services.join(", ")
      : t("allPublicServices");

  return (
    <article className="rounded-2xl border border-[#dbe0ea] bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold tracking-[0.12em] text-[#6a7285] uppercase">
            {incident.kind === "maintenance" ? t("maintenance") : t("incident")}
          </p>
          <h3 className="mt-1 text-lg font-bold text-[#11131a]">
            {incident.title}
          </h3>
        </div>
        <StatusBadge state={incidentBadgeState(incident)} />
      </div>

      <p className="mt-3 text-sm leading-6 text-[#4f5669]">
        {incident.message ?? t("updatePending")}
      </p>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs font-bold tracking-[0.12em] text-[#747b8d] uppercase">
            {t("services")}
          </dt>
          <dd className="mt-1 text-[#2a3040]">{services}</dd>
        </div>
        <div>
          <dt className="text-xs font-bold tracking-[0.12em] text-[#747b8d] uppercase">
            {t("severity")}
          </dt>
          <dd className="mt-1 text-[#2a3040]">{incident.severity}</dd>
        </div>
        <div>
          <dt className="text-xs font-bold tracking-[0.12em] text-[#747b8d] uppercase">
            {t("started")}
          </dt>
          <dd className="mt-1 text-[#2a3040]">
            {startedAt
              ? format.dateTime(startedAt, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })
              : t("recently")}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-bold tracking-[0.12em] text-[#747b8d] uppercase">
            {t("resolved")}
          </dt>
          <dd className="mt-1 text-[#2a3040]">
            {resolvedAt
              ? format.dateTime(resolvedAt, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })
              : t("open")}
          </dd>
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
  const t = useTranslations("public.status");
  const format = useFormatter();
  const updatedDate = parseDateTime(updatedAt);

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
        <p className="font-semibold">{t("affectedServices")}</p>
        <p className="mt-1">
          {services.length > 0 ? services.join(", ") : t("noneReported")}
        </p>
      </div>

      <p className="mt-3 text-xs text-[#6b7285]">
        {updatedDate
          ? t("updatedAt", {
              date: format.dateTime(updatedDate, {
                dateStyle: "medium",
                timeStyle: "short",
              }),
            })
          : t("updatedRecently")}
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
  const t = useTranslations("public.status");
  const format = useFormatter();
  const links = resolvePublicSiteLinks();
  const currentState =
    snapshot?.overall_status ?? (loadError ? "unknown" : "operational");
  const generatedDate = parseDateTime(snapshot?.generated_at ?? null);
  const generatedAt = generatedDate
    ? format.dateTime(generatedDate, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : null;
  const currentIncidents = snapshot?.current_incidents ?? [];
  const scheduledMaintenance = snapshot?.scheduled_maintenance ?? [];
  const recentHistory = snapshot?.recent_history ?? [];

  const heroSummary =
    snapshot?.summary ??
    (loadError ? t("liveUnavailable") : t("statusUnavailable"));

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
      <section className="grid gap-6 lg:grid-cols-[1.3fr_0.7fr]">
        <article className="rounded-[2rem] border border-[#dbe0ea] bg-[linear-gradient(135deg,#0f172a_0%,#111827_60%,#1f2937_100%)] p-7 text-white shadow-[0_24px_70px_rgba(15,23,42,0.18)]">
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-white/80 uppercase">
              {t("publicStatus")}
            </span>
            <StatusBadge state={currentState} />
          </div>

          <h1 className="mt-5 text-4xl leading-tight font-black tracking-[-0.03em] lg:text-6xl">
            {snapshot?.headline ?? t("statusDataUnavailable")}
          </h1>
          <p className="mt-4 max-w-3xl text-sm leading-7 text-white/80 lg:text-base">
            {heroSummary}
          </p>

          <div className="mt-7 flex flex-wrap gap-3">
            <PublicActionLink
              href={links.contact}
              className="rounded-full bg-white px-5 py-3 text-sm font-semibold text-[#111827] transition hover:bg-[#eef2f7]"
            >
              {t("contactSupport")}
            </PublicActionLink>
            <PublicActionLink
              href={links.changelog}
              className="rounded-full border border-white/20 bg-white/5 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              {t("viewChangelog")}
            </PublicActionLink>
          </div>
        </article>

        <aside className="rounded-[2rem] border border-[#dbe0ea] bg-white p-6 shadow-sm">
          <p className="text-xs font-bold tracking-[0.14em] text-[#667085] uppercase">
            {t("snapshot")}
          </p>
          <dl className="mt-5 grid gap-4">
            <div className="rounded-2xl bg-[#f8fafc] px-4 py-4">
              <dt className="text-xs font-bold tracking-[0.12em] text-[#768096] uppercase">
                {t("currentIncidents")}
              </dt>
              <dd className="mt-1 text-3xl font-black text-[#11131a]">
                {currentIncidents.length}
              </dd>
            </div>
            <div className="rounded-2xl bg-[#f8fafc] px-4 py-4">
              <dt className="text-xs font-bold tracking-[0.12em] text-[#768096] uppercase">
                {t("scheduledMaintenance")}
              </dt>
              <dd className="mt-1 text-3xl font-black text-[#11131a]">
                {scheduledMaintenance.length}
              </dd>
            </div>
            <div className="rounded-2xl bg-[#f8fafc] px-4 py-4">
              <dt className="text-xs font-bold tracking-[0.12em] text-[#768096] uppercase">
                {t("lastPublishedUpdate")}
              </dt>
              <dd className="mt-1 text-sm font-semibold text-[#11131a]">
                {generatedAt ?? t("recently")}
              </dd>
            </div>
          </dl>
        </aside>
      </section>

      <section className="mt-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-bold tracking-[0.16em] text-[#667085] uppercase">
              {t("componentStatus")}
            </p>
            <h2 className="mt-2 text-2xl font-black text-[#11131a]">
              {t("componentTitle")}
            </h2>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-[#556074]">
            {t("componentDescription")}
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
                {t("currentIncidents")}
              </p>
              <h2 className="mt-2 text-2xl font-black text-[#11131a]">
                {t("liveIncidents")}
              </h2>
            </div>
          </div>
          <div className="mt-4 space-y-4">
            {currentIncidents.length > 0 ? (
              currentIncidents.map((incident) => (
                <IncidentCard
                  key={`${incident.title}-${incident.started_at}`}
                  incident={incident}
                  supportingText={t("incidentSupportingText")}
                />
              ))
            ) : (
              <EmptySection
                title={t("noActiveIncidents")}
                description={t("noActiveIncidentsDescription")}
              />
            )}
          </div>
        </div>

        <div className="space-y-6">
          <div>
            <p className="text-[11px] font-bold tracking-[0.16em] text-[#667085] uppercase">
              {t("scheduledMaintenance")}
            </p>
            <h2 className="mt-2 text-2xl font-black text-[#11131a]">
              {t("plannedMaintenance")}
            </h2>
          </div>
          <div className="space-y-4">
            {scheduledMaintenance.length > 0 ? (
              scheduledMaintenance.map((incident) => (
                <IncidentCard
                  key={`${incident.title}-${incident.started_at}`}
                  incident={incident}
                  supportingText={t("maintenanceSupportingText")}
                />
              ))
            ) : (
              <EmptySection
                title={t("noScheduledMaintenance")}
                description={t("noScheduledMaintenanceDescription")}
              />
            )}
          </div>
        </div>
      </section>

      <section className="mt-10">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-bold tracking-[0.16em] text-[#667085] uppercase">
              {t("recentHistory")}
            </p>
            <h2 className="mt-2 text-2xl font-black text-[#11131a]">
              {t("recentlyResolvedIncidents")}
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
                  supportingText={t("historySupportingText")}
                />
              ))}
            </div>
          ) : (
            <EmptySection
              title={t("noRecentIncidents")}
              description={t("noRecentIncidentsDescription")}
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
            {t("refreshFailed")}
          </p>
        ) : null}
      </section>
    </div>
  );
}
