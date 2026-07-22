"use client";

import type { ReactNode } from "react";
import Link from "next/link";
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
  ReportDataTable,
  ReportHeader,
  StatusBadge,
} from "@/components/reports/report-ui";
import { useReportBackendData } from "@/components/reports/ReportBackendData";

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

export function AnswerQualityDashboard() {
  const { trust, analytics, gaps } = useReportBackendData();
  const accuracy = trust?.avg_citation_support_score;
  const confidence = trust?.avg_confidence_score;
  const trends = trust?.daily_trends ?? [];
  const trendValues = trends.map((point) =>
    Math.round((point.avg_confidence_score ?? 0) * 100),
  );
  const trendLabels = trends.map((point) => point.date.slice(5));
  const queryRows = trends.map((point) => [
    point.date,
    String(point.answer_count),
    String(point.not_found_count),
    point.avg_confidence_score?.toFixed(2) ?? "—",
    point.avg_citation_support_score?.toFixed(2) ?? "—",
  ]);
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
          value={accuracy == null ? "—" : `${(accuracy * 100).toFixed(1)}%`}
          detail="Average citation support"
          icon={<ShieldCheck className="h-5 w-5" />}
        />
        <MetricCard
          label="Missing citations"
          value={String(trust?.warnings.citation_validation_failed_count ?? 0)}
          detail="Backend validation failures"
          tone="danger"
          icon={<Link2Off className="h-5 w-5" />}
        />
        <MetricCard
          label="Avg. citation support"
          value={trust?.avg_verification_support_score?.toFixed(2) ?? "—"}
          detail="Verification support score"
          icon={<FileText className="h-5 w-5" />}
        />
        <MetricCard
          label="Hallucination risk"
          value={String(analytics?.low_confidence_queries ?? 0)}
          detail="Low-confidence answers"
          tone="warning"
          icon={<AlertTriangle className="h-5 w-5" />}
        />
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <Panel
          title="Confidence Score Distribution"
          description="Probability frequency for all retrieval responses"
        >
          <ReportBarChart values={trendValues} labels={trendLabels} />
        </Panel>
        <div className="grid gap-5">
          <section className="rounded-xl bg-[#4434c7] p-4 text-white shadow-lg sm:p-5 lg:p-6">
            <h2 className="text-lg font-bold">Model Confidence</h2>
            <p className="mt-1 text-sm text-indigo-100">
              Average reliability across {trust?.total_answers ?? 0} answers in
              the selected period.
            </p>
            <div className="mt-6 flex items-center gap-4">
              <strong className="text-4xl">
                {confidence?.toFixed(2) ?? "—"}
              </strong>
              <span className="h-2 flex-1 overflow-hidden rounded bg-white/20">
                <span
                  className="block h-full bg-white"
                  style={{ width: `${Math.round((confidence ?? 0) * 100)}%` }}
                />
              </span>
            </div>
          </section>
          <Panel title="Top Knowledge Gaps">
            <ul className="grid gap-3 text-sm text-[#403c52]">
              {(gaps?.items ?? []).map((gap) => (
                <li
                  key={gap.gap_id}
                  className="flex items-center justify-between rounded-lg bg-[#f7f5ff] px-3 py-2"
                >
                  <span>{gap.topic_label}</span>
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
            Daily Quality Analysis
          </h2>
          <p className="text-sm text-[#777287]">
            Aggregated answer quality returned by the trust analytics API.
          </p>
        </div>
        <ReportDataTable
          caption="Daily quality analysis"
          columns={[
            "Date",
            "Answers",
            "Not found",
            "Confidence",
            "Citation support",
          ]}
          rows={queryRows}
        />
      </section>
    </main>
  );
}

export function SourceHealthDashboard() {
  const { trust, failedJobs, usage } = useReportBackendData();
  const trends = trust?.daily_trends ?? [];
  const failed = failedJobs?.items ?? [];
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
          value={String(usage?.totals.questions_asked ?? 0)}
          detail="Selected period"
          icon={<MessageSquareText className="h-5 w-5" />}
        />
        <MetricCard
          label="Trusted answers"
          value={String(trust?.trust_distribution.high_count ?? 0)}
          detail="High-trust answers"
          tone="success"
          icon={<ShieldCheck className="h-5 w-5" />}
        />
        <MetricCard
          label="Low confidence"
          value={String(trust?.trust_distribution.low_count ?? 0)}
          detail="Low-trust answers"
          tone="warning"
          icon={<AlertTriangle className="h-5 w-5" />}
        />
        <MetricCard
          label="Citation issues"
          value={String(trust?.warnings.citation_validation_failed_count ?? 0)}
          detail="Citation validation failures"
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
            values={trends.map((point) =>
              Math.round((point.avg_confidence_score ?? 0) * 100),
            )}
            labels={trends.map((point) => point.date.slice(5))}
          />
        </Panel>
        <section className="rounded-xl bg-[#4434c7] p-4 text-white shadow-lg sm:p-5 lg:p-6">
          <h2 className="text-lg font-bold">Recommended Tasks</h2>
          <p className="mt-1 text-sm text-indigo-100">
            Insights derived from retrieval failures
          </p>
          <div className="mt-5 grid gap-3">
            {[
              [
                `Review ${failedJobs?.total ?? 0} failed jobs`,
                "Restore incomplete source coverage",
              ],
              [
                `Refresh ${trust?.warnings.stale_source_count ?? 0} stale sources`,
                "Reduce stale-answer warnings",
              ],
              [
                `Review ${trust?.warnings.extraction_count ?? 0} extraction warnings`,
                "Improve indexed evidence",
              ],
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
          <Link
            href="/admin/failed-jobs"
            className="mt-5 w-full rounded-lg bg-white px-4 py-2.5 text-sm font-bold text-[#4434c7]"
          >
            Open failed jobs
          </Link>
        </section>
      </div>
      <section aria-labelledby="integrity-heading" className="grid gap-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2
              id="integrity-heading"
              className="text-lg font-bold text-[#2a2640]"
            >
              Source Processing Health
            </h2>
            <p className="text-sm text-[#777287]">
              Organization-scoped failed jobs and trust warnings
            </p>
          </div>
        </div>
        <ReportDataTable
          caption="Source processing health"
          columns={["Job", "Type", "Attempts", "Queue", "Status", "Retryable"]}
          rows={failed.map((job) => [
            job.task_name,
            job.job_type,
            String(job.attempt_count),
            job.queue_name ?? "—",
            <StatusBadge key={job.id} label={job.status} tone="critical" />,
            job.is_retryable ? "Yes" : "No",
          ])}
        />
      </section>
    </main>
  );
}

export function FeedbackIssuesDashboard() {
  const { feedbackMetrics, feedbackItems } = useReportBackendData();
  const items = feedbackItems?.items ?? [];
  const categories: Array<readonly [string, number]> = (
    feedbackMetrics?.categories ?? []
  ).map((category) => [category.category, category.count]);
  const newIssues = items.filter((item) => item.status === "new").length;
  const triaged = items.filter((item) => item.status === "triaged").length;
  const accepted = items.filter((item) => item.status === "accepted").length;
  const feedbackRows: ReactNode[][] = items.map((item) => [
    item.message?.content_preview ??
      item.feedback?.comment ??
      "Feedback details unavailable",
    <StatusBadge
      key={`${item.review_id}-category`}
      label={item.feedback?.category?.replaceAll("_", " ") ?? "Uncategorized"}
      tone={item.severity === "high" ? "critical" : "neutral"}
    />,
    item.status.replaceAll("_", " "),
    item.review_id,
  ]);
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
          value={String(
            feedbackMetrics?.total_feedback ?? feedbackItems?.total ?? 0,
          )}
          detail={`${feedbackMetrics?.period_days ?? 30}-day backend total`}
          icon={<MessageSquareText className="h-5 w-5" />}
        />
        <MetricCard
          label="New issues"
          value={String(newIssues)}
          detail={`${items.filter((item) => item.severity === "high").length} high severity`}
          tone="danger"
          icon={<XCircle className="h-5 w-5" />}
        />
        <MetricCard
          label="Triaged"
          value={String(triaged)}
          detail="Triaged queue items"
          tone="success"
          icon={<CheckCircle2 className="h-5 w-5" />}
        />
        <MetricCard
          label="Accepted"
          value={String(accepted)}
          detail="Accepted feedback items"
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
              <strong>Backend insight:</strong>{" "}
              {categories[0]?.[0] ?? "No category"} is the most frequent
              category with {categories[0]?.[1] ?? 0} reports.
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
              Showing {items.length} of {feedbackItems?.total ?? 0} active
              issues
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
            Feedback review enabled
          </span>
          <span>Organization-scoped feedback queue</span>
        </div>
        <Link
          href="/admin/feedback-review"
          className="rounded-lg bg-[#4434c7] px-4 py-2 font-bold text-white"
        >
          Open feedback review
        </Link>
      </footer>
    </main>
  );
}
