"use client";

import { ShieldCheck } from "lucide-react";
import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { getJwtExpirationTimeMs } from "@/lib/api/request";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import {
  formatAuthProvider,
  formatExpiryMs,
  SectionHeader,
  BoolBadge,
  type SecuritySession,
} from "@/components/settings/security/securityShared";

export function AuthDiagnosticsSection({
  session,
}: {
  session: SecuritySession;
}) {
  const t = useTranslations("settings.security");

  const config = useMemo(() => getFrontendRuntimeConfig(), []);

  const sessionExpiryMs = getJwtExpirationTimeMs(session?.accessToken ?? null);

  const authFacts = useMemo(
    () => [
      {
        label: t("auth.authProvider"),
        value: formatAuthProvider(config.authProviderRaw),
        isBoolean: false,
      },
      {
        label: t("auth.email"),
        value: session?.email ?? t("auth.unknown"),
        isBoolean: false,
      },
      {
        label: t("auth.role"),
        value: session?.role ?? t("auth.unknown"),
        isBoolean: false,
      },
      {
        label: t("auth.accessTokenAttached"),
        value: session?.accessToken ? t("auth.yes") : t("auth.no"),
        isBoolean: true,
      },
      {
        label: t("auth.refreshCookie"),
        value: t("auth.refreshCookieValue"),
        isBoolean: false,
      },
      {
        label: t("auth.sessionExpiry"),
        value: formatExpiryMs(sessionExpiryMs),
        isBoolean: false,
      },
      {
        label: t("auth.organizationId"),
        value: session?.organizationId ?? t("auth.notAssigned"),
        isBoolean: false,
      },
    ],
    [
      t,
      config.authProviderRaw,
      session?.email,
      session?.role,
      session?.accessToken,
      session?.organizationId,
      sessionExpiryMs,
    ],
  );

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Authentication diagnostics section"
    >
      <SectionHeader icon={ShieldCheck} title={t("auth.title")} />
      <dl className="space-y-3">
        {authFacts.map((fact) => (
          <div
            key={fact.label}
            className="flex items-center justify-between gap-4 rounded-lg border border-[#ebe8f7] px-4 py-2"
          >
            <dt className="text-sm font-semibold text-[#5c5871]">
              {fact.label}
            </dt>
            <dd>
              {fact.isBoolean ? (
                <BoolBadge
                  value={fact.value === t("auth.yes")}
                  yesLabel={t("auth.yes")}
                  noLabel={t("auth.no")}
                />
              ) : (
                <span className="text-sm text-[#1b1b24]">{fact.value}</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-[#777587]">{t("auth.tokenNote")}</p>
    </section>
  );
}
