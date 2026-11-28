"use client";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { formatInteger } from "@/lib/dashboard";
import {
  AUDIT_PAGE_LIMIT,
  formatTimestamp,
  resultPillClass,
  getActorLabel,
} from "@/components/admin/audit-logs/auditShared";
import { useAuditLogsController } from "@/components/admin/audit-logs/useAuditLogsController";

export function AuditResultsTable({
  ctl,
}: {
  ctl: ReturnType<typeof useAuditLogsController>;
}) {
  const {
    t,
    setOffset,
    selectedEvent,
    auditQuery,
    endpointUnavailable,
    rows,
    pageTotal,
    pageStart,
    pageEnd,
    hasPreviousPage,
    hasNextPage,
    openEventDetails,
  } = ctl;

  return (
    <section className="overflow-hidden rounded-xl border border-[#c7c4d8] bg-white shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#e4e1ee] bg-[#f5f2ff] px-4 py-3">
        <h2 className="text-lg font-semibold text-[#1b1b24]">
          {t("auditEvents")}
        </h2>
        {auditQuery.isSuccess ? (
          <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("showingCompact", {
              start: formatInteger(pageStart),
              end: formatInteger(pageEnd),
              total: formatInteger(pageTotal),
            })}
          </p>
        ) : null}
      </div>

      {endpointUnavailable ? (
        <EmptyState
          compact
          className="m-4 rounded-lg border border-dashed border-[#d7d4e8] bg-[#fcfbff] px-3 py-3"
          title={t("endpointUnavailable")}
          description={t("endpointUnavailableDescription")}
        />
      ) : null}
      {auditQuery.isLoading ? (
        <LoadingState
          compact
          className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
          title={t("loading")}
        />
      ) : null}
      {auditQuery.isError && !endpointUnavailable ? (
        <div className="m-4">
          <ErrorState
            compact
            error={auditQuery.error}
            description={getApiErrorMessage(auditQuery.error)}
            onRetry={() => {
              void auditQuery.refetch();
            }}
          />
        </div>
      ) : null}
      {auditQuery.isSuccess && rows.length === 0 ? (
        <EmptyState
          compact
          className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
          title={t("empty")}
        />
      ) : null}

      {auditQuery.isSuccess && rows.length > 0 ? (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead className="border-b border-[#e4e1ee] bg-[#fcf8ff]">
                <tr className="text-left text-[11px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  <th className="px-4 py-3">{t("timestampUtc")}</th>
                  <th className="px-4 py-3">{t("actor")}</th>
                  <th className="px-4 py-3">{t("action")}</th>
                  <th className="px-4 py-3">{t("entity")}</th>
                  <th className="px-4 py-3 text-center">{t("result")}</th>
                  <th className="px-4 py-3">{t("ipAddress")}</th>
                  <th className="px-4 py-3">{t("details")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#ece9f5]">
                {rows.map((item) => {
                  const isSelected =
                    selectedEvent?.audit_log_id === item.audit_log_id;

                  return (
                    <tr
                      key={item.audit_log_id}
                      onClick={(event) =>
                        openEventDetails(item, event.currentTarget)
                      }
                      className={`cursor-pointer transition-colors ${
                        isSelected ? "bg-[#ebe8ff]" : "hover:bg-[#f5f2ff]"
                      }`}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-[#464555]">
                        {formatTimestamp(item.created_at)}
                      </td>
                      <td className="px-4 py-3 text-sm font-medium text-[#1b1b24]">
                        {getActorLabel(item, t("system"))}
                      </td>
                      <td className="px-4 py-3">
                        <span className="rounded border border-[#c7c4d8] bg-[#f5f2ff] px-2 py-1 font-mono text-[11px] text-[#2b1fa8] uppercase">
                          {item.action}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-[#302f39]">
                        {item.resource_type}
                        {item.resource_id ? `:${item.resource_id}` : ""}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span
                          className={`rounded-full px-2 py-1 text-[10px] font-semibold tracking-wide uppercase ${resultPillClass(
                            item.result,
                          )}`}
                        >
                          {t(item.result ?? "unknown")}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-[#464555]">
                        {item.ip_address ?? "-"}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            openEventDetails(item, event.currentTarget);
                          }}
                          className="rounded-lg border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f2ff]"
                        >
                          {t("viewDetails")}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-[#e4e1ee] px-4 py-3">
            <p className="text-sm text-[#464555]">
              {t("showingEvents", {
                start: formatInteger(pageStart),
                end: formatInteger(pageEnd),
                total: formatInteger(pageTotal),
              })}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() =>
                  setOffset((previous) =>
                    Math.max(0, previous - AUDIT_PAGE_LIMIT),
                  )
                }
                disabled={!hasPreviousPage || auditQuery.isFetching}
                className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("previous")}
              </button>
              <button
                type="button"
                onClick={() =>
                  setOffset((previous) => previous + AUDIT_PAGE_LIMIT)
                }
                disabled={!hasNextPage || auditQuery.isFetching}
                className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("next")}
              </button>
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}
