"use client";

import Link from "next/link";
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
const compactNumber = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

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
  const reports = [
    {
      title: "Answer quality",
      description: "Review confidence, grounding, and citation support.",
      href: "/reports/answer-quality",
      icon: <ShieldCheck className="h-5 w-5" aria-hidden />,
    },
    {
      title: "Usage & adoption",
      description: "Understand questions, activity, and feature engagement.",
      href: "/reports/usage-adoption",
      icon: <Users className="h-5 w-5" aria-hidden />,
    },
    {
      title: "Feedback & issues",
      description: "Follow feedback themes and reported answer issues.",
      href: "/reports/feedback-issues",
      icon: <MessageSquareText className="h-5 w-5" aria-hidden />,
    },
  ];
  return (
    <main className="grid gap-6">
      <ReportHeader
        title="Reports overview"
        description="Open your available quality, activity, and feedback reports from one place."
      />
      <section
        aria-label="Available reports"
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
              <ReportLink href={report.href} label="Open report" />
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}

export function UsageAdoptionDashboard() {
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
        title="Usage & Adoption"
        description="Track workspace activity, returning users, and engagement with core Rudix workflows."
      />
      <section
        aria-label="Usage key metrics"
        className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4"
      >
        <KpiCard
          label="Questions asked"
          value={compactNumber.format(questions)}
          description="Selected period"
        />
        <KpiCard
          label="Active users"
          value={compactNumber.format(users)}
          description="Unique users"
        />
        <KpiCard
          label="Agent runs"
          value={compactNumber.format(totals?.agent_runs ?? 0)}
          description="Agent workflow adoption"
        />
        <KpiCard
          label="Questions per user"
          value={users ? (questions / users).toFixed(1) : "0"}
          description="Average engagement"
        />
      </section>
      <section className="grid gap-5 xl:grid-cols-2" aria-label="Usage charts">
        <ChartCard
          title="Questions and active users"
          description="Weekly activity in the selected period"
        >
          <div
            className="h-72"
            role="img"
            aria-label="Questions and active users returned by the usage API"
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
          title="Feature adoption"
          description="Share of active users using each workflow"
        >
          <div
            className="h-72"
            role="img"
            aria-label="Feature adoption returned by the usage API"
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
                  formatter={(value) => [`${value}%`, "Adoption"]}
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
        caption="Top user adoption"
        columns={["User", "Active identities", "Questions", "Adoption"]}
        rows={(usage?.top_users ?? []).map((user) => [
          user.user_id,
          "1",
          compactNumber.format(user.questions),
          <StatusBadge key={user.user_id} label="Active" tone="healthy" />,
        ])}
      />
    </main>
  );
}

export function PermissionsAccessDashboard() {
  const { conflicts } = useReportBackendData();
  const items = conflicts?.items ?? [];
  const blocking = items.filter((item) =>
    ["blocking", "security_risk"].includes(item.severity),
  ).length;
  const warning = items.filter((item) => item.severity === "warning").length;
  const other = Math.max(0, (conflicts?.total ?? 0) - blocking - warning);
  const accessRisk = [
    { name: "Other", value: other, color: "#10b981" },
    { name: "Warning", value: warning, color: "#f59e0b" },
    { name: "Critical", value: blocking, color: "#f43f5e" },
  ];
  return (
    <main className="grid gap-6">
      <ReportHeader
        title="Permissions & Access"
        description="Review workspace access, permission conflicts, and organization-wide security posture."
      />
      <section
        aria-label="Access key metrics"
        className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4"
      >
        <KpiCard
          label="Open conflicts"
          value={String(conflicts?.total ?? 0)}
          description="Needs review"
        />
        <KpiCard
          label="Blocking conflicts"
          value={String(blocking)}
          description="Immediate attention"
        />
        <KpiCard
          label="Warnings"
          value={String(warning)}
          description="Permission anomalies"
        />
        <KpiCard
          label="Loaded conflicts"
          value={String(items.length)}
          description="Current backend page"
        />
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <ChartCard
          title="Access posture"
          description="Current permission health across workspace resources"
        >
          <div
            className="h-72"
            role="img"
            aria-label="Permission conflict severity distribution returned by the backend"
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
                  formatter={(value) => [`${value}%`, "Resources"]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
        <RecommendedActionCard
          title="Resolve blocking conflicts"
          description={`${blocking} access rule${blocking === 1 ? "" : "s"} can expose or hide sources incorrectly. Review matched grants and denies before the next permission sync.`}
          priority="High"
          impact="Restore safe source access"
          related="Admin permissions"
          action={
            <ReportLink href="/admin/permissions" label="Review conflicts" />
          }
        />
      </div>
      <ReportDataTable
        caption="Permission conflicts"
        columns={["Conflict", "Resource", "Severity", "Status"]}
        rows={items.map((item) => [
          item.conflict_summary ?? item.conflict_type,
          `${item.resource_type}${item.resource_id ? ` · ${item.resource_id}` : ""}`,
          <StatusBadge
            key={item.id}
            label={item.severity.replaceAll("_", " ")}
            tone={
              ["blocking", "security_risk"].includes(item.severity)
                ? "critical"
                : item.severity === "warning"
                  ? "warning"
                  : "neutral"
            }
          />,
          item.status,
        ])}
      />
    </main>
  );
}

export function KnowledgeGapsDashboard() {
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
        title="Knowledge Gaps"
        description="Identify recurring unanswered topics and prioritize the sources that will improve coverage most."
      />
      <section
        aria-label="Knowledge gap key metrics"
        className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4"
      >
        <KpiCard
          label="Open gaps"
          value={String(gaps?.total ?? 0)}
          description="Across all collections"
        />
        <KpiCard
          label="Unanswered queries"
          value={String(analytics?.unanswered_queries ?? 0)}
          description="Selected period"
        />
        <KpiCard
          label="Low-confidence topics"
          value={String(lowConfidence)}
          description="Needs stronger evidence"
        />
        <KpiCard
          label="Loaded topics"
          value={String(items.length)}
          description="Prioritized backend results"
        />
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <ChartCard
          title="Top gap topics"
          description="Occurrences grouped by knowledge area"
        >
          <div
            className="h-72"
            role="img"
            aria-label="Top knowledge gaps returned by the backend"
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
          title={`Add guidance for ${items[0]?.topic_label ?? "the leading gap"}`}
          description={`${items[0]?.topic_label ?? "The leading topic"} is the largest unresolved cluster in the current filtered results.`}
          priority="High"
          impact={`Address ${items[0]?.occurrence_count ?? 0} recurring queries`}
          related={items[0]?.collection_id ?? "Unassigned collection"}
          action={<ReportLink href="/documents" label="Add source" />}
        />
      </div>
      <ReportDataTable
        caption="Knowledge gap details"
        columns={["Topic", "Example query", "Occurrences", "Status"]}
        rows={items.map((item) => [
          item.topic_label,
          item.example_query ?? "No example query stored",
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
