"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import {
  DEFAULT_REPORT_FILTERS,
  REPORT_FILTER_KEYS,
  parseReportFilters,
  serializeReportFilters,
  type ReportFilterKey,
  type ReportFilters,
} from "@/lib/reports";
import { listConnectorConnections } from "@/lib/api/connectors";
import { queryKeys } from "@/lib/api/query";

type FilterContextValue = {
  filters: ReportFilters;
  setFilter: (key: ReportFilterKey, value: string) => void;
  resetFilters: () => void;
};
const FilterContext = createContext<FilterContextValue | null>(null);

export function ReportFiltersProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const filters = useMemo(
    () => parseReportFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const navigate = useCallback(
    (next: ReportFilters) => {
      const query = serializeReportFilters(next).toString();
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [pathname, router],
  );
  const value = useMemo<FilterContextValue>(
    () => ({
      filters,
      setFilter: (key, nextValue) => navigate({ ...filters, [key]: nextValue }),
      resetFilters: () => navigate(DEFAULT_REPORT_FILTERS),
    }),
    [filters, navigate],
  );
  return (
    <FilterContext.Provider value={value}>{children}</FilterContext.Provider>
  );
}

export function useReportFilters(): FilterContextValue {
  const value = useContext(FilterContext);
  if (!value)
    throw new Error(
      "useReportFilters must be used inside ReportFiltersProvider",
    );
  return value;
}

const OPTIONS: Record<ReportFilterKey, Array<[string, string]>> = {
  date: [
    ["7d", "Last 7 days"],
    ["30d", "Last 30 days"],
    ["90d", "Last 90 days"],
    ["all", "All time"],
  ],
  workspace: [
    ["all", "All workspaces"],
    ["current", "Current workspace"],
  ],
  team: [
    ["all", "All teams"],
    ["mine", "My team"],
  ],
  user: [
    ["all", "All users"],
    ["me", "Me"],
  ],
  collection: [["all", "All collections"]],
  connector: [["all", "All connectors"]],
  language: [
    ["all", "All languages"],
    ["en", "English"],
    ["de", "German"],
    ["es", "Spanish"],
    ["fr", "French"],
  ],
  model: [["all", "All models / providers"]],
  confidence: [
    ["all", "All confidence"],
    ["high", "High"],
    ["medium", "Medium"],
    ["low", "Low"],
  ],
};

export function GlobalReportFilters() {
  const t = useTranslations("reports.filters");
  const { filters, setFilter, resetFilters } = useReportFilters();
  const connectorsQuery = useQuery({
    queryKey: queryKeys.connectorConnections,
    queryFn: listConnectorConnections,
    staleTime: 60_000,
  });
  const connectorOptions = [
    ...OPTIONS.connector,
    ...(connectorsQuery.data?.items ?? []).map(
      (connector) => [connector.id, connector.display_name] as [string, string],
    ),
  ];
  const changed = REPORT_FILTER_KEYS.some(
    (key) => filters[key] !== DEFAULT_REPORT_FILTERS[key],
  );
  return (
    <section
      aria-label={t("ariaLabel")}
      className="rounded-xl border border-[#dfdced] bg-white p-4 shadow-sm lg:p-5"
    >
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 className="text-sm font-bold text-[#2a2640]">{t("title")}</h2>
        <button
          type="button"
          onClick={resetFilters}
          disabled={!changed}
          className="text-xs font-bold text-[#3525cd] disabled:text-slate-400"
        >
          {t("reset")}
        </button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {REPORT_FILTER_KEYS.map((key) => (
          <label
            className="grid gap-1 text-xs font-semibold text-[#5f5b72]"
            key={key}
          >
            {t(`labels.${key}`)}
            <select
              aria-label={t(`labels.${key}`)}
              value={filters[key]}
              onChange={(event) => setFilter(key, event.target.value)}
              className="min-w-0 rounded-lg border border-[#d7d4e7] bg-white px-3 py-2 text-sm text-[#2a2640]"
            >
              {(key === "connector" ? connectorOptions : OPTIONS[key]).map(
                ([value, fallbackLabel]) => (
                  <option value={value} key={value}>
                    {key === "connector" && value !== "all"
                      ? fallbackLabel
                      : t(`options.${key}.${value}`)}
                  </option>
                ),
              )}
            </select>
          </label>
        ))}
      </div>
    </section>
  );
}
