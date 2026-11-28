"use client";

import { Download, ReceiptText } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { getBillingCapabilities, getInvoices } from "@/lib/api/billing";
import {
  formatDate,
  formatCurrency,
  InvoiceStatusBadge,
} from "@/components/settings/billing/billingShared";
import { queryKeys } from "@/lib/api/query";

export function InvoiceSection({
  capabilities,
}: {
  capabilities: ReturnType<typeof getBillingCapabilities>;
}) {
  const t = useTranslations("settings.billing");

  const invoicesQuery = useQuery({
    queryKey: queryKeys.billing.invoices,
    queryFn: getInvoices,
    enabled: capabilities.invoicesEnabled,
    retry: false,
  });

  return (
    <section
      className="overflow-hidden rounded-2xl border border-[#c7c4d8] bg-white shadow-sm"
      aria-label="Invoice history section"
    >
      <div className="flex items-center justify-between border-b border-[#e4e1ee] px-6 py-4">
        <div className="flex items-center gap-3">
          <ReceiptText
            size={20}
            className="text-[#3525cd]"
            aria-hidden="true"
          />
          <h2 className="text-lg font-semibold text-[#1b1b24]">
            {t("invoices.title")}
          </h2>
        </div>
      </div>

      {!capabilities.invoicesEnabled ? (
        <div className="p-6">
          <p className="text-sm text-[#777587]">{t("invoices.unavailable")}</p>
        </div>
      ) : invoicesQuery.isLoading ? (
        <div className="p-6">
          <LoadingState compact title={t("invoices.loading")} />
        </div>
      ) : invoicesQuery.isError ? (
        <div className="p-6">
          {isApiClientError(invoicesQuery.error) &&
          invoicesQuery.error.status === 429 ? (
            <RateLimitState
              compact
              onRetry={() => {
                void invoicesQuery.refetch();
              }}
            />
          ) : (
            <ErrorState
              compact
              error={invoicesQuery.error}
              description={getApiErrorMessage(invoicesQuery.error)}
              onRetry={() => {
                void invoicesQuery.refetch();
              }}
            />
          )}
        </div>
      ) : (invoicesQuery.data ?? []).length === 0 ? (
        <div className="p-6">
          <p className="text-sm text-[#777587]">{t("invoices.noInvoices")}</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#f5f2ff] text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
              <tr>
                <th className="px-6 py-3">{t("invoices.invoiceId")}</th>
                <th className="px-6 py-3">{t("invoices.date")}</th>
                <th className="px-6 py-3">{t("invoices.amount")}</th>
                <th className="px-6 py-3">{t("invoices.status")}</th>
                <th className="px-6 py-3 text-right">{t("invoices.action")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e4e1ee]">
              {(invoicesQuery.data ?? []).map((inv) => (
                <tr
                  key={inv.id}
                  className="transition-colors hover:bg-[#f5f2ff]/40"
                >
                  <td className="px-6 py-3 font-mono text-xs text-[#464555]">
                    {inv.id}
                  </td>
                  <td className="px-6 py-3 text-[#1b1b24]">
                    {formatDate(inv.date)}
                  </td>
                  <td className="px-6 py-3 font-semibold text-[#1b1b24]">
                    {formatCurrency(inv.amount_usd)}
                  </td>
                  <td className="px-6 py-3">
                    <InvoiceStatusBadge status={inv.status} />
                  </td>
                  <td className="px-6 py-3 text-right">
                    {inv.download_url ? (
                      <a
                        href={inv.download_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={t("invoices.downloadAriaLabel", {
                          id: inv.id,
                        })}
                        className="inline-flex items-center gap-1 text-xs font-semibold text-[#3525cd] hover:underline"
                      >
                        <Download size={14} aria-hidden="true" />
                        {t("invoices.download")}
                      </a>
                    ) : (
                      <span className="text-xs text-[#aaa6b8]">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Portal Fallback ───────────────────────────────────────────────────────────
