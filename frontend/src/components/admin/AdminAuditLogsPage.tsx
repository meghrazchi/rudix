"use client";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { extractRequestIdFromError } from "@/lib/forbidden";
import { useAuditLogsController } from "@/components/admin/audit-logs/useAuditLogsController";
import { AuditSummary } from "@/components/admin/audit-logs/AuditSummary";
import { AuditFilters } from "@/components/admin/audit-logs/AuditFilters";
import { AuditResultsTable } from "@/components/admin/audit-logs/AuditResultsTable";
import { AuditEventDrawer } from "@/components/admin/audit-logs/AuditEventDrawer";

export function AdminAuditLogsPage() {
  const ctl = useAuditLogsController();
  const { t, isAdminUser, forbiddenError, tableOverlayHostRef } = ctl;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("restricted")}
          description={t("restrictedDescription")}
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("unavailable")}
          description={t("unavailableDescription")}
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  return (
    <section className="space-y-5 bg-[#fcf8ff] px-4 py-5 lg:px-8 lg:py-8">
      <AuditSummary ctl={ctl} />
      <AuditFilters ctl={ctl} />

      <div ref={tableOverlayHostRef} className="relative">
        <AuditResultsTable ctl={ctl} />
        <AuditEventDrawer ctl={ctl} />
      </div>

      <p className="text-xs text-[#68647b]">{t("exportNotice")}</p>
    </section>
  );
}
