"use client";

import { useQuery } from "@tanstack/react-query";
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
  const { filters } = useReportFilters();
  const query = useQuery({
    queryKey: ["report-detail-data", filters],
    queryFn: () => getReportsOverview(filters),
  });

  if (query.isLoading) {
    return (
      <LoadingState
        title="Loading report data"
        description="Applying your filters to organization-scoped metrics."
      />
    );
  }
  if (query.isError || !query.data) {
    return (
      <ErrorState
        title="Report data unavailable"
        description="The report could not be loaded from the backend."
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <ReportBackendDataContext.Provider value={query.data}>
      <div className="grid gap-6">
        {query.data.unavailable.length ? (
          <PartialDataState
            message={`${query.data.unavailable.join(", ")} could not be loaded for your current role or filter scope.`}
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
