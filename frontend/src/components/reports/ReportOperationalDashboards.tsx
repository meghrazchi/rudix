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

const usageTrend = [
  { period: "Week 1", questions: 320, users: 42 },
  { period: "Week 2", questions: 460, users: 58 },
  { period: "Week 3", questions: 515, users: 64 },
  { period: "Week 4", questions: 690, users: 81 },
];

const featureAdoption = [
  { feature: "Chat", adoption: 88 },
  { feature: "Search", adoption: 71 },
  { feature: "Collections", adoption: 56 },
  { feature: "Evaluations", adoption: 34 },
];

export function UsageAdoptionDashboard() {
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
          value="1,985"
          change="+18%"
          description="Selected period"
        />
        <KpiCard
          label="Active users"
          value="81"
          change="+12%"
          description="Unique users"
        />
        <KpiCard
          label="Returning users"
          value="68%"
          change="+5%"
          description="Used Rudix more than once"
        />
        <KpiCard
          label="Questions per user"
          value="24.5"
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
            aria-label="Questions and active users increased throughout the period"
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
            aria-label="Chat has the highest feature adoption at 88 percent"
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
        caption="Team adoption"
        columns={["Team", "Active users", "Questions", "Adoption"]}
        rows={[
          [
            "Operations",
            "28",
            "740",
            <StatusBadge key="high" label="High" tone="healthy" />,
          ],
          [
            "Customer success",
            "24",
            "615",
            <StatusBadge key="growing" label="Growing" tone="healthy" />,
          ],
          [
            "Finance",
            "17",
            "390",
            <StatusBadge key="steady" label="Steady" tone="neutral" />,
          ],
          [
            "Legal",
            "12",
            "240",
            <StatusBadge key="review" label="Needs support" tone="warning" />,
          ],
        ]}
      />
    </main>
  );
}

const accessRisk = [
  { name: "Healthy", value: 76, color: "#10b981" },
  { name: "Warning", value: 17, color: "#f59e0b" },
  { name: "Critical", value: 7, color: "#f43f5e" },
];

export function PermissionsAccessDashboard() {
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
          label="Workspace members"
          value="124"
          description="Active identities"
        />
        <KpiCard label="Open conflicts" value="9" description="Needs review" />
        <KpiCard
          label="Blocking conflicts"
          value="2"
          description="Immediate attention"
        />
        <KpiCard
          label="Resolved this month"
          value="31"
          change="+8"
          description="Access remediations"
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
            aria-label="Access posture is 76 percent healthy, 17 percent warning, and 7 percent critical"
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
          description="Two access rules can expose or hide sources incorrectly. Review the matched grants and denies before the next permission sync."
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
        rows={[
          [
            "Grant overrides explicit deny",
            "Finance collection",
            <StatusBadge key="blocking" label="Blocking" tone="critical" />,
            "Open",
          ],
          [
            "Group membership mismatch",
            "HR handbook",
            <StatusBadge key="risk" label="Security risk" tone="critical" />,
            "Investigating",
          ],
          [
            "Stale connector ACL",
            "Salesforce sync",
            <StatusBadge key="warning" label="Warning" tone="warning" />,
            "Open",
          ],
        ]}
      />
    </main>
  );
}

const gapTopics = [
  { topic: "Security", occurrences: 38 },
  { topic: "Onboarding", occurrences: 31 },
  { topic: "API", occurrences: 24 },
  { topic: "Benefits", occurrences: 18 },
  { topic: "Procurement", occurrences: 12 },
];

export function KnowledgeGapsDashboard() {
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
          value="47"
          description="Across all collections"
        />
        <KpiCard
          label="Unanswered queries"
          value="123"
          description="Selected period"
        />
        <KpiCard
          label="Low-confidence topics"
          value="18"
          description="Needs stronger evidence"
        />
        <KpiCard
          label="Resolved this month"
          value="22"
          change="+6"
          description="Coverage improvements"
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
            aria-label="Security is the largest knowledge gap with 38 occurrences"
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
          title="Add missing security guidance"
          description="Security protocol questions account for the largest unresolved cluster and repeatedly return weak evidence."
          priority="High"
          impact="Address 38 recurring queries"
          related="Security collection"
          action={<ReportLink href="/documents" label="Add source" />}
        />
      </div>
      <ReportDataTable
        caption="Knowledge gap details"
        columns={["Topic", "Example query", "Occurrences", "Status"]}
        rows={[
          [
            "Q4 security protocols",
            "Which controls changed this quarter?",
            "38",
            <StatusBadge key="open" label="Open" tone="critical" />,
          ],
          [
            "Remote onboarding",
            "How do contractors receive access?",
            "31",
            <StatusBadge key="review" label="In review" tone="warning" />,
          ],
          [
            "API deprecations",
            "When is v11 no longer supported?",
            "24",
            <StatusBadge
              key="source"
              label="Source requested"
              tone="neutral"
            />,
          ],
          [
            "Employee benefits",
            "Does the plan cover remote therapy?",
            "18",
            <StatusBadge key="progress" label="In review" tone="warning" />,
          ],
        ]}
      />
    </main>
  );
}
