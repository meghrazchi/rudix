"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ArrowRight, FileUp, MessageSquareText } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
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

const links = {
  quality: "/reports/answer-quality",
  sources: "/reports/source-health",
  usage: "/reports/usage-adoption",
  permissions: "/reports/permissions-access",
  feedback: "/reports/feedback-issues",
  gaps: "/reports/knowledge-gaps",
};

const BAR_COLORS = {
  default: "#6254d9",
  healthy: "#10b981",
  warning: "#f59e0b",
  critical: "#f43f5e",
} as const;

type BarTone = Exclude<keyof typeof BAR_COLORS, "default">;

function reportHref(pathname: string, filters: ReportFilters): string {
  const query = serializeReportFilters(filters).toString();
  return query ? `${pathname}?${query}` : pathname;
}

function Bars({
  items,
}: {
  items: Array<{ label: string; value: number; tone?: BarTone }>;
}) {
  const t = useTranslations("reports.overview");
  const locale = useLocale();
  const format = new Intl.NumberFormat(locale, {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  if (!items.some((item) => item.value > 0))
    return (
      <EmptyState
        compact
        title={t("emptyChart.title")}
        description={t("emptyChart.description")}
      />
    );
  return (
    <div
      className="h-44 w-full"
      role="img"
      aria-label={items
        .map((item) => `${item.label}: ${item.value}`)
        .join(", ")}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={items}
          layout="vertical"
          margin={{ left: 4, right: 16 }}
        >
          <CartesianGrid horizontal={false} stroke="#ece9f7" />
          <XAxis type="number" hide domain={[0, "dataMax"]} />
          <YAxis
            type="category"
            dataKey="label"
            width={92}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#5f5b72", fontSize: 11 }}
          />
          <Tooltip
            formatter={(value) => format.format(Number(value))}
            contentStyle={{ borderRadius: 8, borderColor: "#dfdced" }}
          />
          <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={10}>
            {items.map((item) => (
              <Cell
                key={item.label}
                fill={item.tone ? BAR_COLORS[item.tone] : BAR_COLORS.default}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
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
  const t = useTranslations("reports.overview");
  const tReports = useTranslations("reports");
  const locale = useLocale();
  const format = new Intl.NumberFormat(locale, {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  const { filters } = useReportFilters();
  const query = useQuery({
    queryKey: ["reports-overview", filters],
    queryFn: () => getReportsOverview(filters),
  });
  if (query.isLoading)
    return (
      <LoadingState
        title={t("loading.title")}
        description={t("loading.description")}
      />
    );
  if (query.isError || !query.data)
    return (
      <ErrorState
        title={t("error.title")}
        description={t("error.description")}
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
  const connectorItems = (data.connectors?.items ?? []).filter(
    (connector) =>
      filters.connector === "all" || connector.id === filters.connector,
  );
  const healthyConnectors = connectorItems.filter(
    (connector) => connector.status === "active" && !connector.error_message,
  ).length;
  const unhealthyConnectors = connectorItems.length - healthyConnectors;
  const href = (pathname: string) => reportHref(pathname, filters);

  return (
    <main className="grid gap-6">
      <ReportHeader
        title={tReports("sections.overview.label")}
        description={tReports("sections.overview.description")}
      />
      {data.unavailable.length ? (
        <PartialDataState
          message={t("partialData", {
            sources: data.unavailable
              .map((source) => t(`dataSources.${source}`))
              .join(", "),
          })}
        />
      ) : null}
      {empty ? (
        <EmptyState
          title={t("empty.title")}
          description={t("empty.description")}
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <DashboardLink href="/documents">
                <FileUp className="h-3 w-3" aria-hidden />
                {t("empty.uploadSources")}
              </DashboardLink>
              <DashboardLink href="/chat">
                <MessageSquareText className="h-3 w-3" aria-hidden />
                {t("empty.askQuestion")}
              </DashboardLink>
            </div>
          }
        />
      ) : null}
      <section
        aria-label={t("kpis.ariaLabel")}
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8"
      >
        <KpiCard
          label={t("kpis.questions.label")}
          value={format.format(kpis.questions)}
          href={href(links.usage)}
          description={t("kpis.questions.description")}
        />
        <KpiCard
          label={t("kpis.trusted.label")}
          value={format.format(kpis.trustedAnswers)}
          href={href(links.quality)}
          description={t("kpis.trusted.description")}
        />
        <KpiCard
          label={t("kpis.lowConfidence.label")}
          value={format.format(kpis.lowConfidence)}
          href={href(links.quality)}
          description={t("kpis.lowConfidence.description")}
        />
        <KpiCard
          label={t("kpis.citations.label")}
          value={format.format(kpis.citationIssues)}
          href={href(links.quality)}
          description={t("kpis.citations.description")}
        />
        <KpiCard
          label={t("kpis.sources.label")}
          value={format.format(kpis.sourcesNeedingReview)}
          href={href(links.sources)}
          description={t("kpis.sources.description")}
        />
        <KpiCard
          label={t("kpis.users.label")}
          value={format.format(kpis.activeUsers)}
          href={href(links.usage)}
          description={t("kpis.users.description")}
        />
        <KpiCard
          label={t("kpis.indexing.label")}
          value={format.format(kpis.failedIndexingJobs)}
          href={href(links.sources)}
          description={t("kpis.indexing.description")}
        />
        <KpiCard
          label={t("kpis.permissions.label")}
          value={format.format(kpis.permissionConflicts)}
          href={href(links.permissions)}
          description={t("kpis.permissions.description")}
        />
      </section>

      <section
        aria-label={t("charts.ariaLabel")}
        className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
      >
        <ChartCard
          title={t("charts.confidence.title")}
          description={t("charts.confidence.description")}
          href={href(links.quality)}
        >
          <Bars
            items={[
              {
                label: t("levels.high"),
                value: trust?.high_count ?? 0,
                tone: "healthy",
              },
              {
                label: t("levels.medium"),
                value: trust?.medium_count ?? 0,
                tone: "warning",
              },
              {
                label: t("levels.low"),
                value: trust?.low_count ?? 0,
                tone: "critical",
              },
            ]}
          />
        </ChartCard>
        <ChartCard
          title={t("charts.questions.title")}
          description={t("charts.questions.description")}
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
          title={t("charts.sources.title")}
          description={t("charts.sources.description")}
          href={href(links.sources)}
        >
          <Bars
            items={[
              {
                label: t("warnings.stale"),
                value: warnings?.stale_source_count ?? 0,
              },
              { label: t("warnings.ocr"), value: warnings?.ocr_count ?? 0 },
              {
                label: t("warnings.extraction"),
                value: warnings?.extraction_count ?? 0,
              },
              {
                label: t("warnings.processing"),
                value: warnings?.processing_count ?? 0,
              },
            ]}
          />
        </ChartCard>
        <ChartCard
          title={t("charts.feedback.title")}
          description={t("charts.feedback.description")}
          href={href(links.feedback)}
        >
          <Bars
            items={(data.analytics?.top_feedback_categories ?? [])
              .slice(0, 5)
              .map((item) => ({ label: item.category, value: item.count }))}
          />
        </ChartCard>
        <ChartCard
          title={t("charts.users.title")}
          description={t("charts.users.description")}
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
          title={t("charts.gaps.title")}
          description={t("charts.gaps.description")}
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
          title={t("charts.connectors.title")}
          description={t("charts.connectors.description")}
          href={href(links.sources)}
        >
          <Bars
            items={[
              {
                label: t("status.healthy"),
                value: healthyConnectors,
                tone: "healthy",
              },
              {
                label: t("status.failed"),
                value: unhealthyConnectors,
                tone: "critical",
              },
            ]}
          />
        </ChartCard>
        <ChartCard
          title={t("charts.permissions.title")}
          description={t("charts.permissions.description")}
          href={href(links.permissions)}
        >
          <Bars
            items={["security_risk", "blocking", "warning", "info"].map(
              (severity) => ({
                label: t(`severity.${severity}`),
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
            {t("actions.title")}
          </h2>
          <StatusBadge
            label={
              actions.length
                ? t("actions.toReview", { count: actions.length })
                : t("actions.allClear")
            }
            tone={actions.length ? "warning" : "healthy"}
          />
        </div>
        {actions.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {actions.map((item) => (
              <RecommendedActionCard
                key={item.id}
                title={t(`actions.items.${item.id}.title`)}
                description={t(`actions.items.${item.id}.reason`, {
                  count: item.count,
                })}
                priority={
                  item.priority === "High"
                    ? t("levels.high")
                    : t("levels.medium")
                }
                prioritySuffix={t("actions.prioritySuffix")}
                impact={t(`actions.items.${item.id}.impact`)}
                related={t(`actions.items.${item.id}.related`)}
                relatedPrefix={t("actions.relatedPrefix")}
                action={
                  <DashboardLink href={href(item.href)}>
                    {t(`actions.items.${item.id}.cta`)}
                  </DashboardLink>
                }
              />
            ))}
          </div>
        ) : (
          <EmptyState
            compact
            title={t("actions.empty.title")}
            description={t("actions.empty.description")}
          />
        )}
      </section>
    </main>
  );
}
