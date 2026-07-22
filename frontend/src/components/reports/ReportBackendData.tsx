"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { createContext, useContext, type ReactNode } from "react";
import { useReportFilters } from "@/components/reports/ReportFilters";
import { PartialDataState } from "@/components/reports/report-ui";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  getReportsOverview,
  type ReportsOverviewData,
} from "@/lib/reports-overview";

const ReportBackendDataContext = createContext<ReportsOverviewData | null>(
  null,
);

export function ReportBackendDataProvider({
  children,
}: {
  children: ReactNode;
}) {
  const t = useTranslations("reports.pages.backend");
  const { filters } = useReportFilters();
  const query = useQuery({
    queryKey: ["report-detail-data", filters],
    queryFn: () => getReportsOverview(filters),
  });

  if (query.isLoading) {
    return (
      <LoadingState
        title={t("loading")}
        description={t("loadingDescription")}
      />
    );
  }
  if (query.isError || !query.data) {
    return (
      <ErrorState
        title={t("error")}
        description={t("errorDescription")}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <ReportBackendDataContext.Provider value={query.data}>
      <div className="grid gap-6">
        {query.data.unavailable.length ? (
          <PartialDataState
            message={t("partial", {
              sources: query.data.unavailable.join(", "),
            })}
          />
        ) : null}
        {children}
      </div>
    </ReportBackendDataContext.Provider>
  );
}

export function useReportBackendData(): ReportsOverviewData {
  const value = useContext(ReportBackendDataContext);
  if (!value) {
    throw new Error(
      "useReportBackendData must be used inside ReportBackendDataProvider",
    );
  }
  return value;
}
