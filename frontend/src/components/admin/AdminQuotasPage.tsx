"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  createQuotaOverride,
  deleteQuotaOverride,
  getAdminQuotaUsage,
  getQuotaPolicy,
  listQuotaChangeLog,
  listQuotaOverrides,
  resetQuotaPolicy,
  type CreateQuotaOverrideRequest,
  type QuotaLimitConfig,
  type QuotaType,
  type ResetWindow,
  type UpdateOrgQuotaPolicyRequest,
  updateQuotaPolicy,
  QUOTA_TYPES,
  RESET_WINDOWS,
} from "@/lib/api/quotas";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

type EditDraft = {
  quota_type: QuotaType;
  soft_limit: string;
  hard_limit: string;
  reset_window: ResetWindow;
  change_note: string;
};

type OverrideDraft = {
  quota_type: QuotaType;
  hard_limit_override: string;
  reason: string;
  expires_at: string;
};

function UsageBar({
  value,
  soft,
  hard,
}: {
  value: number;
  soft: number | null;
  hard: number | null;
}) {
  const t = useTranslations("adminQuotas");
  const limit = hard ?? soft;
  if (!limit || limit === 0)
    return <span className="text-xs text-gray-400">{t("values.noLimit")}</span>;
  const pct = Math.min(100, Math.round((value / limit) * 100));
  const color =
    pct >= 100 ? "bg-red-500" : pct >= 80 ? "bg-amber-400" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-500">{pct}%</span>
    </div>
  );
}

export function AdminQuotasPage() {
  const t = useTranslations("adminQuotas");
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const isOwner = role === "owner";

  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [overrideDraft, setOverrideDraft] = useState<OverrideDraft | null>(
    null,
  );
  const [resetConfirm, setResetConfirm] = useState(false);
  const [deleteOverrideId, setDeleteOverrideId] = useState<string | null>(null);

  const usageQuery = useQuery({
    queryKey: queryKeys.quotas.usage,
    queryFn: () => getAdminQuotaUsage(),
    enabled: isAdminUser,
  });

  const policyQuery = useQuery({
    queryKey: queryKeys.quotas.policy,
    queryFn: () => getQuotaPolicy(),
    enabled: isAdminUser,
    retry: (count, err) => {
      if (
        typeof err === "object" &&
        err !== null &&
        "status" in err &&
        (err as { status: number }).status === 404
      )
        return false;
      return count < 2;
    },
  });

  const overridesQuery = useQuery({
    queryKey: queryKeys.quotas.overrides(),
    queryFn: () => listQuotaOverrides({ limit: 50 }),
    enabled: isAdminUser,
  });

  const changeLogQuery = useQuery({
    queryKey: queryKeys.quotas.changeLog(),
    queryFn: () => listQuotaChangeLog({ limit: 10 }),
    enabled: isAdminUser,
  });

  const updateMutation = useMutation({
    mutationFn: (payload: UpdateOrgQuotaPolicyRequest) =>
      updateQuotaPolicy(payload),
    onSuccess: () => {
      setEditDraft(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.quotas.all });
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => resetQuotaPolicy(),
    onSuccess: () => {
      setResetConfirm(false);
      queryClient.invalidateQueries({ queryKey: queryKeys.quotas.all });
    },
  });

  const createOverrideMutation = useMutation({
    mutationFn: (payload: CreateQuotaOverrideRequest) =>
      createQuotaOverride(payload),
    onSuccess: () => {
      setOverrideDraft(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.quotas.all });
    },
  });

  const deleteOverrideMutation = useMutation({
    mutationFn: (id: string) => deleteQuotaOverride(id),
    onSuccess: () => {
      setDeleteOverrideId(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.quotas.all });
    },
  });

  const forbiddenError =
    usageQuery.isError &&
    isForbiddenError(usageQuery.error) &&
    usageQuery.error;

  if (!isAdminUser) {
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

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("access.unavailableTitle")}
          description={t("access.unavailableDescription")}
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  if (usageQuery.isLoading) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <LoadingState
          title={t("states.loadingTitle")}
          description={t("states.loadingDescription")}
          compact={false}
        />
      </section>
    );
  }

  if (usageQuery.isError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ErrorState
          title={t("states.errorTitle")}
          description={getApiErrorMessage(usageQuery.error)}
          compact={false}
          requestId={extractRequestIdFromError(usageQuery.error)}
          onRetry={() => usageQuery.refetch()}
        />
      </section>
    );
  }

  const dashboard = usageQuery.data!;
  const policy = policyQuery.data ?? null;
  const overrides = overridesQuery.data?.items ?? [];
  const changeLog = changeLogQuery.data?.items ?? [];

  function openEditDraft(qt: QuotaType) {
    const existing = policy?.limits[qt];
    setEditDraft({
      quota_type: qt,
      soft_limit:
        existing?.soft_limit != null ? String(existing.soft_limit) : "",
      hard_limit:
        existing?.hard_limit != null ? String(existing.hard_limit) : "",
      reset_window: (existing?.reset_window as ResetWindow) ?? "per_day",
      change_note: "",
    });
  }

  function parseOptionalInt(v: string): number | null {
    const trimmed = v.trim();
    if (!trimmed) return null;
    const n = Number.parseInt(trimmed, 10);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }

  function submitEdit() {
    if (!editDraft) return;
    const config: QuotaLimitConfig = {
      soft_limit: parseOptionalInt(editDraft.soft_limit),
      hard_limit: parseOptionalInt(editDraft.hard_limit),
      reset_window: editDraft.reset_window,
    };
    updateMutation.mutate({
      [editDraft.quota_type]: config,
      change_note: editDraft.change_note || null,
    } as UpdateOrgQuotaPolicyRequest);
  }

  function submitOverride() {
    if (!overrideDraft) return;
    createOverrideMutation.mutate({
      quota_type: overrideDraft.quota_type,
      hard_limit_override: parseOptionalInt(overrideDraft.hard_limit_override),
      reason: overrideDraft.reason,
      expires_at: overrideDraft.expires_at || null,
    });
  }

  return (
    <section className="space-y-8 px-4 py-5 lg:px-8 lg:py-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            {t("header.title")}
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {t("header.description")}
            {dashboard.has_overages && (
              <span className="ms-2 font-medium text-red-600 dark:text-red-400">
                {t("header.overage")}
              </span>
            )}
          </p>
        </div>
        {isAdminUser && policy && (
          <button
            type="button"
            className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-900/20"
            onClick={() => setResetConfirm(true)}
          >
            {t("actions.resetDefaults")}
          </button>
        )}
      </div>

      {/* Usage table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
        <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-800">
            <tr>
              <th className="px-4 py-3 text-start font-medium text-gray-600 dark:text-gray-300">
                {t("fields.quotaType")}
              </th>
              <th className="px-4 py-3 text-start font-medium text-gray-600 dark:text-gray-300">
                {t("fields.currentUsage")}
              </th>
              <th className="px-4 py-3 text-start font-medium text-gray-600 dark:text-gray-300">
                {t("fields.softLimit")}
              </th>
              <th className="px-4 py-3 text-start font-medium text-gray-600 dark:text-gray-300">
                {t("fields.hardLimit")}
              </th>
              <th className="px-4 py-3 text-start font-medium text-gray-600 dark:text-gray-300">
                {t("fields.resetWindow")}
              </th>
              <th className="px-4 py-3 text-start font-medium text-gray-600 dark:text-gray-300">
                {t("fields.status")}
              </th>
              {isAdminUser && (
                <th className="px-4 py-3 text-end font-medium text-gray-600 dark:text-gray-300">
                  {t("fields.actions")}
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-800 dark:bg-gray-900">
            {dashboard.quota_usage.map((item) => (
              <tr key={item.quota_type}>
                <td className="px-4 py-3 font-medium text-gray-800 dark:text-gray-200">
                  {t(`quotaTypes.${item.quota_type}`)}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-col gap-1">
                    <span className="text-gray-700 dark:text-gray-300">
                      {item.current_value.toLocaleString()}
                    </span>
                    <UsageBar
                      value={item.current_value}
                      soft={item.soft_limit}
                      hard={item.hard_limit}
                    />
                  </div>
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {item.soft_limit != null ? (
                    item.soft_limit.toLocaleString()
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {item.hard_limit != null ? (
                    item.hard_limit.toLocaleString()
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {t(`resetWindows.${item.reset_window}`)}
                </td>
                <td className="px-4 py-3">
                  {item.over_hard_limit ? (
                    <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-400">
                      {t("statuses.overLimit")}
                    </span>
                  ) : item.over_soft_limit ? (
                    <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                      {t("statuses.softExceeded")}
                    </span>
                  ) : item.near_limit ? (
                    <span className="inline-flex items-center rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400">
                      {t("statuses.nearLimit")}
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
                      {t("statuses.ok")}
                    </span>
                  )}
                </td>
                {isAdminUser && (
                  <td className="px-4 py-3 text-end">
                    <button
                      type="button"
                      className="text-xs text-indigo-600 hover:underline dark:text-indigo-400"
                      onClick={() =>
                        openEditDraft(item.quota_type as QuotaType)
                      }
                    >
                      {t("actions.edit")}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Edit limit modal */}
      {editDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl dark:bg-gray-900">
            <h2 className="mb-4 text-base font-semibold text-gray-900 dark:text-gray-100">
              {t("edit.title", {
                quotaType: t(`quotaTypes.${editDraft.quota_type}`),
              })}
            </h2>
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t("edit.softLimitWarn")}
                </span>
                <input
                  type="number"
                  min={0}
                  value={editDraft.soft_limit}
                  onChange={(e) =>
                    setEditDraft(
                      (d) => d && { ...d, soft_limit: e.target.value },
                    )
                  }
                  placeholder={t("edit.noSoftLimit")}
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t("edit.hardLimitBlock")}
                </span>
                <input
                  type="number"
                  min={0}
                  value={editDraft.hard_limit}
                  onChange={(e) =>
                    setEditDraft(
                      (d) => d && { ...d, hard_limit: e.target.value },
                    )
                  }
                  placeholder={t("edit.noHardLimit")}
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t("fields.resetWindow")}
                </span>
                <select
                  value={editDraft.reset_window}
                  onChange={(e) =>
                    setEditDraft(
                      (d) =>
                        d && {
                          ...d,
                          reset_window: e.target.value as ResetWindow,
                        },
                    )
                  }
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
                >
                  {RESET_WINDOWS.map((w) => (
                    <option key={w} value={w}>
                      {t(`resetWindows.${w}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t("edit.changeNoteOptional")}
                </span>
                <input
                  type="text"
                  value={editDraft.change_note}
                  onChange={(e) =>
                    setEditDraft(
                      (d) => d && { ...d, change_note: e.target.value },
                    )
                  }
                  placeholder={t("edit.changeReason")}
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
                />
              </label>
            </div>
            {updateMutation.error && (
              <p className="mt-3 text-xs text-red-600 dark:text-red-400">
                {getApiErrorMessage(updateMutation.error)}
              </p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-gray-300 px-4 py-1.5 text-sm dark:border-gray-600"
                onClick={() => setEditDraft(null)}
              >
                {t("actions.cancel")}
              </button>
              <button
                type="button"
                className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                disabled={updateMutation.isPending}
                onClick={submitEdit}
              >
                {updateMutation.isPending
                  ? t("actions.saving")
                  : t("actions.saveLimit")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reset confirm modal */}
      {resetConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl dark:bg-gray-900">
            <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
              {t("reset.title")}
            </h2>
            <p className="mb-4 text-sm text-gray-500">
              {t("reset.description")}
            </p>
            {resetMutation.error && (
              <p className="mb-3 text-xs text-red-600 dark:text-red-400">
                {getApiErrorMessage(resetMutation.error)}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-gray-300 px-4 py-1.5 text-sm dark:border-gray-600"
                onClick={() => setResetConfirm(false)}
              >
                {t("actions.cancel")}
              </button>
              <button
                type="button"
                className="rounded bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                disabled={resetMutation.isPending}
                onClick={() => resetMutation.mutate()}
              >
                {resetMutation.isPending
                  ? t("actions.resetting")
                  : t("actions.resetDefaults")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Overrides section */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            {t("overrides.title")}
          </h2>
          {isOwner && (
            <button
              type="button"
              className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
              onClick={() =>
                setOverrideDraft({
                  quota_type: "uploads",
                  hard_limit_override: "",
                  reason: "",
                  expires_at: "",
                })
              }
            >
              {t("actions.addOverride")}
            </button>
          )}
        </div>
        {overrides.length === 0 ? (
          <p className="text-sm text-gray-500">{t("overrides.empty")}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="min-w-full divide-y divide-gray-100 text-sm dark:divide-gray-800">
              <thead className="bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="px-4 py-2.5 text-start font-medium text-gray-600 dark:text-gray-300">
                    {t("fields.quotaType")}
                  </th>
                  <th className="px-4 py-2.5 text-start font-medium text-gray-600 dark:text-gray-300">
                    {t("fields.target")}
                  </th>
                  <th className="px-4 py-2.5 text-start font-medium text-gray-600 dark:text-gray-300">
                    {t("fields.hardLimitOverride")}
                  </th>
                  <th className="px-4 py-2.5 text-start font-medium text-gray-600 dark:text-gray-300">
                    {t("fields.expires")}
                  </th>
                  <th className="px-4 py-2.5 text-start font-medium text-gray-600 dark:text-gray-300">
                    {t("fields.reason")}
                  </th>
                  {isOwner && (
                    <th className="px-4 py-2.5 text-end font-medium text-gray-600 dark:text-gray-300" />
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-800 dark:bg-gray-900">
                {overrides.map((o) => (
                  <tr key={o.override_id}>
                    <td className="px-4 py-2.5 text-gray-800 dark:text-gray-200">
                      {t(`quotaTypes.${o.quota_type}`)}
                    </td>
                    <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400">
                      {o.target_user_id
                        ? o.target_user_id.slice(0, 8) + "…"
                        : t("values.orgWide")}
                    </td>
                    <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400">
                      {o.hard_limit_override != null
                        ? o.hard_limit_override.toLocaleString()
                        : t("values.unlimited")}
                    </td>
                    <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400">
                      {o.expires_at
                        ? new Date(o.expires_at).toLocaleDateString()
                        : t("values.never")}
                    </td>
                    <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400">
                      {o.reason}
                    </td>
                    {isOwner && (
                      <td className="px-4 py-2.5 text-end">
                        <button
                          type="button"
                          className="text-xs text-red-600 hover:underline dark:text-red-400"
                          onClick={() => setDeleteOverrideId(o.override_id)}
                        >
                          {t("actions.delete")}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* New override modal */}
      {overrideDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl dark:bg-gray-900">
            <h2 className="mb-4 text-base font-semibold text-gray-900 dark:text-gray-100">
              {t("override.title")}
            </h2>
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t("fields.quotaType")}
                </span>
                <select
                  value={overrideDraft.quota_type}
                  onChange={(e) =>
                    setOverrideDraft(
                      (d) =>
                        d && { ...d, quota_type: e.target.value as QuotaType },
                    )
                  }
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
                >
                  {QUOTA_TYPES.map((qt) => (
                    <option key={qt} value={qt}>
                      {t(`quotaTypes.${qt}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t("override.hardLimitHint")}
                </span>
                <input
                  type="number"
                  min={0}
                  value={overrideDraft.hard_limit_override}
                  onChange={(e) =>
                    setOverrideDraft(
                      (d) => d && { ...d, hard_limit_override: e.target.value },
                    )
                  }
                  placeholder={t("values.unlimited")}
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t("fields.reason")}
                </span>
                <input
                  type="text"
                  value={overrideDraft.reason}
                  onChange={(e) =>
                    setOverrideDraft(
                      (d) => d && { ...d, reason: e.target.value },
                    )
                  }
                  placeholder={t("values.required")}
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t("override.expiresOptional")}
                </span>
                <input
                  type="datetime-local"
                  value={overrideDraft.expires_at}
                  onChange={(e) =>
                    setOverrideDraft(
                      (d) => d && { ...d, expires_at: e.target.value },
                    )
                  }
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800"
                />
              </label>
            </div>
            {createOverrideMutation.error && (
              <p className="mt-3 text-xs text-red-600 dark:text-red-400">
                {getApiErrorMessage(createOverrideMutation.error)}
              </p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-gray-300 px-4 py-1.5 text-sm dark:border-gray-600"
                onClick={() => setOverrideDraft(null)}
              >
                {t("actions.cancel")}
              </button>
              <button
                type="button"
                className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                disabled={
                  createOverrideMutation.isPending ||
                  !overrideDraft.reason.trim()
                }
                onClick={submitOverride}
              >
                {createOverrideMutation.isPending
                  ? t("actions.saving")
                  : t("actions.createOverride")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete override confirm */}
      {deleteOverrideId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl dark:bg-gray-900">
            <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
              {t("delete.title")}
            </h2>
            <p className="mb-4 text-sm text-gray-500">
              {t("delete.description")}
            </p>
            {deleteOverrideMutation.error && (
              <p className="mb-3 text-xs text-red-600">
                {getApiErrorMessage(deleteOverrideMutation.error)}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-gray-300 px-4 py-1.5 text-sm dark:border-gray-600"
                onClick={() => setDeleteOverrideId(null)}
              >
                {t("actions.cancel")}
              </button>
              <button
                type="button"
                className="rounded bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                disabled={deleteOverrideMutation.isPending}
                onClick={() => deleteOverrideMutation.mutate(deleteOverrideId)}
              >
                {deleteOverrideMutation.isPending
                  ? t("actions.deleting")
                  : t("actions.delete")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Change log */}
      {changeLog.length > 0 && (
        <div>
          <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
            {t("history.title")}
          </h2>
          <ol className="space-y-2">
            {changeLog.map((entry) => (
              <li
                key={entry.entry_id}
                className="flex items-start gap-3 text-sm"
              >
                <span className="mt-0.5 rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-400">
                  v{entry.version_number}
                </span>
                <div>
                  <span className="text-gray-700 dark:text-gray-300">
                    {entry.change_note ?? t("history.noNote")}
                  </span>
                  <span className="ms-2 text-xs text-gray-400">
                    {new Date(entry.created_at).toLocaleString()}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
