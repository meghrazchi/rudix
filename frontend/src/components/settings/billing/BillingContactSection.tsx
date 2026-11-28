"use client";

import { AlertTriangle, CreditCard, ExternalLink, Zap } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { getBillingCapabilities, getBillingContact } from "@/lib/api/billing";
import {
  SectionHeader,
  DeploymentControlledBadge,
} from "@/components/settings/billing/billingShared";
import { queryKeys } from "@/lib/api/query";

export function BillingPortalFallback({
  portalUrl,
  deploymentControlledLabel,
}: {
  portalUrl: string | null;
  deploymentControlledLabel: string;
}) {
  const t = useTranslations("settings.billing.portal");

  return (
    <section
      className="rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-sm"
      aria-label="Billing portal section"
    >
      <div className="mb-3 flex items-center gap-3">
        <CreditCard size={20} className="text-[#3525cd]" aria-hidden="true" />
        <h2 className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
          {t("title")}
        </h2>
        <DeploymentControlledBadge label={deploymentControlledLabel} />
      </div>
      <p className="mb-4 text-sm text-[#4d4963]">{t("desc")}</p>
      {portalUrl ? (
        <a
          href={portalUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-xl border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
        >
          {t("openPortal")}
          <ExternalLink size={14} aria-hidden="true" />
        </a>
      ) : (
        <p className="text-sm text-[#777587]">{t("noPortalUrl")}</p>
      )}
    </section>
  );
}

// ── Billing Notifications Info ────────────────────────────────────────────────

export function BillingNotificationsInfo() {
  const t = useTranslations("settings.billing.alerts");

  const alerts = [
    { labelKey: "quota80", descKey: "quota80Desc" },
    { labelKey: "quota90", descKey: "quota90Desc" },
    { labelKey: "quotaExceeded", descKey: "quotaExceededDesc" },
    { labelKey: "failedPayments", descKey: "failedPaymentsDesc" },
    { labelKey: "invoiceAvailable", descKey: "invoiceAvailableDesc" },
  ];

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm"
      aria-label="Billing notifications section"
    >
      <SectionHeader icon={AlertTriangle} title={t("title")} />
      <div className="space-y-3">
        {alerts.map(({ labelKey, descKey }) => (
          <div
            key={labelKey}
            className="flex items-start gap-3 rounded-lg border border-[#ebe8f7] bg-[#f5f2ff]/40 px-4 py-3"
          >
            <Zap
              size={14}
              className="mt-0.5 shrink-0 text-[#3525cd]"
              aria-hidden="true"
            />
            <div>
              <p className="text-sm font-semibold text-[#1b1b24]">
                {t(labelKey)}
              </p>
              <p className="text-xs text-[#464555]">{t(descKey)}</p>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-[#777587]">{t("deliveryNote")}</p>
    </section>
  );
}

export function BillingContactSection({
  capabilities,
  canViewBilling,
}: {
  capabilities: ReturnType<typeof getBillingCapabilities>;
  canViewBilling: boolean;
}) {
  const t = useTranslations("settings.billing");

  const contactQuery = useQuery({
    queryKey: queryKeys.billing.contact,
    queryFn: getBillingContact,
    enabled: capabilities.billingContactEnabled && canViewBilling,
    retry: false,
  });

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm"
      aria-label="Billing contact section"
    >
      <SectionHeader icon={CreditCard} title={t("contact.title")} />

      {!capabilities.billingContactEnabled ? (
        <p className="text-sm text-[#777587]">{t("contact.unavailable")}</p>
      ) : contactQuery.isLoading ? (
        <LoadingState compact title={t("contact.loading")} />
      ) : contactQuery.isError ? (
        isApiClientError(contactQuery.error) &&
        contactQuery.error.status === 429 ? (
          <RateLimitState
            compact
            onRetry={() => {
              void contactQuery.refetch();
            }}
          />
        ) : (
          <ErrorState
            compact
            error={contactQuery.error}
            description={getApiErrorMessage(contactQuery.error)}
            onRetry={() => {
              void contactQuery.refetch();
            }}
          />
        )
      ) : (
        <div className="space-y-4">
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[
              {
                labelKey: "contact.billingContact",
                value:
                  contactQuery.data?.name ?? contactQuery.data?.email ?? "—",
              },
              {
                labelKey: "contact.email",
                value: contactQuery.data?.email ?? "—",
              },
              {
                labelKey: "contact.address",
                value:
                  contactQuery.data?.address_line1 ??
                  contactQuery.data?.address_line2 ??
                  t("contact.addressDefault"),
              },
              {
                labelKey: "contact.paymentMethod",
                value:
                  contactQuery.data?.payment_method_summary ??
                  t("contact.paymentMethodDefault"),
              },
            ].map(({ labelKey, value }) => (
              <div
                key={labelKey}
                className="rounded-xl border border-[#ebe8f7] bg-[#f8f7ff] px-4 py-3"
              >
                <dt className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                  {t(labelKey)}
                </dt>
                <dd className="mt-1 text-sm font-medium text-[#1b1b24]">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-[#777587]">{t("contact.note")}</p>
        </div>
      )}
    </section>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
