"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useLocale } from "next-intl";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { canViewAdminUsage } from "@/lib/dashboard";
import { useAuthSession } from "@/lib/use-auth-session";
import type { SupportedLocale } from "@/i18n/routing";
import { createAdminLandingTranslations } from "./admin-landing-translations";

type CardStatus =
  | "available"
  | "unavailable"
  | "online"
  | "active"
  | "configurable";

const STATUS_CLASS: Record<CardStatus, string> = {
  available: "text-emerald-600 bg-emerald-50 border border-emerald-100",
  unavailable: "text-amber-600 bg-amber-50 border border-amber-100",
  online: "text-emerald-600 bg-emerald-50 border border-emerald-100",
  active: "text-emerald-600 bg-emerald-50 border border-emerald-100",
  configurable: "text-indigo-600 bg-indigo-50 border border-indigo-100",
};

function trimToNull(value: string | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function LargeCard({
  title,
  description,
  href,
  status,
  icon,
  actionLabel,
}: {
  title: string;
  description: string;
  href: string;
  status: CardStatus;
  icon: ReactNode;
  actionLabel: string;
}) {
  const locale = useLocale() as SupportedLocale;
  const translations = createAdminLandingTranslations(locale);
  const isUnavailable = status === "unavailable";
  return (
    <div
      className={`flex flex-col rounded-xl border p-6 transition-all duration-200 ${
        isUnavailable
          ? "border-slate-200 bg-slate-50 opacity-80 shadow-none"
          : "border-slate-200 bg-white shadow-sm hover:border-indigo-500 hover:shadow-md"
      }`}
    >
      <div className="mb-4 flex items-start justify-between">
        <div className={isUnavailable ? "text-slate-400" : "text-indigo-600"}>
          {icon}
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${STATUS_CLASS[status]}`}
        >
          {translations[status]}
        </span>
      </div>
      <h5 className="mb-2 text-base font-bold text-slate-900">
        {translations.text(title)}
      </h5>
      <p className="mb-6 flex-grow text-sm leading-relaxed text-slate-500">
        {locale === "en" ? description : translations.description}
      </p>
      {isUnavailable ? (
        <Link
          href={href}
          className="inline-flex w-full cursor-not-allowed items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-400"
        >
          {translations.setup}
        </Link>
      ) : (
        <Link
          href={href}
          className="inline-flex w-full items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50"
        >
          {locale === "en"
            ? actionLabel
            : `${translations.open} ${translations.text(title)}`}
          <svg
            className="ml-2 h-4 w-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
            />
          </svg>
        </Link>
      )}
    </div>
  );
}

function SmallCard({
  title,
  description,
  href,
  status,
  actionLabel,
}: {
  title: string;
  description: string;
  href: string;
  status: CardStatus;
  actionLabel: string;
}) {
  const locale = useLocale() as SupportedLocale;
  const translations = createAdminLandingTranslations(locale);
  return (
    <div className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-200 hover:border-indigo-500 hover:shadow-md">
      <span
        className={`mb-3 w-max rounded-full px-2 py-0.5 text-[9px] font-bold ${STATUS_CLASS[status]}`}
      >
        {translations[status]}
      </span>
      <h5 className="mb-1 text-sm font-bold text-slate-900">
        {translations.text(title)}
      </h5>
      <p className="mb-4 flex-grow text-xs leading-relaxed text-slate-500">
        {locale === "en" ? description : translations.description}
      </p>
      <Link
        href={href}
        className="inline-flex items-center text-xs font-semibold text-indigo-600 hover:text-indigo-700"
      >
        {locale === "en"
          ? actionLabel
          : `${translations.open} ${translations.text(title)}`}
        <svg
          className="ml-1 h-3 w-3"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            d="M9 5l7 7-7 7"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
          />
        </svg>
      </Link>
    </div>
  );
}

function HorizontalCard({
  title,
  description,
  href,
  icon,
  actionLabel,
}: {
  title: string;
  description: string;
  href: string;
  icon: ReactNode;
  actionLabel: string;
}) {
  const locale = useLocale() as SupportedLocale;
  const translations = createAdminLandingTranslations(locale);
  return (
    <div className="flex flex-col rounded-xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-200 hover:border-indigo-500 hover:shadow-md">
      <div className="flex items-start justify-between">
        <div className="flex items-center space-x-4">
          <div className="rounded-lg bg-slate-50 p-3 text-slate-600">
            {icon}
          </div>
          <div>
            <h5 className="text-base font-bold text-slate-900">
              {translations.text(title)}
            </h5>
            <p className="mt-0.5 text-sm text-slate-500">
              {locale === "en" ? description : translations.description}
            </p>
          </div>
        </div>
        <Link
          href={href}
          className="ml-4 flex-shrink-0 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700"
        >
          {locale === "en" ? actionLabel : translations.open}
        </Link>
      </div>
    </div>
  );
}

function SectionHeader({ icon, title }: { icon: ReactNode; title: string }) {
  const translations = createAdminLandingTranslations(
    useLocale() as SupportedLocale,
  );
  return (
    <div className="mb-6 flex items-center space-x-2">
      <div className="rounded-lg bg-indigo-100 p-1.5 text-indigo-600">
        {icon}
      </div>
      <h4 className="text-lg font-bold tracking-tight text-slate-900">
        {translations.text(title)}
      </h4>
    </div>
  );
}

export function AdminLandingPage() {
  const translations = createAdminLandingTranslations(
    useLocale() as SupportedLocale,
  );
  const { state } = useAuthSession();
  const role = state.session?.role;

  const monitoringUrl = trimToNull(
    process.env.NEXT_PUBLIC_ADMIN_MONITORING_URL,
  );

  if (!canViewAdminUsage(role)) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={translations.restricted}
          description={translations.restrictedDescription}
          compact={false}
        />
      </section>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-slate-50/50">
      <div className="mx-auto max-w-7xl p-8">
        {/* Hero */}
        <section className="relative mb-10 overflow-hidden rounded-2xl border border-slate-200 bg-white p-10 shadow-sm">
          <div className="absolute -top-12 -right-12 h-64 w-64 rounded-full bg-indigo-50 opacity-50 transition-transform duration-500 group-hover:scale-110" />
          <div className="relative z-10">
            <div className="mb-4 flex items-center space-x-3">
              <span className="rounded-full bg-indigo-100 px-3 py-1 text-[10px] font-bold tracking-wider text-indigo-700 uppercase">
                {translations.hub}
              </span>
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <span className="text-xs font-medium text-slate-500 italic">
                {translations.deployment}
              </span>
            </div>
            <h1 className="mb-4 text-4xl font-extrabold tracking-tight text-slate-900">
              {translations.title}
            </h1>
            <p className="max-w-2xl text-lg leading-relaxed text-slate-600">
              {translations.intro}
            </p>
          </div>
        </section>

        <div className="space-y-12">
          {/* Analytics & Insights */}
          <div>
            <SectionHeader
              title="Analytics & Insights"
              icon={
                <svg
                  className="h-5 w-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                  />
                </svg>
              }
            />
            <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
              <LargeCard
                title="Usage Analytics"
                description="Inspect token consumption, estimated cost distributions, top users, and performance trends over time."
                href="/admin/usage"
                status="available"
                actionLabel="Open Usage"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <LargeCard
                title="Observability Dashboard"
                description="API error rates, LLM health, indexing reliability, and storage metrics in one consolidated view."
                href="/admin/observability"
                status="available"
                actionLabel="Open Dashboard"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <LargeCard
                title="Service Monitoring"
                description="External service monitoring and alerting dashboards for incident response and uptime visibility."
                href="/admin/monitoring"
                status={monitoringUrl ? "available" : "unavailable"}
                actionLabel="Open Monitoring"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
            </div>
          </div>

          {/* Security & Compliance */}
          <div>
            <SectionHeader
              title="Security & Compliance"
              icon={
                <svg
                  className="h-5 w-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                  />
                </svg>
              }
            />
            <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
              <LargeCard
                title="Audit Logs"
                description="Immutable review of security and product activity across all administrative and operational events."
                href="/admin/audit-logs"
                status="available"
                actionLabel="Open Logs"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <LargeCard
                title="Security Center"
                description="Monitor security posture, active access controls, active warnings, and unresolved vulnerability flags."
                href="/admin/security-center"
                status="available"
                actionLabel="Open Security"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <LargeCard
                title="Agent Governance"
                description="Manage agent modes, MCP tool exposure, tool allowlists, provider security, and runtime budgets."
                href="/admin/governance"
                status="available"
                actionLabel="Manage Policies"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                    <path
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <LargeCard
                title="Org Memory"
                description="Review reusable workflow memory, verified knowledge links, and source-scoped defaults."
                href="/admin/memory"
                status="available"
                actionLabel="Open Memory"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M12 6v12m6-6H6m12-3H6m12 6H6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
            </div>
          </div>

          {/* AI & Model Management */}
          <div>
            <SectionHeader
              title="AI & Model Management"
              icon={
                <svg
                  className="h-5 w-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                  />
                </svg>
              }
            />
            <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
              <LargeCard
                title="Model Provider Settings"
                description="Configure org-scoped LLM providers, models, timeouts, retry policies, and fallback chains."
                href="/admin/model-provider"
                status="available"
                actionLabel="Configure Providers"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <LargeCard
                title="Model Diagnostics"
                description="Test provider connectivity, inspect capability badges, and verify model health before deployments."
                href="/admin/model-diagnostics"
                status="available"
                actionLabel="Run Diagnostics"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <LargeCard
                title="Safety Evaluations"
                description="Run AI safety red-team evaluation suites, review violation reports, and track evaluation run history."
                href="/admin/safety-evals"
                status="available"
                actionLabel="View Evaluations"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
            </div>
          </div>

          {/* Operations & Infrastructure */}
          <div>
            <SectionHeader
              title="Operations & Infrastructure"
              icon={
                <svg
                  className="h-5 w-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                  />
                </svg>
              }
            />
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
              <SmallCard
                title="System Health"
                description="Live API readiness and service status from deployed environment."
                href="/admin/system-health"
                status="online"
                actionLabel="Open Health"
              />
              <SmallCard
                title="Feedback Review Queue"
                description="Triage answer feedback, assign severity, and resolve knowledge gaps."
                href="/admin/feedback-review"
                status="available"
                actionLabel="View Queue"
              />
              <SmallCard
                title="Document Deletion"
                description="Monitor and retry deletions in progress, failed, or blocked by retention policy."
                href="/admin/documents/deletion"
                status="active"
                actionLabel="Open Status"
              />
              <SmallCard
                title="Feature Flags"
                description="Override environment-level flags per org and audit rollout changes."
                href="/admin/feature-flags"
                status="configurable"
                actionLabel="Manage Flags"
              />
              <SmallCard
                title="Failed Jobs"
                description="Inspect failed background tasks, view error details, and trigger bulk retries."
                href="/admin/failed-jobs"
                status="available"
                actionLabel="View Jobs"
              />
              <SmallCard
                title="Status & Incidents"
                description="Manage incidents, service snapshots, and the public status banner."
                href="/admin/status"
                status="available"
                actionLabel="Open Status"
              />
              <SmallCard
                title="Quotas & Rate Limits"
                description="Manage org quota policies, usage overrides, and rate-limit warnings."
                href="/admin/quotas"
                status="configurable"
                actionLabel="Manage Quotas"
              />
              <SmallCard
                title="Data Portability"
                description="Request sanitized workspace exports, validate imports, and download completed artifacts."
                href="/admin/portability"
                status="available"
                actionLabel="Open Portability"
              />
            </div>
          </div>

          {/* Identity & Access */}
          <div className="pb-12">
            <SectionHeader
              title="Identity & Access"
              icon={
                <svg
                  className="h-5 w-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                  />
                </svg>
              }
            />
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <HorizontalCard
                title="Team Management"
                description="Invite members, manage roles, and track pending invitations."
                href="/admin/team"
                actionLabel="Open Team"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <HorizontalCard
                title="API Access Keys"
                description="Create scoped keys for programmatic and integration access."
                href="/admin/api-keys"
                actionLabel="Manage Keys"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <HorizontalCard
                title="Roles & Permissions"
                description="Manage built-in roles, create custom permission sets, and audit role assignments."
                href="/admin/roles"
                actionLabel="Manage Roles"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <HorizontalCard
                title="Access Management"
                description="View and edit the role permission matrix. Grant or revoke explicit resource-level access for users, teams, and groups."
                href="/admin/permissions"
                actionLabel="Manage Access"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <HorizontalCard
                title="Access Debugger"
                description="Simulate the authorization policy engine to see exactly why a user can or cannot access any resource. Full reason chain and audit log."
                href="/admin/access-debugger"
                actionLabel="Open Debugger"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M10 21h7a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v11m0 5l4.879-4.879m0 0a3 3 0 104.243-4.242 3 3 0 00-4.243 4.242z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <HorizontalCard
                title="SSO / SAML"
                description="Configure enterprise single sign-on, SAML settings, and email-domain discovery."
                href="/admin/sso"
                actionLabel="Configure SSO"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
              <HorizontalCard
                title="SCIM Provisioning"
                description="Configure automated user provisioning, domain verification, and deprovisioning policies."
                href="/admin/scim"
                actionLabel="Configure SCIM"
                icon={
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                    />
                  </svg>
                }
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
