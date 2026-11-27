"use client";

import { useMemo } from "react";
import { getSecurityCapabilities } from "@/lib/api/security";
import { useAuthSession } from "@/lib/use-auth-session";
import {
  trimToNull,
  isAdminLike,
} from "@/components/settings/security/securityShared";
import { AuthDiagnosticsSection } from "@/components/settings/security/AuthDiagnosticsSection";
import { ActiveSessionsSection } from "@/components/settings/security/ActiveSessionsSection";
import { LoginPolicySection } from "@/components/settings/security/LoginPolicySection";
import { RoleAccessSection } from "@/components/settings/security/RoleAccessSection";
import { RateLimitsSection } from "@/components/settings/security/RateLimitsSection";
import { AiPostureSection } from "@/components/settings/security/AiPostureSection";
import { AuditLogSection } from "@/components/settings/security/AuditLogSection";

export function SecuritySettingsTab() {
  const { state } = useAuthSession();
  const session = state.session;
  const role = session?.role ?? null;
  const isAdmin = isAdminLike(role);

  const capabilities = useMemo(() => getSecurityCapabilities(), []);

  const changePasswordUrl = trimToNull(
    process.env.NEXT_PUBLIC_SECURITY_CHANGE_PASSWORD_URL,
  );
  const auditPageUrl = trimToNull(process.env.NEXT_PUBLIC_AUDIT_PAGE_URL);
  const auditExportUrl = trimToNull(
    process.env.NEXT_PUBLIC_SECURITY_AUDIT_EXPORT_URL,
  );

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
      <div className="space-y-6 lg:col-span-8">
        <AuthDiagnosticsSection session={session} />
        <ActiveSessionsSection capabilities={capabilities} />
        <LoginPolicySection
          capabilities={capabilities}
          isAdmin={isAdmin}
          changePasswordUrl={changePasswordUrl}
        />
        <RoleAccessSection role={role} />
        <RateLimitsSection />
      </div>

      <div className="space-y-6 lg:col-span-4">
        <AiPostureSection capabilities={capabilities} />
        <AuditLogSection
          capabilities={capabilities}
          isAdmin={isAdmin}
          auditPageUrl={auditPageUrl}
          auditExportUrl={auditExportUrl}
        />
      </div>
    </div>
  );
}
