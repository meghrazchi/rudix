"use client";

import { useTranslations } from "next-intl";
import { useAuthSession } from "@/lib/use-auth-session";
import { canViewReportSection, findReportSection } from "@/lib/reports";
import { EmptyState } from "@/components/states/EmptyState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { ReportsOverviewDashboard } from "@/components/reports/ReportsOverviewDashboard";
import { ReportBackendDataProvider } from "@/components/reports/ReportBackendData";
import {
  FeedbackIssuesDashboard,
  SourceHealthDashboard,
} from "@/components/reports/ReportReferenceDashboards";
import { AnswerQualityReportDashboard } from "@/components/reports/AnswerQualityReportDashboard";
import {
  KnowledgeGapsDashboard,
  PermissionsAccessDashboard,
  PersonalReportsOverview,
  UsageAdoptionDashboard,
} from "@/components/reports/ReportOperationalDashboards";

export function ReportSectionPage({ slug }: { slug?: string }) {
  const t = useTranslations("reports");
  const { state } = useAuthSession();
  const section = findReportSection(slug);
  if (state.status === "loading")
    return <LoadingState title={t("states.loadingReport")} />;
  if (!section)
    return (
      <EmptyState
        title={t("states.notFound")}
        description={t("states.notFoundDescription")}
      />
    );
  if (!state.session || !canViewReportSection(state.session.role, section)) {
    return (
      <ForbiddenState
        title={t("states.unavailable")}
        description={t("states.unavailableDescription")}
        backHref="/reports"
        backLabel={t("states.back")}
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
        <AnswerQualityReportDashboard />
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
