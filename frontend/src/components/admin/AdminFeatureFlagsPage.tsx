"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  ALL_FLAG_NAMES,
  clearAdminFeatureFlag,
  listAdminFeatureFlags,
  setAdminFeatureFlag,
  type FeatureFlagDetail,
  type FeatureFlagsResponse,
} from "@/lib/api/feature-flags";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";

function FlagBadge({ enabled }: { enabled: boolean }) {
  const t = useTranslations("adminFeatureFlags");
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${
        enabled
          ? "bg-emerald-100 text-emerald-800"
          : "bg-rose-100 text-rose-800"
      }`}
    >
      {enabled ? t("badges.enabled") : t("badges.disabled")}
    </span>
  );
}

function SourceBadge({ hasOverride }: { hasOverride: boolean }) {
  const t = useTranslations("adminFeatureFlags");
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${
        hasOverride
          ? "bg-amber-100 text-amber-800"
          : "bg-slate-100 text-slate-600"
      }`}
    >
      {hasOverride ? t("badges.orgOverride") : t("badges.envDefault")}
    </span>
  );
}

type OverrideModalState = {
  flag: FeatureFlagDetail;
  pendingEnabled: boolean;
};

function OverrideModal({
  state,
  onConfirm,
  onCancel,
  isSaving,
}: {
  state: OverrideModalState;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const t = useTranslations("adminFeatureFlags");
  const [reason, setReason] = useState(state.flag.override_reason ?? "");
  const label = t(`flags.${state.flag.name}`);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-xl">
        <h2 className="mb-1 text-lg font-bold text-[#2a2640]">
          {state.pendingEnabled
            ? t("modal.enableTitle", { label })
            : t("modal.disableTitle", { label })}
        </h2>
        <p className="mb-4 text-sm text-[#6b6895]">{t("modal.description")}</p>
        <label className="mb-1 block text-xs font-semibold text-[#2a2640]">
          {t("modal.reasonOptional")}
        </label>
        <textarea
          className="mb-4 w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm text-[#2a2640] focus:ring-2 focus:ring-[#5d58a8] focus:outline-none"
          rows={3}
          maxLength={500}
          placeholder={t("modal.reasonPlaceholder")}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="rounded-lg border border-[#d7d4e8] px-4 py-2 text-sm font-semibold text-[#6b6895] hover:bg-[#f4f3fb]"
            onClick={onCancel}
            disabled={isSaving}
          >
            {t("actions.cancel")}
          </button>
          <button
            type="button"
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white ${
              state.pendingEnabled
                ? "bg-emerald-600 hover:bg-emerald-700"
                : "bg-rose-600 hover:bg-rose-700"
            } disabled:opacity-50`}
            onClick={() => onConfirm(reason.trim())}
            disabled={isSaving}
          >
            {isSaving ? t("actions.saving") : t("actions.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

export function AdminFeatureFlagsPage() {
  const t = useTranslations("adminFeatureFlags");
  const { state } = useAuthSession();
  const role = state.session?.role;
  const queryClient = useQueryClient();

  const [modal, setModal] = useState<OverrideModalState | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery<FeatureFlagsResponse>({
    queryKey: queryKeys.admin.featureFlags,
    queryFn: listAdminFeatureFlags,
  });

  const setMutation = useMutation({
    mutationFn: ({
      flagName,
      enabled,
      reason,
    }: {
      flagName: string;
      enabled: boolean;
      reason: string | null;
    }) => setAdminFeatureFlag(flagName, { enabled, reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.featureFlags });
      queryClient.invalidateQueries({ queryKey: queryKeys.featureFlags });
      setModal(null);
      setErrorMsg(null);
    },
    onError: (err) => {
      setErrorMsg(getApiErrorMessage(err));
    },
  });

  const clearMutation = useMutation({
    mutationFn: (flagName: string) => clearAdminFeatureFlag(flagName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.featureFlags });
      queryClient.invalidateQueries({ queryKey: queryKeys.featureFlags });
      setErrorMsg(null);
    },
    onError: (err) => {
      setErrorMsg(getApiErrorMessage(err));
    },
  });

  if (!canViewAdminUsage(role)) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("access.restrictedTitle")}
          description={t("access.restrictedDescription")}
          compact={false}
        />
      </section>
    );
  }

  if (isLoading) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <LoadingState title={t("states.loading")} />
      </section>
    );
  }

  if (error) {
    if (isForbiddenError(error)) {
      return (
        <section className="px-4 py-5 lg:px-8 lg:py-8">
          <ForbiddenState
            title={t("access.deniedTitle")}
            description={t("access.deniedDescription")}
            compact={false}
          />
        </section>
      );
    }
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ErrorState error={error} />
      </section>
    );
  }

  const flagMap = new Map(data?.flags.map((f) => [f.name, f]) ?? []);

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      {modal && (
        <OverrideModal
          state={modal}
          isSaving={setMutation.isPending}
          onConfirm={(reason) =>
            setMutation.mutate({
              flagName: modal.flag.name,
              enabled: modal.pendingEnabled,
              reason: reason || null,
            })
          }
          onCancel={() => setModal(null)}
        />
      )}

      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {t("header.eyebrow")}
        </p>
        <h1 className="mb-1 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          {t("header.title")}
        </h1>
        <p className="text-sm text-[#6b6895]">{t("header.description")}</p>
      </header>

      {errorMsg && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {errorMsg}
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="border-b border-[#d7d4e8] bg-[#f4f3fb]">
            <tr>
              <th className="px-4 py-3 text-start text-xs font-semibold text-[#6b6895]">
                {t("table.flag")}
              </th>
              <th className="px-4 py-3 text-start text-xs font-semibold text-[#6b6895]">
                {t("table.status")}
              </th>
              <th className="px-4 py-3 text-start text-xs font-semibold text-[#6b6895]">
                {t("table.source")}
              </th>
              <th className="px-4 py-3 text-start text-xs font-semibold text-[#6b6895]">
                {t("table.envDefault")}
              </th>
              <th className="px-4 py-3 text-start text-xs font-semibold text-[#6b6895]">
                {t("table.reason")}
              </th>
              <th className="px-4 py-3 text-end text-xs font-semibold text-[#6b6895]">
                {t("table.actions")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#ece9f8]">
            {ALL_FLAG_NAMES.map((name) => {
              const flag = flagMap.get(name);
              if (!flag) return null;
              const label = t(`flags.${name}`);
              const isMutating =
                (setMutation.isPending &&
                  setMutation.variables?.flagName === name) ||
                (clearMutation.isPending && clearMutation.variables === name);

              return (
                <tr key={name} className="hover:bg-[#f9f8fe]">
                  <td className="px-4 py-3 font-medium text-[#2a2640]">
                    <span>{label}</span>
                    <span className="ms-2 font-mono text-[11px] text-[#9893c4]">
                      {name}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <FlagBadge enabled={flag.enabled} />
                  </td>
                  <td className="px-4 py-3">
                    <SourceBadge hasOverride={flag.has_org_override} />
                  </td>
                  <td className="px-4 py-3">
                    <FlagBadge enabled={flag.env_default} />
                  </td>
                  <td className="px-4 py-3 text-[#6b6895]">
                    {flag.override_reason ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      {flag.enabled ? (
                        <button
                          type="button"
                          className="rounded-lg border border-rose-200 px-3 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-40"
                          disabled={isMutating}
                          onClick={() =>
                            setModal({ flag, pendingEnabled: false })
                          }
                        >
                          {t("actions.disable")}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="rounded-lg border border-emerald-200 px-3 py-1 text-xs font-semibold text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
                          disabled={isMutating}
                          onClick={() =>
                            setModal({ flag, pendingEnabled: true })
                          }
                        >
                          {t("actions.enable")}
                        </button>
                      )}
                      {flag.has_org_override && (
                        <button
                          type="button"
                          className="rounded-lg border border-[#d7d4e8] px-3 py-1 text-xs font-semibold text-[#6b6895] hover:bg-[#f4f3fb] disabled:opacity-40"
                          disabled={isMutating}
                          onClick={() => clearMutation.mutate(name)}
                        >
                          {t("actions.resetDefault")}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
