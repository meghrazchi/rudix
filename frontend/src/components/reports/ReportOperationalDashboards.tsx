"use client";

import type { ComponentType } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  ArrowRight,
  MessageSquareText,
  ShieldCheck,
  Users,
} from "lucide-react";
import dynamic from "next/dynamic";
import { SkeletonBlock } from "@/components/states/SkeletonBlock";
import {
  ChartCard,
  KpiCard,
  RecommendedActionCard,
  ReportDataTable,
  ReportHeader,
  StatusBadge,
} from "@/components/reports/report-ui";
import { useReportBackendData } from "@/components/reports/ReportBackendData";

// recharts loads on demand (R07-03); the wrapper keeps the chart height.
function lazyChart<P extends object>(load: () => Promise<ComponentType<P>>) {
  return dynamic<P>(load, {
    ssr: false,
    loading: () => <SkeletonBlock rows={6} className="h-full" />,
  });
}

const UsageTrendChart = lazyChart(() =>
  import("@/components/reports/ReportOperationalCharts").then(
    (module) => module.UsageTrendChart,
  ),
);
const FeatureAdoptionChart = lazyChart(() =>
  import("@/components/reports/ReportOperationalCharts").then(
    (module) => module.FeatureAdoptionChart,
  ),
);
const AccessPostureChart = lazyChart(() =>
  import("@/components/reports/ReportOperationalCharts").then(
    (module) => module.AccessPostureChart,
  ),
);
const GapTopicsChart = lazyChart(() =>
  import("@/components/reports/ReportOperationalCharts").then(
    (module) => module.GapTopicsChart,
  ),
);

function ReportLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 text-sm font-bold text-[#4434c7]"
    >
      {label} <ArrowRight className="h-4 w-4" aria-hidden />
    </Link>
  );
}

export function PersonalReportsOverview() {
  const t = useTranslations("reports");
  const p = useTranslations("reports.pages");
  const reports = [
    {
      title: t("sections.answer-quality.label"),
      description: p("personal.answerQuality"),
      href: "/reports/answer-quality",
      icon: <ShieldCheck className="h-5 w-5" aria-hidden />,
    },
    {
      title: t("sections.usage-adoption.label"),
      description: p("personal.usage"),
      href: "/reports/usage-adoption",
      icon: <Users className="h-5 w-5" aria-hidden />,
    },
    {
      title: t("sections.feedback-issues.label"),
      description: p("personal.feedback"),
      href: "/reports/feedback-issues",
      icon: <MessageSquareText className="h-5 w-5" aria-hidden />,
    },
  ];
  return (
    <main className="grid gap-6">
      <ReportHeader
        title={t("sections.overview.label")}
        description={t("sections.overview.description")}
      />
      <section
        aria-label={p("personal.available")}
        className="grid gap-5 md:grid-cols-2 xl:grid-cols-3"
      >
        {reports.map((report) => (
          <article
            key={report.href}
            className="flex min-h-48 flex-col rounded-xl border border-[#dfdced] bg-white p-5 shadow-sm lg:p-6"
          >
            <span className="grid h-10 w-10 place-items-center rounded-lg bg-[#ece9ff] text-[#4434c7]">
              {report.icon}
            </span>
            <h2 className="mt-5 text-lg font-bold text-[#2a2640]">
              {report.title}
            </h2>
            <p className="mt-2 flex-1 text-sm leading-6 text-[#68647b]">
              {report.description}
            </p>
            <div className="mt-5">
              <ReportLink href={report.href} label={p("personal.open")} />
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}

export function UsageAdoptionDashboard() {
  const t = useTranslations("reports");
  const p = useTranslations("reports.pages.usage");
  const locale = useLocale();
  const compactNumber = new Intl.NumberFormat(locale, {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  const { usage } = useReportBackendData();
  const totals = usage?.totals;
  const usageTrend = (usage?.series ?? []).map((point) => ({
    period: point.period_start,
    questions: point.questions_asked,
    users: point.active_users,
  }));
  const featureAdoption = Object.entries(
    usage?.feature_area_breakdown ?? {},
  ).map(([feature, adoption]) => ({ feature, adoption }));
  const questions = totals?.questions_asked ?? 0;
  const users = totals?.active_users ?? 0;
  return (
    <main className="grid gap-6">
      <ReportHeader
        title={t("sections.usage-adoption.label")}
        description={t("sections.usage-adoption.description")}
      />
      <section
        aria-label={p("metrics")}
        className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4"
      >
        <KpiCard
          label={p("questions")}
          value={compactNumber.format(questions)}
          description={p("selectedPeriod")}
        />
        <KpiCard
          label={p("activeUsers")}
          value={compactNumber.format(users)}
          description={p("uniqueUsers")}
        />
        <KpiCard
          label={p("agentRuns")}
          value={compactNumber.format(totals?.agent_runs ?? 0)}
          description={p("agentAdoption")}
        />
        <KpiCard
          label={p("questionsPerUser")}
          value={users ? (questions / users).toFixed(1) : "0"}
          description={p("averageEngagement")}
        />
      </section>
      <section className="grid gap-5 xl:grid-cols-2" aria-label={p("charts")}>
        <ChartCard
          title={p("activityTitle")}
          description={p("activityDescription")}
        >
          <div
            className="h-72"
            role="img"
            aria-label={p("activityAria")}
            data-chart-library="recharts"
          >
            <UsageTrendChart data={usageTrend} />
          </div>
        </ChartCard>
        <ChartCard
          title={p("adoptionTitle")}
          description={p("adoptionDescription")}
        >
          <div
            className="h-72"
            role="img"
            aria-label={p("adoptionAria")}
            data-chart-library="recharts"
          >
            <FeatureAdoptionChart
              data={featureAdoption}
              adoptionLabel={p("adoption")}
            />
          </div>
        </ChartCard>
      </section>
      <ReportDataTable
        caption={p("tableCaption")}
        columns={[p("user"), p("identities"), p("questions"), p("adoption")]}
        rows={(usage?.top_users ?? []).map((user) => [
          user.user_id,
          "1",
          compactNumber.format(user.questions),
          <StatusBadge key={user.user_id} label={p("active")} tone="healthy" />,
        ])}
      />
    </main>
  );
}

export function PermissionsAccessDashboard() {
  const t = useTranslations("reports");
  const p = useTranslations("reports.pages.permissions");
  const { conflicts } = useReportBackendData();
  const items = conflicts?.items ?? [];
  const blocking = items.filter((item) =>
    ["blocking", "security_risk"].includes(item.severity),
  ).length;
  const warning = items.filter((item) => item.severity === "warning").length;
  const other = Math.max(0, (conflicts?.total ?? 0) - blocking - warning);
  const accessRisk = [
    { name: p("other"), value: other, color: "#10b981" },
    { name: p("warning"), value: warning, color: "#f59e0b" },
    { name: p("critical"), value: blocking, color: "#f43f5e" },
  ];
  return (
    <main className="grid gap-6">
      <ReportHeader
        title={t("sections.permissions-access.label")}
        description={t("sections.permissions-access.description")}
      />
      <section
        aria-label={p("metrics")}
        className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4"
      >
        <KpiCard
          label={p("openConflicts")}
          value={String(conflicts?.total ?? 0)}
          description={p("needsReview")}
        />
        <KpiCard
          label={p("blockingConflicts")}
          value={String(blocking)}
          description={p("immediateAttention")}
        />
        <KpiCard
          label={p("warnings")}
          value={String(warning)}
          description={p("anomalies")}
        />
        <KpiCard
          label={p("loadedConflicts")}
          value={String(items.length)}
          description={p("backendPage")}
        />
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <ChartCard
          title={p("postureTitle")}
          description={p("postureDescription")}
        >
          <div
            className="h-72"
            role="img"
            aria-label={p("postureAria")}
            data-chart-library="recharts"
          >
            <AccessPostureChart
              data={accessRisk}
              resourcesLabel={p("resources")}
            />
          </div>
        </ChartCard>
        <RecommendedActionCard
          title={p("actionTitle")}
          description={p("actionDescription", { count: blocking })}
          priority={p("high")}
          impact={p("actionImpact")}
          related={p("actionRelated")}
          action={
            <div className="flex flex-wrap gap-3">
              <ReportLink
                href="/admin/permissions"
                label={p("reviewConflicts")}
              />
              <ReportLink
                href="/admin/permissions-access"
                label={p("viewAccessReport")}
              />
            </div>
          }
        />
      </div>
      <ReportDataTable
        caption={p("tableCaption")}
        columns={[p("conflict"), p("resource"), p("severity"), p("status")]}
        rows={items.map((item) => [
          item.conflict_summary ?? item.conflict_type,
          `${item.resource_type}${item.resource_id ? ` · ${item.resource_id}` : ""}`,
          <StatusBadge
            key={item.id}
            label={p(`severityLabels.${item.severity}`)}
            tone={
              ["blocking", "security_risk"].includes(item.severity)
                ? "critical"
                : item.severity === "warning"
                  ? "warning"
                  : "neutral"
            }
          />,
          p(`statusLabels.${item.status}`),
        ])}
      />
    </main>
  );
}

export function KnowledgeGapsDashboard() {
  const t = useTranslations("reports");
  const p = useTranslations("reports.pages.gaps");
  const { gaps, analytics } = useReportBackendData();
  const items = gaps?.items ?? [];
  const gapTopics = items.map((item) => ({
    topic: item.topic_label,
    occurrences: item.occurrence_count,
  }));
  const lowConfidence = items.filter(
    (item) => item.gap_type === "low_confidence",
  ).length;
  return (
    <main className="grid gap-6">
      <ReportHeader
        title={t("sections.knowledge-gaps.label")}
        description={t("sections.knowledge-gaps.description")}
      />
      <section
        aria-label={p("metrics")}
        className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4"
      >
        <KpiCard
          label={p("openGaps")}
          value={String(gaps?.total ?? 0)}
          description={p("allCollections")}
        />
        <KpiCard
          label={p("unanswered")}
          value={String(analytics?.unanswered_queries ?? 0)}
          description={p("selectedPeriod")}
        />
        <KpiCard
          label={p("lowConfidence")}
          value={String(lowConfidence)}
          description={p("strongerEvidence")}
        />
        <KpiCard
          label={p("loadedTopics")}
          value={String(items.length)}
          description={p("backendResults")}
        />
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <ChartCard title={p("chartTitle")} description={p("chartDescription")}>
          <div
            className="h-72"
            role="img"
            aria-label={p("chartAria")}
            data-chart-library="recharts"
          >
            <GapTopicsChart data={gapTopics} />
          </div>
        </ChartCard>
        <RecommendedActionCard
          title={p("actionTitle", {
            topic: items[0]?.topic_label ?? p("leadingGap"),
          })}
          description={p("actionDescription", {
            topic: items[0]?.topic_label ?? p("leadingTopic"),
          })}
          priority={p("high")}
          impact={p("actionImpact", { count: items[0]?.occurrence_count ?? 0 })}
          related={items[0]?.collection_id ?? p("unassigned")}
          action={<ReportLink href="/documents" label={p("addSource")} />}
        />
      </div>
      <ReportDataTable
        caption={p("tableCaption")}
        columns={[p("topic"), p("example"), p("occurrences"), p("status")]}
        rows={items.map((item) => [
          item.topic_label,
          item.example_query ?? p("noExample"),
          String(item.occurrence_count),
          <StatusBadge
            key={item.gap_id}
            label={p(`statusLabels.${item.status}`)}
            tone={item.status === "open" ? "critical" : "warning"}
          />,
        ])}
      />
    </main>
  );
}
