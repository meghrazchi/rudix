"use client";

import { useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  FileText,
  Link2Off,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  XCircle,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  DetailDrawer,
  ReportDataTable,
  ReportHeader,
  StatusBadge,
} from "@/components/reports/report-ui";

type Tone = "primary" | "success" | "warning" | "danger";

const tones: Record<Tone, string> = {
  primary: "border-t-[#6254d9] text-[#4d3ed1]",
  success: "border-t-emerald-500 text-emerald-700",
  warning: "border-t-amber-500 text-amber-700",
  danger: "border-t-rose-500 text-rose-700",
};

function MetricCard({
  label,
  value,
  detail,
  tone = "primary",
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: Tone;
  icon: ReactNode;
}) {
  return (
    <article
      className={`rounded-xl border border-t-4 border-[#dfdced] bg-white p-4 shadow-sm sm:p-5 ${tones[tone]}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-bold tracking-[0.08em] text-[#777287] uppercase">
          {label}
        </p>
        {icon}
      </div>
      <p className="mt-3 text-3xl font-extrabold text-[#2a2640]">{value}</p>
      <p className="mt-2 text-xs font-semibold text-current">{detail}</p>
    </article>
  );
}

const chartTooltipStyle = {
  border: "1px solid #dfdced",
  borderRadius: "8px",
  boxShadow: "0 4px 14px rgb(42 38 64 / 0.12)",
  color: "#2a2640",
  fontSize: "12px",
};

function ReportBarChart({
  values,
  labels,
}: {
  values: number[];
  labels: string[];
}) {
  const data = labels.map((label, index) => ({
    label,
    value: values[index] ?? 0,
  }));
  const summary = data
    .map((item) => `${item.label}: ${item.value}%`)
    .join(", ");

  return (
    <div
      className="h-64 w-full"
      role="img"
      aria-label={summary}
      data-chart-library="recharts"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 16, right: 8, left: 8, bottom: 0 }}
        >
          <CartesianGrid
            vertical={false}
            stroke="#ebe8f4"
            strokeDasharray="3 3"
          />
          <XAxis
            dataKey="label"
            axisLine={{ stroke: "#dfdced" }}
            tickLine={false}
            tick={{ fill: "#777287", fontSize: 10 }}
          />
          <YAxis hide domain={[0, 100]} />
          <Tooltip
            cursor={{ fill: "#f7f5ff" }}
            contentStyle={chartTooltipStyle}
            formatter={(value) => [`${value}%`, "Score"]}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={64}>
            {data.map((item, index) => (
              <Cell
                key={item.label}
                fill="#6254d9"
                fillOpacity={Math.min(1, 0.35 + index * 0.08)}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function FeedbackCategoryChart({
  data,
}: {
  data: ReadonlyArray<readonly [string, number]>;
}) {
  const chartData = data.map(([label, value]) => ({ label, value }));
  const summary = chartData
    .map((item) => `${item.label}: ${item.value}%`)
    .join(", ");

  return (
    <div
      className="h-72 w-full"
      role="img"
      aria-label={summary}
      data-chart-library="recharts"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 0, right: 38, bottom: 0, left: 0 }}
          barCategoryGap="34%"
        >
          <XAxis type="number" hide domain={[0, 50]} />
          <YAxis
            type="category"
            dataKey="label"
            width={104}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#403c52", fontSize: 12 }}
          />
          <Tooltip
            cursor={{ fill: "#f7f5ff" }}
            contentStyle={chartTooltipStyle}
            formatter={(value) => [`${value}%`, "Feedback"]}
          />
          <Bar
            dataKey="value"
            fill="#6254d9"
            radius={[0, 5, 5, 0]}
            background={{ fill: "#ece9f7", radius: 5 }}
          >
            {chartData.map((item) => (
              <Cell
                key={item.label}
                fill={item.label === "Hallucination" ? "#f43f5e" : "#6254d9"}
              />
            ))}
            <LabelList
              dataKey="value"
              position="right"
              fill="#403c52"
              fontSize={12}
              fontWeight={700}
              formatter={(value) => `${value}%`}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Panel({
  title,
  description,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-[#dfdced] bg-white p-4 shadow-sm sm:p-5 lg:p-6 ${className}`}
    >
      <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
      {description ? (
        <p className="mt-1 text-sm text-[#777287]">{description}</p>
      ) : null}
      <div className="mt-5">{children}</div>
    </section>
  );
}

const queryRows = [
  [
    "How do I reset my SSO credentials?",
    "Jane Doe",
    "Oct 24, 2023",
    "0.96",
    "4 sources",
  ],
  [
    "What is the policy for expense refunds in EU?",
    "Mark Smith",
    "Oct 24, 2023",
    "0.72",
    "2 sources",
  ],
  [
    "Explain the new compliance layer for v12.",
    "Anna Lee",
    "Oct 23, 2023",
    "0.41",
    "0 sources",
  ],
];

export function AnswerQualityDashboard() {
  const [selected, setSelected] = useState<string[] | null>(null);
  return (
    <main className="grid gap-6">
      <ReportHeader
        title="Answer Quality"
        description="Trace confidence, citation accuracy, and grounding quality across retrieval responses."
      />
      <section
        aria-label="Answer quality key metrics"
        className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4"
      >
        <MetricCard
          label="Citation accuracy"
          value="94.2%"
          detail="+2.4% vs last week"
          icon={<ShieldCheck className="h-5 w-5" />}
        />
        <MetricCard
          label="Missing citations"
          value="12"
          detail="5% fewer vs last week"
          tone="danger"
          icon={<Link2Off className="h-5 w-5" />}
        />
        <MetricCard
          label="Avg. citation support"
          value="3.8"
          detail="Citations per answer"
          icon={<FileText className="h-5 w-5" />}
        />
        <MetricCard
          label="Hallucination risk"
          value="Low"
          detail="Stable"
          tone="warning"
          icon={<AlertTriangle className="h-5 w-5" />}
        />
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <Panel
          title="Confidence Score Distribution"
          description="Probability frequency for all retrieval responses"
        >
          <ReportBarChart
            values={[20, 35, 60, 85, 95, 55, 25]}
            labels={["0.0", "0.2", "0.4", "0.6", "0.8", "0.9", "1.0"]}
          />
        </Panel>
        <div className="grid gap-5">
          <section className="rounded-xl bg-[#4434c7] p-4 text-white shadow-lg sm:p-5 lg:p-6">
            <h2 className="text-lg font-bold">Model Confidence</h2>
            <p className="mt-1 text-sm text-indigo-100">
              Average reliability across 2.4k queries this month.
            </p>
            <div className="mt-6 flex items-center gap-4">
              <strong className="text-4xl">0.89</strong>
              <span className="h-2 flex-1 overflow-hidden rounded bg-white/20">
                <span className="block h-full w-[89%] bg-white" />
              </span>
            </div>
          </section>
          <Panel title="Top Knowledge Gaps">
            <ul className="grid gap-3 text-sm text-[#403c52]">
              {[
                "Q4 Security Protocols",
                "Remote Onboarding",
                "API deprecation dates",
              ].map((gap) => (
                <li
                  key={gap}
                  className="flex items-center justify-between rounded-lg bg-[#f7f5ff] px-3 py-2"
                >
                  <span>{gap}</span>
                  <ArrowRight className="h-4 w-4 text-[#6254d9]" />
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
      <section aria-labelledby="query-analysis" className="grid gap-4">
        <div>
          <h2 id="query-analysis" className="text-lg font-bold text-[#2a2640]">
            Detailed Query Analysis
          </h2>
          <p className="text-sm text-[#777287]">
            Select a query to inspect response quality and attribution.
          </p>
        </div>
        <ReportDataTable
          caption="Detailed query analysis"
          columns={["Question", "User", "Date", "Confidence", "Citations"]}
          rows={queryRows.map((row) =>
            row.map((cell, index) =>
              index === 0 ? (
                <button
                  key={cell}
                  type="button"
                  onClick={() => setSelected(row)}
                  className="text-left font-semibold text-[#3525cd] hover:underline"
                >
                  {cell}
                </button>
              ) : (
                cell
              ),
            ),
          )}
        />
      </section>
      <DetailDrawer
        title="Query Details"
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
      >
        <div className="grid gap-5 text-sm text-[#403c52]">
          <div>
            <p className="text-xs font-bold text-[#777287] uppercase">
              Question
            </p>
            <p className="mt-1 text-lg font-bold">{selected?.[0]}</p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-bold text-[#777287] uppercase">User</p>
              <p className="mt-1">{selected?.[1]}</p>
            </div>
            <div>
              <p className="text-xs font-bold text-[#777287] uppercase">
                Confidence
              </p>
              <p className="mt-1">{selected?.[3]}</p>
            </div>
          </div>
          <section className="rounded-xl border border-[#dfdced] bg-[#f7f5ff] p-4">
            <p className="text-xs font-bold text-[#6254d9] uppercase">
              AI response
            </p>
            <p className="mt-2 leading-6">
              To reset your SSO credentials, open the Identity Portal from your
              employee dashboard and choose Account Recovery. Verify your
              identity before updating the password. [1][2]
            </p>
            <p className="mt-3 flex items-center gap-2 text-emerald-700">
              <CheckCircle2 className="h-4 w-4" /> Guardrail validation passed
            </p>
          </section>
          <div>
            <p className="text-xs font-bold text-[#777287] uppercase">
              Sources
            </p>
            <div className="mt-2 grid gap-2">
              {["SSO_Policy_2023.pdf", "Identity_Mgmt_Guide.docx"].map(
                (source) => (
                  <div
                    key={source}
                    className="flex items-center gap-2 rounded-lg border border-[#dfdced] p-3"
                  >
                    <FileText className="h-4 w-4 text-[#6254d9]" />
                    {source}
                  </div>
                ),
              )}
            </div>
          </div>
        </div>
      </DetailDrawer>
    </main>
  );
}

const integrityRows: ReactNode[][] = [
  [
    "Q3 Financial Report.pdf",
    "PDF / Internal",
    "1,402 refs",
    "98%",
    <StatusBadge key="stable-1" label="Stable" tone="healthy" />,
    "Inspect",
  ],
  [
    "Salesforce_Leads_Main",
    "DB / Dynamic",
    "890 refs",
    "85%",
    <StatusBadge key="stable-2" label="Stable" tone="healthy" />,
    "Inspect",
  ],
  [
    "Employee_Benefits_2023.docx",
    "DOCX / Deprecated",
    "245 refs",
    "62%",
    <StatusBadge key="outdated" label="Outdated" tone="warning" />,
    "Update",
  ],
  [
    "Compliance_Checklist_v1.xls",
    "XLS / External",
    "12 refs",
    "12%",
    <StatusBadge key="broken" label="Broken" tone="critical" />,
    "Relink",
  ],
];

export function SourceHealthDashboard() {
  return (
    <main className="grid gap-6">
      <ReportHeader
        title="Source Health"
        description="Monitor retrieval stability, source freshness, and citation integrity across connected knowledge."
      />
      <section
        aria-label="Source health key metrics"
        className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4"
      >
        <MetricCard
          label="Questions asked"
          value="24,812"
          detail="+12.5% vs last week"
          icon={<MessageSquareText className="h-5 w-5" />}
        />
        <MetricCard
          label="Trusted answers"
          value="94.2%"
          detail="2.1% improvement"
          tone="success"
          icon={<ShieldCheck className="h-5 w-5" />}
        />
        <MetricCard
          label="Low confidence"
          value="312"
          detail="5% critical decrease"
          tone="warning"
          icon={<AlertTriangle className="h-5 w-5" />}
        />
        <MetricCard
          label="Citation issues"
          value="18"
          detail="4 urgent alerts"
          tone="danger"
          icon={<Link2Off className="h-5 w-5" />}
        />
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <Panel
          title="Retrieval Volatility"
          description="Hourly confidence score fluctuations across clusters"
        >
          <ReportBarChart
            values={[40, 55, 75, 95, 85, 65, 45]}
            labels={[
              "00:00",
              "04:00",
              "08:00",
              "12:00",
              "16:00",
              "20:00",
              "23:59",
            ]}
          />
        </Panel>
        <section className="rounded-xl bg-[#4434c7] p-4 text-white shadow-lg sm:p-5 lg:p-6">
          <h2 className="text-lg font-bold">Recommended Tasks</h2>
          <p className="mt-1 text-sm text-indigo-100">
            Insights derived from retrieval failures
          </p>
          <div className="mt-5 grid gap-3">
            {[
              ["Fix 12 broken source links", "Retrieval accuracy +4.2%"],
              ["Re-index HR Handbook", "Benefits knowledge gap detected"],
              ["Review 4 low-confidence traces", "Requires human verification"],
            ].map(([title, detail]) => (
              <div
                key={title}
                className="flex gap-3 rounded-lg bg-white/10 p-3"
              >
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <p className="text-sm font-bold">{title}</p>
                  <p className="mt-1 text-xs text-indigo-100">{detail}</p>
                </div>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="mt-5 w-full rounded-lg bg-white px-4 py-2.5 text-sm font-bold text-[#4434c7]"
          >
            Launch cleanup tool
          </button>
        </section>
      </div>
      <section aria-labelledby="integrity-heading" className="grid gap-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2
              id="integrity-heading"
              className="text-lg font-bold text-[#2a2640]"
            >
              Source Citation Integrity
            </h2>
            <p className="text-sm text-[#777287]">98% linked · 2% warning</p>
          </div>
        </div>
        <ReportDataTable
          caption="Source citation integrity"
          columns={[
            "Source document",
            "Doc type",
            "Citation freq.",
            "Confidence",
            "Integrity",
            "Action",
          ]}
          rows={integrityRows}
        />
      </section>
    </main>
  );
}

const feedbackRows: ReactNode[][] = [
  [
    "The response ignored the Q4 budget constraints mentioned in Doc A.",
    <StatusBadge key="wrong" label="Wrong answer" tone="critical" />,
    "Critical",
    "#8421-XB · 2h ago",
  ],
  [
    "Links to page 4 but the data is on page 12 of the HR manual.",
    <StatusBadge key="citation" label="Bad citation" tone="warning" />,
    "Pending",
    "#8419-ZA · 5h ago",
  ],
  [
    "Reference ID for Project Phoenix is missing.",
    <StatusBadge key="source" label="Missing source" tone="warning" />,
    "Triaged",
    "#8415-XF · 1d ago",
  ],
  [
    "The answer is correct but the tone is too casual for client use.",
    <StatusBadge key="tone" label="Tone / style" />,
    "Low priority",
    "#8412-LC · 1d ago",
  ],
];

export function FeedbackIssuesDashboard() {
  const categories = [
    ["Wrong answer", 42],
    ["Bad citation", 28],
    ["Missing source", 15],
    ["Hallucination", 10],
    ["Slow response", 5],
  ] as const;
  return (
    <main className="grid gap-6">
      <ReportHeader
        title="Feedback & Issues"
        description="Understand feedback themes, triage reported answer issues, and turn recurring failures into evaluation cases."
      />
      <section
        aria-label="Feedback key metrics"
        className="grid gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4"
      >
        <MetricCard
          label="Total feedback"
          value="1,284"
          detail="+12.5% vs last week"
          icon={<MessageSquareText className="h-5 w-5" />}
        />
        <MetricCard
          label="New issues"
          value="42"
          detail="8 critical"
          tone="danger"
          icon={<XCircle className="h-5 w-5" />}
        />
        <MetricCard
          label="Triaged"
          value="89.2%"
          detail="1,145 processed"
          tone="success"
          icon={<CheckCircle2 className="h-5 w-5" />}
        />
        <MetricCard
          label="Accepted"
          value="216"
          detail="Pending evaluation sync"
          tone="warning"
          icon={<TrendingUp className="h-5 w-5" />}
        />
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(300px,5fr)_minmax(0,7fr)]">
        <Panel title="Feedback by Category">
          <FeedbackCategoryChart data={categories} />
          <div className="mt-5 flex gap-2 rounded-lg border border-[#dfdced] bg-[#f7f5ff] p-3 text-sm text-[#5f5b72]">
            <Sparkles className="h-4 w-4 shrink-0 text-[#6254d9]" />
            <p>
              <strong>AI insight:</strong> 64% of wrong answers originate from
              the q3_internal_docs index.
            </p>
          </div>
        </Panel>
        <section
          aria-labelledby="feedback-queue"
          className="grid content-start gap-4"
        >
          <div>
            <h2
              id="feedback-queue"
              className="text-lg font-bold text-[#2a2640]"
            >
              Feedback Queue
            </h2>
            <p className="text-sm text-[#777287]">
              Showing 4 of 42 active issues
            </p>
          </div>
          <ReportDataTable
            caption="Feedback queue"
            columns={["Feedback", "Category", "Status", "Query"]}
            rows={feedbackRows}
          />
        </section>
      </div>
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-[#dfdced] pt-4 text-sm text-[#68647b]">
        <div className="flex gap-5">
          <span className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-[#6254d9]" />
            Auto-triage enabled
          </span>
          <span>Next sync in 12m</span>
        </div>
        <button
          type="button"
          className="rounded-lg bg-[#4434c7] px-4 py-2 font-bold text-white"
        >
          Create bulk eval case
        </button>
      </footer>
    </main>
  );
}
