"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  ArrowRight,
  MessageSquareText,
  ShieldCheck,
  Users,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChartCard,
  KpiCard,
  RecommendedActionCard,
  ReportDataTable,
  ReportHeader,
  StatusBadge,
} from "@/components/reports/report-ui";
import { useReportBackendData } from "@/components/reports/ReportBackendData";

const tooltipStyle = {
  border: "1px solid #dfdced",
  borderRadius: "8px",
  boxShadow: "0 4px 14px rgb(42 38 64 / 0.12)",
  color: "#2a2640",
  fontSize: "12px",
};

const axisTick = { fill: "#777287", fontSize: 11 };
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
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={usageTrend}
                margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
              >
                <CartesianGrid
                  vertical={false}
                  stroke="#ebe8f4"
                  strokeDasharray="3 3"
                />
                <XAxis
                  dataKey="period"
                  tick={axisTick}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis tick={axisTick} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Line
                  type="monotone"
                  dataKey="questions"
                  stroke="#4434c7"
                  strokeWidth={3}
                  dot={{ fill: "#4434c7", r: 4 }}
                />
                <Line
                  type="monotone"
                  dataKey="users"
                  stroke="#10b981"
                  strokeWidth={2}
                  dot={{ fill: "#10b981", r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
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
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={featureAdoption}
                layout="vertical"
                margin={{ top: 4, right: 24, left: 8, bottom: 0 }}
              >
                <XAxis type="number" hide domain={[0, 100]} />
                <YAxis
                  type="category"
                  dataKey="feature"
                  width={82}
                  tick={axisTick}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(value) => [`${value}%`, p("adoption")]}
                />
                <Bar
                  dataKey="adoption"
                  fill="#6254d9"
                  radius={[0, 5, 5, 0]}
                  background={{ fill: "#ece9f7", radius: 5 }}
                />
              </BarChart>
            </ResponsiveContainer>
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
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={accessRisk}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={66}
                  outerRadius={98}
                  paddingAngle={3}
                >
                  {accessRisk.map((item) => (
                    <Cell key={item.name} fill={item.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(value) => [`${value}%`, p("resources")]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
        <RecommendedActionCard
          title={p("actionTitle")}
          description={p("actionDescription", { count: blocking })}
          priority={p("high")}
          impact={p("actionImpact")}
          related={p("actionRelated")}
          action={
            <ReportLink
              href="/admin/permissions"
              label={p("reviewConflicts")}
            />
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
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={gapTopics}
                margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
              >
                <CartesianGrid
                  vertical={false}
                  stroke="#ebe8f4"
                  strokeDasharray="3 3"
                />
                <XAxis
                  dataKey="topic"
                  tick={axisTick}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis tick={axisTick} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar
                  dataKey="occurrences"
                  fill="#6254d9"
                  radius={[5, 5, 0, 0]}
                  maxBarSize={64}
                />
              </BarChart>
            </ResponsiveContainer>
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
            label={item.status.replaceAll("_", " ")}
            tone={item.status === "open" ? "critical" : "warning"}
          />,
        ])}
      />
    </main>
  );
}
