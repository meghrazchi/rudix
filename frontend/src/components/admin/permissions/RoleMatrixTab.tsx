"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import {
  getRoleMatrix,
  updateRolePermissions,
  type RoleMatrixEntry,
} from "@/lib/api/permissions";
import {
  PermissionDot,
  formatCategory,
  groupByCategory,
} from "@/components/admin/permissions/permissionsShared";

// ── Role matrix tab ────────────────────────────────────────────────────────────

export function RoleMatrixTab({ canManage }: { canManage: boolean }) {
  const t = useTranslations("adminPermissions");
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.adminPermissions.roleMatrix,
    queryFn: getRoleMatrix,
  });

  const [editing, setEditing] = useState<{
    role: RoleMatrixEntry;
    pending: Set<string>;
  } | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [confirmRole, setConfirmRole] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: ({ role, perms }: { role: string; perms: string[] }) =>
      updateRolePermissions(role, perms),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminPermissions.roleMatrix,
      });
      setEditing(null);
      setEditError(null);
      setConfirmRole(null);
    },
    onError: (err) => {
      setEditError(getApiErrorMessage(err));
      setConfirmRole(null);
    },
  });

  if (isLoading) return <LoadingState />;
  if (error) {
    if (isForbiddenError(error)) {
      return (
        <ForbiddenState
          title={t("tabs.roleMatrix")}
          description={t("errors.rolesViewRequired")}
          requestId={extractRequestIdFromError(error)}
          backHref="/admin"
        />
      );
    }
    return <ErrorState description={getApiErrorMessage(error)} />;
  }

  const roles = data?.roles ?? [];
  const allPerms = data?.all_permissions ?? [];
  const grouped = groupByCategory(allPerms);

  function startEdit(role: RoleMatrixEntry) {
    setEditing({ role, pending: new Set(role.permissions) });
    setEditError(null);
  }

  function togglePerm(perm: string) {
    if (!editing) return;
    const next = new Set(editing.pending);
    if (next.has(perm)) next.delete(perm);
    else next.add(perm);
    setEditing({ ...editing, pending: next });
  }

  function handleSaveClick() {
    if (!editing) return;
    if (editing.role.role === "owner") {
      setConfirmRole("owner");
    } else {
      saveMutation.mutate({
        role: editing.role.role,
        perms: Array.from(editing.pending),
      });
    }
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-[#68647b]">
        {t("matrix.descriptionBefore")}{" "}
        <span className="inline-block h-3 w-3 rounded-full bg-amber-400 align-middle" />{" "}
        {t("matrix.descriptionAfter")}
      </p>

      {editing ? (
        <div className="rounded-xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold text-[#2a2640]">
                {t("matrix.editing", { role: editing.role.label })}
              </h3>
              <p className="text-sm text-[#68647b]">
                {editing.role.description}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setEditing(null);
                setEditError(null);
              }}
              className="text-[#68647b] hover:text-[#2a2640]"
            >
              ✕
            </button>
          </div>

          <div className="max-h-[60vh] space-y-4 overflow-y-auto">
            {Object.entries(grouped).map(([cat, perms]) => (
              <div key={cat}>
                <p className="mb-1.5 text-xs font-bold tracking-wide text-[#5d58a8] uppercase">
                  {formatCategory(cat)}
                </p>
                <div className="grid grid-cols-1 gap-1.5 rounded-lg bg-[#f9f8ff] p-3 sm:grid-cols-2">
                  {perms.map((perm) => (
                    <label
                      key={perm}
                      className="flex cursor-pointer items-start gap-2"
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 accent-[#3525cd]"
                        checked={editing.pending.has(perm)}
                        onChange={() => togglePerm(perm)}
                      />
                      <span className="text-sm text-[#2a2640]">
                        <span className="font-medium">
                          {perm.split(":").slice(1).join(":")}
                        </span>
                        <span className="block text-xs text-[#68647b]">
                          {perm}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {editError && (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {editError}
            </p>
          )}

          <div className="mt-4 flex gap-3">
            <button
              type="button"
              onClick={handleSaveClick}
              disabled={saveMutation.isPending}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
            >
              {saveMutation.isPending ? t("saving") : t("saveChanges")}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(null);
                setEditError(null);
              }}
              disabled={saveMutation.isPending}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
            >
              {t("cancel")}
            </button>
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#d7d4e8] bg-white shadow-sm">
          <table className="w-full min-w-max text-sm">
            <thead>
              <tr className="border-b border-[#d7d4e8] bg-[#f9f8ff]">
                <th className="sticky left-0 bg-[#f9f8ff] px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("permission")}
                </th>
                {roles.map((r) => (
                  <th
                    key={r.role}
                    className="px-3 py-3 text-center text-xs font-bold whitespace-nowrap text-[#5d58a8] uppercase"
                  >
                    {r.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(grouped).map(([cat, perms]) => (
                <>
                  <tr key={`cat-${cat}`} className="border-b border-[#f0eeff]">
                    <td
                      colSpan={roles.length + 1}
                      className="sticky left-0 bg-[#f5f3ff] px-4 py-1.5 text-xs font-bold text-[#5d58a8] uppercase"
                    >
                      {formatCategory(cat)}
                    </td>
                  </tr>
                  {perms.map((perm) => (
                    <tr
                      key={perm}
                      className="border-b border-[#f0eeff] hover:bg-[#fdfcff]"
                    >
                      <td className="sticky left-0 bg-white px-4 py-2 font-mono text-xs text-[#2a2640]">
                        {perm}
                      </td>
                      {roles.map((r) => {
                        const has = r.permissions.includes(perm);
                        const overridden =
                          r.overridden_permissions.includes(perm);
                        return (
                          <td key={r.role} className="px-3 py-2 text-center">
                            <PermissionDot has={has} overridden={overridden} />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!editing && canManage && (
        <div>
          <p className="mb-3 text-sm font-medium text-[#2a2640]">
            {t("matrix.editRolePermissions")}
          </p>
          <div className="flex flex-wrap gap-3">
            {roles.map((r) => (
              <button
                key={r.role}
                type="button"
                onClick={() => startEdit(r)}
                className="rounded-lg border border-[#d7d4e8] bg-white px-3 py-1.5 text-sm font-medium text-[#3525cd] transition hover:border-[#3525cd] hover:bg-[#f0eeff]"
              >
                {t("matrix.editRole", { role: r.label })}
              </button>
            ))}
          </div>
        </div>
      )}

      {confirmRole && editing && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="mb-2 text-base font-semibold text-[#2a2640]">
              {t("matrix.confirmOwnerTitle")}
            </h3>
            <p className="mb-4 text-sm text-[#68647b]">
              {t("matrix.confirmOwnerDescription")}
            </p>
            {editError && (
              <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {editError}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() =>
                  saveMutation.mutate({
                    role: editing.role.role,
                    perms: Array.from(editing.pending),
                  })
                }
                disabled={saveMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {saveMutation.isPending ? t("saving") : t("confirmChange")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setConfirmRole(null);
                  setEditError(null);
                }}
                disabled={saveMutation.isPending}
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
