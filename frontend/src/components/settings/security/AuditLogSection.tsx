"use client";

import { ClipboardList } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getSecurityCapabilities,
  getRecentAuditEvents,
} from "@/lib/api/security";
import { queryKeys } from "@/lib/api/query";
import {
  SectionHeader,
  DeploymentControlledBadge,
  AuditEventPreview,
} from "@/components/settings/security/securityShared";

export function AuditLogSection({
  capabilities,
  isAdmin,
  auditPageUrl,
  auditExportUrl,
}: {
  capabilities: ReturnType<typeof getSecurityCapabilities>;
  isAdmin: boolean;
  auditPageUrl: string | null;
  auditExportUrl: string | null;
}) {
  const t = useTranslations("settings.security");

  const auditQuery = useQuery({
    queryKey: queryKeys.securityAudit,
    queryFn: getRecentAuditEvents,
    enabled: capabilities.auditEnabled && isAdmin,
    retry: false,
  });

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Audit log section"
    >
      <SectionHeader
        icon={ClipboardList}
        title={t("audit.title")}
        badge={
          !capabilities.auditEnabled && (
            <DeploymentControlledBadge label={t("deploymentControlled")} />
          )
        }
      />

      {!isAdmin ? (
        <p className="text-sm text-[#777587]">{t("audit.restricted")}</p>
      ) : !capabilities.auditEnabled ? (
        <p className="text-sm text-[#777587]">{t("audit.unavailable")}</p>
      ) : auditQuery.isLoading ? (
        <LoadingState compact title={t("audit.loading")} />
      ) : auditQuery.isError ? (
        <ErrorState
          compact
          error={auditQuery.error}
          description={getApiErrorMessage(auditQuery.error)}
          onRetry={() => {
            void auditQuery.refetch();
          }}
        />
      ) : (
        <div className="space-y-2">
          {(auditQuery.data ?? []).length === 0 ? (
            <p className="text-sm text-[#777587]">{t("audit.noEvents")}</p>
          ) : (
            (auditQuery.data ?? []).map((event) => (
              <AuditEventPreview key={event.id} event={event} />
            ))
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {auditPageUrl && (
          <a
            href={auditPageUrl}
            className="inline-flex rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
          >
            {t("audit.openAuditLogs")}
          </a>
        )}
        {auditExportUrl && isAdmin && (
          <a
            href={auditExportUrl}
            className="inline-flex rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#464555] transition-colors hover:bg-[#f5f3ff]"
          >
            {t("audit.exportLog")}
          </a>
        )}
        {!auditPageUrl && !auditExportUrl && (
          <span className="text-xs text-[#777587]">{t("audit.noLinks")}</span>
        )}
      </div>
      <p className="mt-3 text-xs text-[#777587]">{t("audit.retention")}</p>
    </section>
  );
}
