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
  operational:
    "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300",
  degraded:
    "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300",
  outage:
    "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300",
  maintenance:
    "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-300",
  unknown: "border-site-border bg-site-muted text-site-ink-muted",
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
      className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-bold tracking-[0.12em] uppercase ${STATE_BADGE_CLASSES[state]}`}
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
    <article className="border-site-border bg-site-surface rounded-2xl border p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-site-ink-subtle text-xs font-medium tracking-wide uppercase">
            {incident.kind === "maintenance" ? t("maintenance") : t("incident")}
          </p>
          <h3 className="text-site-ink mt-1 text-lg font-semibold">
            {incident.title}
          </h3>
        </div>
        <StatusBadge state={incidentBadgeState(incident)} />
      </div>

      <p className="text-site-ink-muted mt-3 text-sm leading-6">
        {incident.message ?? t("updatePending")}
      </p>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-site-ink-subtle text-xs font-medium">
            {t("services")}
          </dt>
          <dd className="text-site-ink mt-1">{services}</dd>
        </div>
        <div>
          <dt className="text-site-ink-subtle text-xs font-medium">
            {t("severity")}
          </dt>
          <dd className="text-site-ink mt-1">{incident.severity}</dd>
        </div>
        <div>
          <dt className="text-site-ink-subtle text-xs font-medium">
            {t("started")}
          </dt>
          <dd className="text-site-ink mt-1">
            {startedAt
              ? format.dateTime(startedAt, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })
              : t("recently")}
          </dd>
        </div>
        <div>
          <dt className="text-site-ink-subtle text-xs font-medium">
            {t("resolved")}
          </dt>
          <dd className="text-site-ink mt-1">
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
        <p className="text-site-ink-subtle mt-4 text-xs leading-5">
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
    <article className="border-site-border bg-site-surface rounded-2xl border p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-site-ink text-base font-semibold">{label}</h3>
          <p className="text-site-ink-muted mt-1 text-sm leading-6">
            {summary}
          </p>
        </div>
        <StatusBadge state={status} />
      </div>

      <div className="bg-site-canvas text-site-ink-muted mt-4 rounded-xl px-4 py-3 text-sm">
        <p className="font-semibold">{t("affectedServices")}</p>
        <p className="mt-1">
          {services.length > 0 ? services.join(", ") : t("noneReported")}
        </p>
      </div>

      <p className="text-site-ink-subtle mt-3 text-xs">
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
    <div className="border-site-border bg-site-surface text-site-ink-muted rounded-2xl border border-dashed px-5 py-6 text-sm">
      <h3 className="text-site-ink text-base font-semibold">{title}</h3>
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
    <div className="bg-site-canvas text-site-ink">
      <div className="mx-auto w-full max-w-6xl px-4 py-14 lg:px-8 lg:py-20">
        <section
          aria-labelledby="status-hero-title"
          className="grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_0.6fr]"
        >
          <article className="border-site-border bg-site-surface min-w-0 rounded-3xl border p-7 md:p-10">
            <div className="flex flex-wrap items-center gap-3">
              <span className="border-site-border text-site-ink-muted rounded-full border px-3 py-1 text-xs font-medium">
                {t("publicStatus")}
              </span>
              <StatusBadge state={currentState} />
            </div>

            <h1
              id="status-hero-title"
              className="text-site-ink mt-6 text-4xl font-semibold tracking-[-0.03em] text-balance break-words hyphens-auto lg:text-5xl lg:hyphens-manual"
            >
              {snapshot?.headline ?? t("statusDataUnavailable")}
            </h1>
            <p className="text-site-ink-muted mt-4 max-w-3xl text-base leading-7">
              {heroSummary}
            </p>

            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <PublicActionLink
                href={links.contact}
                className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover inline-flex h-11 items-center justify-center rounded-full px-6 text-sm font-medium transition-colors"
              >
                {t("contactSupport")}
              </PublicActionLink>
              <PublicActionLink
                href={links.changelog}
                className="border-site-border bg-site-surface text-site-ink hover:bg-site-muted inline-flex h-11 items-center justify-center rounded-full border px-6 text-sm font-medium transition-colors"
              >
                {t("viewChangelog")}
              </PublicActionLink>
            </div>
          </article>

          <aside className="border-site-border bg-site-surface rounded-3xl border p-6">
            <p className="text-site-ink-subtle text-xs font-medium tracking-wide uppercase">
              {t("snapshot")}
            </p>
            <dl className="mt-5 grid gap-3">
              <div className="bg-site-canvas rounded-2xl px-4 py-4">
                <dt className="text-site-ink-subtle text-xs font-medium">
                  {t("currentIncidents")}
                </dt>
                <dd className="text-site-ink mt-1 text-3xl font-semibold">
                  {currentIncidents.length}
                </dd>
              </div>
              <div className="bg-site-canvas rounded-2xl px-4 py-4">
                <dt className="text-site-ink-subtle text-xs font-medium">
                  {t("scheduledMaintenance")}
                </dt>
                <dd className="text-site-ink mt-1 text-3xl font-semibold">
                  {scheduledMaintenance.length}
                </dd>
              </div>
              <div className="bg-site-canvas rounded-2xl px-4 py-4">
                <dt className="text-site-ink-subtle text-xs font-medium">
                  {t("lastPublishedUpdate")}
                </dt>
                <dd className="text-site-ink mt-1 text-sm font-medium">
                  {generatedAt ?? t("recently")}
                </dd>
              </div>
            </dl>
          </aside>
        </section>

        <section className="mt-10">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-site-accent-ink text-xs font-semibold tracking-[0.08em] uppercase">
                {t("componentStatus")}
              </p>
              <h2 className="text-site-ink mt-2 text-2xl font-semibold tracking-tight">
                {t("componentTitle")}
              </h2>
            </div>
            <p className="text-site-ink-muted max-w-2xl text-sm leading-6">
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

        <section className="mt-10 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div>
            <div className="flex items-end justify-between gap-3">
              <div>
                <p className="text-site-accent-ink text-xs font-semibold tracking-[0.08em] uppercase">
                  {t("currentIncidents")}
                </p>
                <h2 className="text-site-ink mt-2 text-2xl font-semibold tracking-tight">
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
              <p className="text-site-accent-ink text-xs font-semibold tracking-[0.08em] uppercase">
                {t("scheduledMaintenance")}
              </p>
              <h2 className="text-site-ink mt-2 text-2xl font-semibold tracking-tight">
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
              <p className="text-site-accent-ink text-xs font-semibold tracking-[0.08em] uppercase">
                {t("recentHistory")}
              </p>
              <h2 className="text-site-ink mt-2 text-2xl font-semibold tracking-tight">
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

        <section className="border-site-border bg-site-surface mt-10 rounded-3xl border px-6 py-5">
          <p className="text-site-ink-muted text-sm leading-7">
            {snapshot?.uptime_notice ?? ""}
          </p>
          {loadError ? (
            <p className="mt-3 text-sm font-medium text-amber-700 dark:text-amber-300">
              {t("refreshFailed")}
            </p>
          ) : null}
        </section>
      </div>
    </div>
  );
}
