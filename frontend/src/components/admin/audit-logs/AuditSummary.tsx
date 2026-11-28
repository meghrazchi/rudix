"use client";

import { getApiErrorMessage } from "@/lib/api/errors";
import { formatInteger } from "@/lib/dashboard";
import { useAuditLogsController } from "@/components/admin/audit-logs/useAuditLogsController";

export function AuditSummary({
  ctl,
}: {
  ctl: ReturnType<typeof useAuditLogsController>;
}) {
  const {
    t,
    exportsEnabled,
    exportMutation,
    pageTotal,
    uniqueActors,
    securityAlerts,
  } = ctl;

  return (
    <>
      <header className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-semibold tracking-[0.16em] text-[#3525cd] uppercase">
              {t("eyebrow")}
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-[#1b1b24]">
              {t("title")}
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-[#464555]">
              {t("description")}
            </p>
          </div>

          <div className="flex flex-wrap items-end gap-2">
            {exportsEnabled ? (
              <>
                <button
                  type="button"
                  onClick={() => exportMutation.mutate("csv")}
                  disabled={exportMutation.isPending}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-4 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {exportMutation.isPending
                    ? t("preparingExport")
                    : t("exportCsv")}
                </button>
                <button
                  type="button"
                  onClick={() => exportMutation.mutate("json")}
                  disabled={exportMutation.isPending}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-4 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {t("exportJson")}
                </button>
              </>
            ) : null}
          </div>
        </div>

        {exportMutation.isError ? (
          <p className="mt-3 text-sm text-rose-700">
            {getApiErrorMessage(exportMutation.error)}
          </p>
        ) : null}
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <article className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("totalEvents")}
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-[#1b1b24]">
            {formatInteger(pageTotal)}
          </p>
        </article>

        <article className="rounded-xl border border-rose-200 bg-rose-50/50 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-rose-700 uppercase">
            {t("securityAlerts")}
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-rose-700">
            {formatInteger(securityAlerts)}
          </p>
        </article>

        <article className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("uniqueActors")}
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-[#1b1b24]">
            {formatInteger(uniqueActors)}
          </p>
        </article>

        <article className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-emerald-700 uppercase">
            {t("exportStatus")}
          </p>
          <p className="mt-2 text-lg font-semibold text-emerald-700">
            {exportsEnabled ? t("ready") : t("disabled")}
          </p>
        </article>
      </section>
    </>
  );
}
