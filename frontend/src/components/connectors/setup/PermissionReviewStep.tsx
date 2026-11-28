"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { WizardStepProps } from "@/components/connectors/wizard/types";
import { type ProviderSummary } from "@/lib/api/connector-providers";
import { ConnectorSetupState } from "@/components/connectors/setup/types";
import {
  ScopeRisk,
  detectScopeRisks,
} from "@/components/connectors/setup/scopeRisk";
import {
  CONFLUENCE_SCOPES,
  GOOGLE_DRIVE_SCOPES,
  MICROSOFT_SHAREPOINT_ONEDRIVE_SCOPES,
} from "@/components/connectors/setup/oauthScopes";

export const SCOPE_RISK_ICONS: Record<ScopeRisk, string> = {
  write_permission: "edit_off",
  admin_scope: "admin_panel_settings",
  org_wide_access: "public",
  broad_read: "visibility",
};

export type PermissionReviewState = { confirmed: boolean };

export function PermissionReviewStep({
  state,
  onChange,
  provider,
  scopeValues,
}: WizardStepProps<ConnectorSetupState> & {
  provider: ProviderSummary;
  scopeValues: Record<string, string | boolean>;
}) {
  const t = useTranslations("connectors.setup");
  const requestedScopes = useMemo(() => {
    if (provider.key === "confluence") {
      return CONFLUENCE_SCOPES.map((s) => s.scope);
    }
    if (provider.key === "google_drive") {
      return GOOGLE_DRIVE_SCOPES.map((s) => s.scope);
    }
    if (provider.key === "microsoft-sharepoint-onedrive") {
      return MICROSOFT_SHAREPOINT_ONEDRIVE_SCOPES.map((s) => s.scope);
    }
    return [];
  }, [provider.key]);

  const warnings = useMemo(
    () => detectScopeRisks(requestedScopes, provider.key, scopeValues),
    [requestedScopes, provider.key, scopeValues],
  );

  const isBroad = warnings.length > 0;

  const confirmed =
    (state as unknown as PermissionReviewState & ConnectorSetupState)
      .confirmed ?? false;

  return (
    <div className="space-y-5">
      {isBroad && (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <span className="material-symbols-outlined mt-0.5 shrink-0 text-[22px] text-amber-600">
            warning
          </span>
          <div>
            <div className="text-sm font-semibold text-amber-900">
              {t("permissions.broadTitle")}
            </div>
            <p className="mt-0.5 text-sm text-amber-800">
              {t("permissions.broadDescription")}
            </p>
          </div>
        </div>
      )}

      <div className="space-y-3 rounded-2xl border border-[#d7d4e8] bg-white p-4">
        <h3 className="text-sm font-semibold text-[#2a2640]">
          {t("permissions.requestedScopes")}
        </h3>
        {requestedScopes.length === 0 ? (
          <p className="text-sm text-[#68647b]">
            {t("permissions.noOAuthScopes")}
          </p>
        ) : (
          <div className="divide-y divide-[#f0eef9] overflow-hidden rounded-xl border border-[#d7d4e8]">
            {requestedScopes.map((scope) => {
              const warning = warnings.find((w) => w.scope === scope);
              return (
                <div
                  key={scope}
                  className={`flex items-start gap-3 px-3 py-2.5 ${warning ? "bg-amber-50/60" : "bg-white"}`}
                >
                  <span
                    className={`material-symbols-outlined mt-0.5 shrink-0 text-[18px] ${
                      warning ? "text-amber-500" : "text-emerald-500"
                    }`}
                  >
                    {warning ? SCOPE_RISK_ICONS[warning.code] : "check_circle"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-xs break-all text-[#2a2640]">
                      {scope}
                    </div>
                    {warning && (
                      <div className="mt-0.5 text-xs text-amber-700">
                        {t(`permissions.risks.${warning.code}`, {
                          scope: warning.scope,
                        })}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#2a2640]">
            <span className="material-symbols-outlined text-[18px] text-[#3525cd]">
              sync_alt
            </span>
            {t("permissions.syncDirection")}
          </div>
          <p className="mt-1.5 text-sm text-[#68647b]">
            {t("permissions.syncDescription")}
          </p>
        </div>
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#2a2640]">
            <span className="material-symbols-outlined text-[18px] text-[#3525cd]">
              database
            </span>
            {t("permissions.retention")}
          </div>
          <p className="mt-1.5 text-sm text-[#68647b]">
            {t("permissions.retentionDescription")}
          </p>
        </div>
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#2a2640]">
            <span className="material-symbols-outlined text-[18px] text-[#3525cd]">
              group
            </span>
            {t("permissions.access")}
          </div>
          <p className="mt-1.5 text-sm text-[#68647b]">
            {t("permissions.accessDescription")}
          </p>
        </div>
      </div>

      <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-[#d7d4e8] bg-white p-4 transition-colors hover:border-[#3525cd]/40">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) =>
            onChange({
              ...(state as object),
              confirmed: e.target.checked,
            } as ConnectorSetupState)
          }
          className="mt-0.5 h-4 w-4 shrink-0 rounded border-[#bfb9d8] text-[#3525cd] focus:ring-[#3525cd]"
          data-testid="permission-review-confirm"
        />
        <div>
          <div className="text-sm font-semibold text-[#2a2640]">
            {t("permissions.confirmTitle")}
          </div>
          <p className="mt-0.5 text-xs text-[#6a6780]">
            {isBroad
              ? t("permissions.confirmBroad")
              : t("permissions.confirmNormal")}
          </p>
        </div>
      </label>
    </div>
  );
}
