"use client";

import { useAuthSession } from "@/lib/use-auth-session";
import { canViewReportSection, findReportSection } from "@/lib/reports";
import { EmptyState } from "@/components/states/EmptyState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { ReportsOverviewDashboard } from "@/components/reports/ReportsOverviewDashboard";
import { ReportBackendDataProvider } from "@/components/reports/ReportBackendData";
import {
  AnswerQualityDashboard,
  FeedbackIssuesDashboard,
  SourceHealthDashboard,
} from "@/components/reports/ReportReferenceDashboards";
import {
  KnowledgeGapsDashboard,
  PermissionsAccessDashboard,
  PersonalReportsOverview,
  UsageAdoptionDashboard,
} from "@/components/reports/ReportOperationalDashboards";

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
  if (section.id === "answer-quality")
    return (
      <ReportBackendDataProvider>
        <AnswerQualityDashboard />
      </ReportBackendDataProvider>
    );
  if (section.id === "source-health")
    return (
      <ReportBackendDataProvider>
        <SourceHealthDashboard />
      </ReportBackendDataProvider>
    );
  if (section.id === "usage-adoption")
    return (
      <ReportBackendDataProvider>
        <UsageAdoptionDashboard />
      </ReportBackendDataProvider>
    );
  if (section.id === "permissions-access")
    return (
      <ReportBackendDataProvider>
        <PermissionsAccessDashboard />
      </ReportBackendDataProvider>
    );
  if (section.id === "feedback-issues")
    return (
      <ReportBackendDataProvider>
        <FeedbackIssuesDashboard />
      </ReportBackendDataProvider>
    );
  if (section.id === "knowledge-gaps")
    return (
      <ReportBackendDataProvider>
        <KnowledgeGapsDashboard />
      </ReportBackendDataProvider>
    );
  return <PersonalReportsOverview />;
}
