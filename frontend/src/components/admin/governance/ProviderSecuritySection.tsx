"use client";

import type { ProviderSecurityPolicy } from "@/lib/api/admin-governance";
import { useTranslations } from "next-intl";

type Props = {
  policy: ProviderSecurityPolicy;
  cloudFallbackAck: boolean;
  onPolicyChange: (next: ProviderSecurityPolicy) => void;
  onCloudFallbackAckChange: (checked: boolean) => void;
};

function requiresCloudFallbackAck(
  current: ProviderSecurityPolicy,
  next: Partial<ProviderSecurityPolicy>,
): boolean {
  const wasLocalOnly = current.local_only_mode;
  const turningOffLocalOnly = wasLocalOnly && next.local_only_mode === false;
  const enablingCloudFallback =
    !current.cloud_fallback_allowed && next.cloud_fallback_allowed === true;
  return turningOffLocalOnly || enablingCloudFallback;
}

export function ProviderSecuritySection({
  policy,
  cloudFallbackAck,
  onPolicyChange,
  onCloudFallbackAckChange,
}: Props) {
  const t = useTranslations("adminGovernance.providerSecurity");
  function update(patch: Partial<ProviderSecurityPolicy>) {
    const next = { ...policy, ...patch };
    if (!requiresCloudFallbackAck(policy, patch)) {
      onCloudFallbackAckChange(false);
    }
    onPolicyChange(next);
  }

  const needsCloudAck =
    policy.local_only_mode === false || policy.cloud_fallback_allowed === true;

  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">{t("title")}</h2>
      <p className="mt-1 text-xs text-[#68647b]">{t("description")}</p>

      <div className="mt-4 space-y-3">
        {/* Local-only mode */}
        <label className="flex items-start justify-between gap-4 rounded-lg border border-[#e1dff0] p-3">
          <span className="flex-1 text-sm">
            <span className="block font-medium text-[#3d3953]">
              {t("localOnly")}
            </span>
            <span className="block text-xs text-[#68647b]">
              {t("localOnlyDescription")}
            </span>
          </span>
          <input
            type="checkbox"
            className="mt-0.5 shrink-0"
            checked={policy.local_only_mode}
            onChange={(e) => update({ local_only_mode: e.target.checked })}
          />
        </label>

        {/* Cloud fallback allowed */}
        <label className="flex items-start justify-between gap-4 rounded-lg border border-[#e1dff0] p-3">
          <span className="flex-1 text-sm">
            <span className="block font-medium text-[#3d3953]">
              {t("cloudFallback")}
            </span>
            <span className="block text-xs text-[#68647b]">
              {t("cloudFallbackDescription")}
            </span>
          </span>
          <input
            type="checkbox"
            className="mt-0.5 shrink-0"
            checked={policy.cloud_fallback_allowed}
            onChange={(e) =>
              update({ cloud_fallback_allowed: e.target.checked })
            }
          />
        </label>

        {/* Admin-only model selection */}
        <label className="flex items-start justify-between gap-4 rounded-lg border border-[#e1dff0] p-3">
          <span className="flex-1 text-sm">
            <span className="block font-medium text-[#3d3953]">
              {t("adminOnly")}
            </span>
            <span className="block text-xs text-[#68647b]">
              {t("adminOnlyDescription")}
            </span>
          </span>
          <input
            type="checkbox"
            className="mt-0.5 shrink-0"
            checked={policy.admin_only_model_selection}
            onChange={(e) =>
              update({ admin_only_model_selection: e.target.checked })
            }
          />
        </label>

        {/* Allowed provider profiles */}
        <div className="rounded-lg border border-[#e1dff0] p-3">
          <label className="mb-1 block text-sm font-medium text-[#3d3953]">
            {t("allowedProfiles")}
          </label>
          <p className="mb-2 text-xs text-[#68647b]">
            {t("allowedProfilesDescription")}{" "}
            <code className="rounded bg-[#f3f2f9] px-1">local, openai</code>).
          </p>
          <input
            type="text"
            className="w-full rounded-lg border border-[#d7d4e8] bg-white px-3 py-2 text-sm text-[#2a2640] placeholder-[#a09dbb] focus:ring-2 focus:ring-[#5d58a8]/40 focus:outline-none"
            placeholder={t("profilesPlaceholder")}
            value={policy.allowed_provider_profiles.join(", ")}
            onChange={(e) => {
              const profiles = e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean);
              update({ allowed_provider_profiles: profiles });
            }}
          />
        </div>

        {/* Retention warning acknowledgment */}
        {policy.local_only_mode ? (
          <label className="flex items-start gap-2 rounded-lg border border-[#d7d4e8] bg-[#f7f6fc] p-3 text-sm text-[#3d3953]">
            <input
              type="checkbox"
              className="mt-0.5 shrink-0"
              checked={policy.retention_warning_acknowledged}
              onChange={(e) =>
                update({ retention_warning_acknowledged: e.target.checked })
              }
            />
            <span>{t("retentionAcknowledgement")}</span>
          </label>
        ) : null}

        {/* Cloud fallback warning acknowledgment */}
        {needsCloudAck &&
        (policy.local_only_mode === false || policy.cloud_fallback_allowed) ? (
          <label className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <input
              type="checkbox"
              className="mt-0.5 shrink-0"
              checked={cloudFallbackAck}
              onChange={(e) => onCloudFallbackAckChange(e.target.checked)}
            />
            <span>{t("cloudAcknowledgement")}</span>
          </label>
        ) : null}
      </div>
    </article>
  );
}
