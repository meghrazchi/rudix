"use client";

import { formatDate } from "@/components/documents/detail/detail-format";
import { severityBadgeClass } from "@/components/documents/detail/detail-lifecycle";
import type { DocumentDetailController } from "@/components/documents/detail/useDocumentDetail";

/** Errors tab: severity summary, error log table, and recommendations. */
export function DocumentErrorsTab({ ctl }: { ctl: DocumentDetailController }) {
  const { td, errorRows, errorSummary, recommendations } = ctl;
  return (
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
          <p className="text-2xl font-bold text-[#2a2640]">
            {errorSummary.critical}
          </p>
          <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {td("criticalErrors")}
          </p>
        </div>
        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
          <p className="text-2xl font-bold text-[#2a2640]">
            {errorSummary.warnings}
          </p>
          <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {td("warningsLabel")}
          </p>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-[#e9e6f5]">
        <div className="border-b border-[#e9e6f5] bg-[#faf9ff] px-3 py-2 text-sm font-semibold text-[#2a2640]">
          {td("errorLog")}
        </div>
        {errorRows.length === 0 ? (
          <p className="px-3 py-4 text-sm text-[#69637f]">{td("noErrors")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-[#f7f5ff] text-xs tracking-wide text-[#69637f] uppercase">
                <tr>
                  <th className="px-3 py-2 font-semibold">
                    {td("errorColType")}
                  </th>
                  <th className="px-3 py-2 font-semibold">
                    {td("errorColSeverity")}
                  </th>
                  <th className="px-3 py-2 font-semibold">
                    {td("errorColMessage")}
                  </th>
                  <th className="px-3 py-2 font-semibold">
                    {td("errorColTimestamp")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {errorRows.map((row) => (
                  <tr key={row.key} className="border-t border-[#ece9f8]">
                    <td className="px-3 py-3 text-[#2a2640]">{row.type}</td>
                    <td className="px-3 py-3">
                      <span
                        className={`rounded px-2 py-1 text-[10px] font-bold uppercase ${severityBadgeClass(row.severity)}`}
                      >
                        {row.severity}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-[#2a2640]">
                      {row.message}
                      {row.code ? (
                        <span className="ml-1 font-mono text-xs text-[#69637f]">
                          ({row.code})
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-[#69637f]">
                      {formatDate(row.timestamp)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-[#d9d4f1] bg-[#f5f3ff] px-4 py-3">
        <p className="mb-2 text-sm font-semibold text-[#2a2640]">
          {td("recommendations")}
        </p>
        <ul className="list-disc space-y-1 pl-4 text-sm text-[#4d4868]">
          {recommendations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
