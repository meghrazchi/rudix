"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { usePathname, useSearchParams } from "next/navigation";
import { useAuthSession } from "@/lib/use-auth-session";
import { getVisibleReportSections } from "@/lib/reports";
import {
  GlobalReportFilters,
  ReportFiltersProvider,
} from "@/components/reports/ReportFilters";
import { LoadingState } from "@/components/states/LoadingState";

export function ReportsShell({ children }: { children: React.ReactNode }) {
  return (
    <ReportFiltersProvider>
      <ReportsShellContent>{children}</ReportsShellContent>
    </ReportFiltersProvider>
  );
}

function ReportsShellContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { state } = useAuthSession();
  const t = useTranslations("reports");
  if (state.status === "loading" || !state.session)
    return (
      <LoadingState
        title={t("states.loadingReports")}
        description={t("states.loadingReportsDescription")}
      />
    );
  const sections = getVisibleReportSections(state.session.role);
  const query = searchParams.toString();
  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <nav
        aria-label={t("sectionsLabel")}
        className="overflow-x-auto border-b border-[#dfdced] pb-px"
      >
        <div className="flex min-w-max gap-1">
          {sections.map((section) => {
            const active =
              section.id === "overview"
                ? pathname === "/reports"
                : pathname === section.href;
            return (
              <Link
                key={section.id}
                href={query ? `${section.href}?${query}` : section.href}
                aria-current={active ? "page" : undefined}
                className={`border-b-2 px-3 py-2 text-sm font-semibold ${active ? "border-[#3525cd] text-[#3525cd]" : "border-transparent text-[#68647b] hover:text-[#2a2640]"}`}
              >
                {t(`sections.${section.id}.label`)}
              </Link>
            );
          })}
        </div>
      </nav>
      <GlobalReportFilters />
      {children}
    </section>
  );
}
