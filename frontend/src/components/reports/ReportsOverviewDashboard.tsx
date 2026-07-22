"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowRight, FileUp, MessageSquareText } from "lucide-react";
import { useReportFilters } from "@/components/reports/ReportFilters";
import {
  ChartCard,
  KpiCard,
  PartialDataState,
  RecommendedActionCard,
  ReportHeader,
  StatusBadge,
} from "@/components/reports/report-ui";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  buildRecommendedActions,
  calculateOverviewKpis,
  getReportsOverview,
} from "@/lib/reports-overview";
import { serializeReportFilters, type ReportFilters } from "@/lib/reports";

const format = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const links = {
  quality: "/reports/answer-quality",
  sources: "/reports/source-health",
  usage: "/reports/usage-adoption",
  permissions: "/reports/permissions-access",
  feedback: "/reports/feedback-issues",
  gaps: "/reports/knowledge-gaps",
};

function reportHref(pathname: string, filters: ReportFilters): string {
  const query = serializeReportFilters(filters).toString();
  return query ? `${pathname}?${query}` : pathname;
}

function Bars({
  items,
}: {
  items: Array<{ label: string; value: number; tone?: string }>;
}) {
  const max = Math.max(1, ...items.map((item) => item.value));
  if (!items.some((item) => item.value > 0))
    return (
      <EmptyState
        compact
        title="No activity in this period"
        description="Broaden the filters or start using the workspace."
      />
    );
  return (
    <div
      className="grid gap-3"
      role="img"
      aria-label={items
        .map((item) => `${item.label}: ${item.value}`)
        .join(", ")}
    >
      {items.map((item) => (
        <div
          key={item.label}
          className="grid grid-cols-[minmax(90px,1fr)_2fr_auto] items-center gap-2 text-xs"
        >
          <span className="truncate text-[#5f5b72]">{item.label}</span>
          <span className="h-2.5 overflow-hidden rounded-full bg-[#ece9f7]">
            <span
              className={`block h-full rounded-full ${item.tone ?? "bg-[#6254d9]"}`}
              style={{ width: `${Math.max(3, (item.value / max) * 100)}%` }}
            />
          </span>
          <strong className="min-w-7 text-right text-[#2a2640]">
            {format.format(item.value)}
          </strong>
        </div>
      ))}
    </div>
  );
}

function DashboardLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 rounded-lg bg-[#3525cd] px-3 py-2 text-xs font-bold text-white"
    >
      {children}
      <ArrowRight className="h-3 w-3" aria-hidden />
    </Link>
  );
}

export function ReportsOverviewDashboard() {
  const t = useTranslations("reports");
  const { filters } = useReportFilters();
  const query = useQuery({
    queryKey: ["reports-overview", filters],
    queryFn: () => getReportsOverview(filters),
  });
  if (query.isLoading)
    return (
      <LoadingState
        title="Loading reports overview"
        description="Calculating workspace health and recommendations."
      />
    );
  if (query.isError || !query.data)
    return (
      <ErrorState
        title="Reports overview unavailable"
        description="We could not load workspace health right now."
        onRetry={() => void query.refetch()}
      />
    );
  const data = query.data;
  const kpis = calculateOverviewKpis(data);
  const actions = buildRecommendedActions(kpis);
  const empty =
    kpis.questions === 0 && (data.usage?.totals.documents ?? 0) === 0;
  const trust = data.trust?.trust_distribution;
  const warnings = data.trust?.warnings;
  const href = (pathname: string) => reportHref(pathname, filters);

  return (
    <main className="grid gap-6">
      <ReportHeader
        title={t("sections.overview.label")}
        description={t("sections.overview.description")}
      />
      {data.unavailable.length ? (
        <PartialDataState
          message={`${data.unavailable.join(", ")} data is temporarily unavailable. Available metrics remain exact.`}
        />
      ) : null}
      {empty ? (
        <EmptyState
          title="Build your first workspace report"
          description="Upload a source and ask a question to start measuring answer quality, coverage, and adoption."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <DashboardLink href="/documents">
                <FileUp className="h-3 w-3" aria-hidden />
                Upload sources
              </DashboardLink>
              <DashboardLink href="/chat">
                <MessageSquareText className="h-3 w-3" aria-hidden />
                Ask a question
              </DashboardLink>
            </div>
          }
        />
      ) : null}
      <section
        aria-label="Key performance indicators"
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8"
      >
        <KpiCard
          label="Questions asked"
          value={format.format(kpis.questions)}
          href={href(links.usage)}
          description="Selected period"
        />
        <KpiCard
          label="Trusted answers"
          value={format.format(kpis.trustedAnswers)}
          href={href(links.quality)}
          description="High-confidence answers"
        />
        <KpiCard
          label="Low-confidence"
          value={format.format(kpis.lowConfidence)}
          href={href(links.quality)}
          description="Needs quality review"
        />
        <KpiCard
          label="Citation issues"
          value={format.format(kpis.citationIssues)}
          href={href(links.quality)}
          description="Validation failures"
        />
        <KpiCard
          label="Sources to review"
          value={format.format(kpis.sourcesNeedingReview)}
          href={href(links.sources)}
          description="Freshness or processing"
        />
        <KpiCard
          label="Active users"
          value={format.format(kpis.activeUsers)}
          href={href(links.usage)}
          description="Unique users"
        />
        <KpiCard
          label="Failed indexing"
          value={format.format(kpis.failedIndexingJobs)}
          href={href(links.sources)}
          description="Open failed jobs"
        />
        <KpiCard
          label="Permission conflicts"
          value={format.format(kpis.permissionConflicts)}
          href={href(links.permissions)}
          description="Open conflicts"
        />
      </section>

      <section
        aria-label="Workspace health charts"
        className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
      >
        <ChartCard
          title="Answer confidence"
          description="Trust distribution"
          href={href(links.quality)}
        >
          <Bars
            items={[
              {
                label: "High",
                value: trust?.high_count ?? 0,
                tone: "bg-emerald-500",
              },
              {
                label: "Medium",
                value: trust?.medium_count ?? 0,
                tone: "bg-amber-500",
              },
              {
                label: "Low",
                value: trust?.low_count ?? 0,
                tone: "bg-rose-500",
              },
            ]}
          />
        </ChartCard>
        <ChartCard
          title="Questions over time"
          description="Questions by reporting period"
          href={href(links.usage)}
        >
          <Bars
            items={(data.usage?.series ?? []).slice(-7).map((point) => ({
              label: point.period_start.slice(5, 10),
              value: point.questions_asked,
            }))}
          />
        </ChartCard>
        <ChartCard
          title="Source health"
          description="Warnings that can affect answers"
          href={href(links.sources)}
        >
          <Bars
            items={[
              { label: "Stale", value: warnings?.stale_source_count ?? 0 },
              { label: "OCR", value: warnings?.ocr_count ?? 0 },
              { label: "Extraction", value: warnings?.extraction_count ?? 0 },
              { label: "Processing", value: warnings?.processing_count ?? 0 },
            ]}
          />
        </ChartCard>
        <ChartCard
          title="Feedback categories"
          description="Most common feedback themes"
          href={href(links.feedback)}
        >
          <Bars
            items={(data.analytics?.top_feedback_categories ?? [])
              .slice(0, 5)
              .map((item) => ({ label: item.category, value: item.count }))}
          />
        </ChartCard>
        <ChartCard
          title="Active users"
          description="Unique users by reporting period"
          href={href(links.usage)}
        >
          <Bars
            items={(data.usage?.series ?? []).slice(-7).map((point) => ({
              label: point.period_start.slice(5, 10),
              value: point.active_users,
            }))}
          />
        </ChartCard>
        <ChartCard
          title="Top knowledge gaps"
          description="Repeated unanswered topics"
          href={href(links.gaps)}
        >
          <Bars
            items={(data.gaps?.items ?? []).map((gap) => ({
              label: gap.topic_label,
              value: gap.occurrence_count,
            }))}
          />
        </ChartCard>
        <ChartCard
          title="Connector sync health"
          description="Indexing jobs in this period"
          href={href(links.sources)}
        >
          <Bars
            items={[
              {
                label: "Healthy",
                value: Math.max(
                  0,
                  (data.usage?.totals.indexing_jobs ?? 0) -
                    kpis.failedIndexingJobs,
                ),
                tone: "bg-emerald-500",
              },
              {
                label: "Failed",
                value: kpis.failedIndexingJobs,
                tone: "bg-rose-500",
              },
            ]}
          />
        </ChartCard>
        <ChartCard
          title="Permission warnings"
          description="Open access conflicts by severity"
          href={href(links.permissions)}
        >
          <Bars
            items={["security_risk", "blocking", "warning", "info"].map(
              (severity) => ({
                label: severity.replace("_", " "),
                value:
                  data.conflicts?.items.filter(
                    (item) => item.severity === severity,
                  ).length ?? 0,
              }),
            )}
          />
        </ChartCard>
      </section>

      <section
        aria-labelledby="recommended-actions-title"
        className="grid gap-3"
      >
        <div className="flex items-center justify-between">
          <h2
            id="recommended-actions-title"
            className="text-lg font-extrabold text-[#2a2640]"
          >
            Recommended actions
          </h2>
          <StatusBadge
            label={actions.length ? `${actions.length} to review` : "All clear"}
            tone={actions.length ? "warning" : "healthy"}
          />
        </div>
        {actions.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {actions.map((item) => (
              <RecommendedActionCard
                key={item.title}
                title={item.title}
                description={item.reason}
                priority={item.priority}
                impact={item.impact}
                related={item.related}
                action={
                  <DashboardLink href={href(item.href)}>
                    {item.cta}
                  </DashboardLink>
                }
              />
            ))}
          </div>
        ) : (
          <EmptyState
            compact
            title="No urgent actions"
            description="No indexing, citation, source, or permission issues need attention in this period."
          />
        )}
      </section>
    </main>
  );
}
