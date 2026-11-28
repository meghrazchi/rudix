"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import {
  createResourceDeny,
  createResourceGrant,
  listResourceDenies,
  listResourceGrants,
  revokeResourceDeny,
  revokeResourceGrant,
  type ResourceAccessEntry,
} from "@/lib/api/permissions";
import {
  ACTIONS,
  RESOURCE_TYPES,
  StatusBadge,
} from "@/components/admin/permissions/permissionsShared";

// ── Resource access tab (shared for grants + denies) ───────────────────────────

export function ResourceAccessTab({
  kind,
  canManage,
}: {
  kind: "grant" | "deny";
  canManage: boolean;
}) {
  const t = useTranslations("adminPermissions");
  const queryClient = useQueryClient();
  const queryKey =
    kind === "grant"
      ? queryKeys.adminPermissions.grants
      : queryKeys.adminPermissions.denies;
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [showForm, setShowForm] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<ResourceAccessEntry | null>(
    null,
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const [formPrincipalType, setFormPrincipalType] = useState("user");
  const [formPrincipalValue, setFormPrincipalValue] = useState("");
  const [formResourceType, setFormResourceType] = useState("");
  const [formResourceId, setFormResourceId] = useState("");
  const [formAction, setFormAction] = useState("read_only");
  const [formReason, setFormReason] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.adminPermissions.resourceAccess(
      kind,
      resourceTypeFilter,
      statusFilter,
    ),
    queryFn: () =>
      kind === "grant"
        ? listResourceGrants({
            resource_type: resourceTypeFilter || undefined,
            status: statusFilter || undefined,
          })
        : listResourceDenies({
            resource_type: resourceTypeFilter || undefined,
            status: statusFilter || undefined,
          }),
  });

  const createMutation = useMutation({
    mutationFn: (req: Parameters<typeof createResourceGrant>[0]) =>
      kind === "grant" ? createResourceGrant(req) : createResourceDeny(req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      setShowForm(false);
      setFormError(null);
      resetForm();
    },
    onError: (err) => setFormError(getApiErrorMessage(err)),
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) =>
      kind === "grant" ? revokeResourceGrant(id) : revokeResourceDeny(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      setRevokeTarget(null);
      setRevokeError(null);
    },
    onError: (err) => setRevokeError(getApiErrorMessage(err)),
  });

  function resetForm() {
    setFormPrincipalType("user");
    setFormPrincipalValue("");
    setFormResourceType("");
    setFormResourceId("");
    setFormAction("read_only");
    setFormReason("");
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    createMutation.mutate({
      principal_type: formPrincipalType,
      principal_value: formPrincipalValue.trim(),
      resource_type: formResourceType,
      resource_id: formResourceId.trim() || null,
      action: formAction,
      reason: formReason.trim() || null,
    });
  }

  const kindLabel = t(`access.${kind}`);
  const kindActionLabel = t(`access.${kind}Action`);
  const items = data?.items ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={resourceTypeFilter}
          onChange={(e) => setResourceTypeFilter(e.target.value)}
          className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
        >
          <option value="">{t("filters.allResourceTypes")}</option>
          {RESOURCE_TYPES.map((rt) => (
            <option key={rt} value={rt}>
              {rt}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
        >
          <option value="">{t("filters.allStatuses")}</option>
          <option value="active">{t("statuses.active")}</option>
          <option value="revoked">{t("statuses.revoked")}</option>
          <option value="expired">{t("statuses.expired")}</option>
        </select>
        <span className="flex-1" />
        {canManage && !showForm && (
          <button
            type="button"
            onClick={() => {
              setShowForm(true);
              setFormError(null);
            }}
            className="rounded-lg bg-[#3525cd] px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            {t("access.add", { kind: kindActionLabel })}
          </button>
        )}
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
        >
          <h3 className="text-sm font-semibold text-[#2a2640]">
            {t("access.new", { kind: kindLabel })}
          </h3>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                {t("columns.principalType")}{" "}
                <span className="text-red-500">*</span>
              </label>
              <select
                value={formPrincipalType}
                onChange={(e) => setFormPrincipalType(e.target.value)}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              >
                {["user", "team", "group", "role"].map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                {t("columns.principalValue")}{" "}
                <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={formPrincipalValue}
                onChange={(e) => setFormPrincipalValue(e.target.value)}
                required
                placeholder={t("access.principalPlaceholder")}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                {t("columns.resourceType")}{" "}
                <span className="text-red-500">*</span>
              </label>
              <select
                value={formResourceType}
                onChange={(e) => setFormResourceType(e.target.value)}
                required
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              >
                <option value="">{t("select")}</option>
                {RESOURCE_TYPES.map((rt) => (
                  <option key={rt} value={rt}>
                    {rt}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                {t("columns.resourceId")}{" "}
                <span className="text-[#68647b]">{t("access.blankAll")}</span>
              </label>
              <input
                type="text"
                value={formResourceId}
                onChange={(e) => setFormResourceId(e.target.value)}
                placeholder={t("access.resourceIdPlaceholder")}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                {t("columns.action")} <span className="text-red-500">*</span>
              </label>
              <select
                value={formAction}
                onChange={(e) => setFormAction(e.target.value)}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              >
                {ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                {t("columns.reason")}
              </label>
              <input
                type="text"
                value={formReason}
                onChange={(e) => setFormReason(e.target.value)}
                maxLength={1024}
                placeholder={t("access.reasonPlaceholder")}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              />
            </div>
          </div>

          {formError && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {formError}
            </p>
          )}

          <div className="flex gap-3">
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
            >
              {createMutation.isPending
                ? t("saving")
                : t("access.create", { kind: kindLabel })}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowForm(false);
                setFormError(null);
                resetForm();
              }}
              disabled={createMutation.isPending}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
            >
              {t("cancel")}
            </button>
          </div>
        </form>
      )}

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState description={getApiErrorMessage(error)} />
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#d7d4e8] p-8 text-center text-sm text-[#68647b]">
          {t(kind === "grant" ? "access.emptyGrants" : "access.emptyDenies")}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#d7d4e8] bg-white shadow-sm">
          <table className="w-full min-w-max text-sm">
            <thead>
              <tr className="border-b border-[#d7d4e8] bg-[#f9f8ff]">
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.principal")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.resourceType")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.resourceId")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.action")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.status")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.expires")}
                </th>
                {canManage && (
                  <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase" />
                )}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  className="border-b border-[#f0eeff] hover:bg-[#fdfcff]"
                >
                  <td className="px-4 py-3">
                    <span className="rounded bg-[#f5f3ff] px-1.5 py-0.5 text-xs text-[#4d4880]">
                      {item.principal_type}
                    </span>{" "}
                    <span className="font-mono text-xs text-[#2a2640]">
                      {item.principal_value}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-[#2a2640]">
                    {item.resource_type}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[#68647b]">
                    {item.resource_id ?? (
                      <span className="text-[#a09dbf] italic">{t("all")}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-[#2a2640]">
                    {item.action}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="px-4 py-3 text-xs text-[#68647b]">
                    {item.expires_at ? (
                      new Date(item.expires_at).toLocaleDateString()
                    ) : (
                      <span className="text-[#a09dbf] italic">
                        {t("never")}
                      </span>
                    )}
                  </td>
                  {canManage && (
                    <td className="px-4 py-3">
                      {item.status === "active" && (
                        <button
                          type="button"
                          onClick={() => {
                            setRevokeTarget(item);
                            setRevokeError(null);
                          }}
                          className="text-xs font-medium text-red-600 hover:underline"
                        >
                          {t("revoke")}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-[#d7d4e8] px-4 py-2 text-xs text-[#68647b]">
            {t("showing", { count: items.length, total: data?.total ?? 0 })}
          </div>
        </div>
      )}

      {revokeTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="mb-2 text-base font-semibold text-[#2a2640]">
              {t("access.revokeTitle", { kind: kindLabel })}
            </h3>
            <p className="mb-1 text-sm text-[#68647b]">
              {t("columns.principal")}:{" "}
              <strong>{revokeTarget.principal_value}</strong>
            </p>
            <p className="mb-4 text-sm text-[#68647b]">
              {t("columns.resource")}:{" "}
              <strong>{revokeTarget.resource_type}</strong>
              {revokeTarget.resource_id
                ? ` / ${revokeTarget.resource_id}`
                : ` ${t("access.allParenthetical")}`}
            </p>
            {revokeError && (
              <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {revokeError}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => revokeMutation.mutate(revokeTarget.id)}
                disabled={revokeMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {revokeMutation.isPending ? t("revoking") : t("revoke")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setRevokeTarget(null);
                  setRevokeError(null);
                }}
                disabled={revokeMutation.isPending}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
              >
                {t("cancel")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
