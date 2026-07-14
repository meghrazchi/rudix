"use client";

import { useAuthSession } from "@/lib/use-auth-session";
import { canViewReportSection, findReportSection } from "@/lib/reports";
import {
  ChartCard,
  KpiCard,
  PartialDataState,
  RecommendedActionCard,
  ReportDataTable,
  ReportHeader,
  StatusBadge,
} from "@/components/reports/report-ui";
import { EmptyState } from "@/components/states/EmptyState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { ReportsOverviewDashboard } from "@/components/reports/ReportsOverviewDashboard";

export function ReportSectionPage({ slug }: { slug?: string }) {
  const { state } = useAuthSession();
  const section = findReportSection(slug);
  if (state.status === "loading")
    return <LoadingState title="Loading report" />;
  if (!section)
    return (
      <EmptyState
        title="Report not found"
        description="This report section does not exist or is not available yet."
      />
    );
  if (!state.session || !canViewReportSection(state.session.role, section)) {
    return (
      <ForbiddenState
        title="Report unavailable"
        description="Your role does not have permission to view this report section."
        backHref="/reports"
        backLabel="Back to reports"
      />
    );
  }
  if (
    section.id === "overview" &&
    (state.session.role === "admin" || state.session.role === "owner")
  ) {
    return <ReportsOverviewDashboard />;
  }
  return (
    <main className="grid gap-5">
      <div>
        <ReportHeader title={section.label} description={section.description} />
      </div>
      <PartialDataState message="Some report data sources are not connected yet. Available metrics are shown without estimates." />
      <section
        aria-label="Key performance indicators"
        className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
      >
        <KpiCard
          label="Questions"
          value="—"
          description="No report data in this period"
        />
        <KpiCard
          label="Average confidence"
          value="—"
          description="Waiting for answer metrics"
        />
        <KpiCard
          label="Helpful feedback"
          value="—"
          description="Waiting for feedback events"
        />
        <KpiCard
          label="Active sources"
          value="—"
          description="Waiting for source metrics"
        />
      </section>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)]">
        <ChartCard
          title={`${section.label} trend`}
          description="Updates when report data becomes available."
        >
          <EmptyState
            compact
            title="No trend data"
            description="Try another date range or broaden the global filters."
          />
        </ChartCard>
        <RecommendedActionCard
          title="Connect report data"
          description="This shell is ready for the section-specific metrics endpoint. Filters and role scope will be applied consistently."
        />
      </div>
      <ReportDataTable
        caption={`${section.label} details`}
        columns={["Metric", "Status", "Scope"]}
        rows={[
          [
            "Report data",
            <StatusBadge key="status" label="Awaiting data" tone="neutral" />,
            state.session.role === "admin" || state.session.role === "owner"
              ? "Workspace"
              : "Personal",
          ],
        ]}
      />
    </main>
  );
}
