"use client";

import { SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  getSecurityCapabilities,
  getLoginPolicy,
  updateLoginPolicy,
} from "@/lib/api/security";
import { queryKeys } from "@/lib/api/query";
import {
  fromList,
  toList,
  SectionHeader,
  DeploymentControlledBadge,
  UnavailableRow,
  SaveFeedback,
  ToggleSwitch,
  FieldLabel,
  loginPolicySchema,
  type SaveState,
  type LoginPolicyFormValues,
} from "@/components/settings/security/securityShared";

export function LoginPolicySection({
  capabilities,
  isAdmin,
  changePasswordUrl,
}: {
  capabilities: ReturnType<typeof getSecurityCapabilities>;
  isAdmin: boolean;
  changePasswordUrl: string | null;
}) {
  const t = useTranslations("settings.security");

  const [loginPolicySaveState, setLoginPolicySaveState] =
    useState<SaveState>(null);

  const defaultLoginPolicyValues: LoginPolicyFormValues = {
    domainAllowlist: "",
    sessionTimeoutHours: "24",
    ssoRequired: false,
    inviteOnly: false,
    mfaRequired: false,
  };

  const loginPolicyForm = useForm<LoginPolicyFormValues>({
    resolver: zodResolver(loginPolicySchema),
    defaultValues: defaultLoginPolicyValues,
    mode: "onSubmit",
  });

  const loginPolicyQuery = useQuery({
    queryKey: queryKeys.security.loginPolicy,
    queryFn: getLoginPolicy,
    enabled: capabilities.loginPolicyEnabled && isAdmin,
    retry: false,
  });

  useMemo(() => {
    if (!loginPolicyQuery.data) return;
    loginPolicyForm.reset({
      domainAllowlist: fromList(loginPolicyQuery.data.domain_allowlist),
      sessionTimeoutHours:
        loginPolicyQuery.data.session_timeout_hours?.toString() ?? "24",
      ssoRequired: loginPolicyQuery.data.sso_required,
      inviteOnly: loginPolicyQuery.data.invite_only,
      mfaRequired: loginPolicyQuery.data.mfa_required,
    });
  }, [loginPolicyQuery.data, loginPolicyForm]);

  const loginPolicySaveMutation = useMutation({
    mutationFn: (values: LoginPolicyFormValues) =>
      updateLoginPolicy({
        domain_allowlist: toList(values.domainAllowlist),
        session_timeout_hours: values.sessionTimeoutHours
          ? Number(values.sessionTimeoutHours)
          : null,
        sso_required: values.ssoRequired,
        invite_only: values.inviteOnly,
        mfa_required: values.mfaRequired,
      }),
    onSuccess: () => {
      setLoginPolicySaveState({
        tone: "success",
        message: t("loginPolicy.saved"),
      });
    },
    onError: (error) => {
      setLoginPolicySaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  async function handleSaveLoginPolicy(): Promise<void> {
    setLoginPolicySaveState(null);
    const valid = await loginPolicyForm.trigger();
    if (!valid) return;
    await loginPolicySaveMutation.mutateAsync(loginPolicyForm.getValues());
  }

  const watchedSsoRequired = loginPolicyForm.watch("ssoRequired");
  const watchedInviteOnly = loginPolicyForm.watch("inviteOnly");
  const watchedMfaRequired = loginPolicyForm.watch("mfaRequired");

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Login policy section"
    >
      <SectionHeader
        icon={SlidersHorizontal}
        title={t("loginPolicy.title")}
        badge={
          !capabilities.loginPolicyEnabled && (
            <DeploymentControlledBadge label={t("deploymentControlled")} />
          )
        }
      />

      {/* Change password link */}
      <div className="mb-6">
        {changePasswordUrl ? (
          <a
            href={changePasswordUrl}
            className="inline-flex rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
          >
            {t("loginPolicy.changePassword")}
          </a>
        ) : (
          <UnavailableRow
            label={t("loginPolicy.changePasswordUnavailableLabel")}
            description={t("loginPolicy.changePasswordUnavailableDesc")}
            notAvailableMsg={t("notAvailableMsg")}
            unavailableLabel={t("unavailable")}
          />
        )}
      </div>

      {!capabilities.loginPolicyEnabled ? (
        <p className="text-sm text-[#777587]">{t("loginPolicy.unavailable")}</p>
      ) : !isAdmin ? (
        <ForbiddenState
          compact
          title={t("loginPolicy.restrictedTitle")}
          description={t("loginPolicy.restrictedDesc")}
          backHref="/dashboard"
          backLabel={t("backToDashboard")}
        />
      ) : loginPolicyQuery.isLoading ? (
        <LoadingState compact title={t("loginPolicy.loading")} />
      ) : loginPolicyQuery.isError ? (
        isApiClientError(loginPolicyQuery.error) &&
        loginPolicyQuery.error.status === 429 ? (
          <RateLimitState
            compact
            onRetry={() => {
              void loginPolicyQuery.refetch();
            }}
          />
        ) : (
          <ErrorState
            compact
            error={loginPolicyQuery.error}
            description={getApiErrorMessage(loginPolicyQuery.error)}
            onRetry={() => {
              void loginPolicyQuery.refetch();
            }}
          />
        )
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <FieldLabel htmlFor="sec-domain-allowlist">
                {t("loginPolicy.domainAllowlist")}
              </FieldLabel>
              <input
                id="sec-domain-allowlist"
                {...loginPolicyForm.register("domainAllowlist")}
                placeholder="example.com, partner.org"
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
              <p className="text-xs text-[#777587]">
                {t("loginPolicy.domainAllowlistHint")}
              </p>
            </div>

            <div className="space-y-1">
              <FieldLabel htmlFor="sec-session-timeout">
                {t("loginPolicy.sessionTimeout")}
              </FieldLabel>
              <select
                id="sec-session-timeout"
                {...loginPolicyForm.register("sessionTimeoutHours")}
                className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              >
                <option value="8">{t("loginPolicy.hours8")}</option>
                <option value="24">{t("loginPolicy.hours24")}</option>
                <option value="168">{t("loginPolicy.days7")}</option>
                <option value="720">{t("loginPolicy.days30")}</option>
              </select>
              <p className="text-xs text-[#777587]">
                {t("loginPolicy.sessionTimeoutHint")}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
              <div>
                <label
                  htmlFor="sec-sso-required"
                  className="text-sm font-semibold text-[#1b1b24]"
                >
                  {t("loginPolicy.enforceSSO")}
                </label>
                <p className="text-xs text-[#464555]">
                  {t("loginPolicy.enforceSSODesc")}
                </p>
              </div>
              <ToggleSwitch
                id="sec-sso-required"
                checked={watchedSsoRequired}
                onChange={(v) =>
                  loginPolicyForm.setValue("ssoRequired", v, {
                    shouldDirty: true,
                  })
                }
              />
            </div>

            <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
              <div>
                <label
                  htmlFor="sec-invite-only"
                  className="text-sm font-semibold text-[#1b1b24]"
                >
                  {t("loginPolicy.inviteOnly")}
                </label>
                <p className="text-xs text-[#464555]">
                  {t("loginPolicy.inviteOnlyDesc")}
                </p>
              </div>
              <ToggleSwitch
                id="sec-invite-only"
                checked={watchedInviteOnly}
                onChange={(v) =>
                  loginPolicyForm.setValue("inviteOnly", v, {
                    shouldDirty: true,
                  })
                }
              />
            </div>

            <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
              <div>
                <label
                  htmlFor="sec-mfa-required"
                  className="text-sm font-semibold text-[#1b1b24]"
                >
                  {t("loginPolicy.requireMFA")}
                </label>
                <p className="text-xs text-[#464555]">
                  {t("loginPolicy.requireMFADesc")}
                </p>
              </div>
              <ToggleSwitch
                id="sec-mfa-required"
                checked={watchedMfaRequired}
                onChange={(v) =>
                  loginPolicyForm.setValue("mfaRequired", v, {
                    shouldDirty: true,
                  })
                }
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-3">
            <SaveFeedback state={loginPolicySaveState} />
            <button
              type="button"
              onClick={() => {
                void handleSaveLoginPolicy();
              }}
              disabled={loginPolicySaveMutation.isPending}
              className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loginPolicySaveMutation.isPending
                ? t("saving")
                : t("loginPolicy.savePolicy")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
