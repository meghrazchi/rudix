"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { usePermissions } from "@/lib/use-permissions";
import {
  createResourceDeny,
  createResourceGrant,
  getRoleMatrix,
  listResourceDenies,
  listResourceGrants,
  revokeResourceDeny,
  revokeResourceGrant,
  updateRolePermissions,
  type ResourceAccessEntry,
  type RoleMatrixEntry,
} from "@/lib/api/permissions";

type Tab = "role-matrix" | "resource-grants" | "resource-denies";

const QUERY_ROLE_MATRIX = ["admin", "permissions", "role-matrix"] as const;
const QUERY_GRANTS = ["admin", "permissions", "grants"] as const;
const QUERY_DENIES = ["admin", "permissions", "denies"] as const;

const RESOURCE_TYPES = [
  "document",
  "collection",
  "connector",
  "connector_source_item",
  "citation",
  "graph_entity",
  "graph_evidence",
  "evaluation",
  "saved_answer",
  "knowledge_card",
  "api_key",
];

const ACTIONS = ["read_only", "manage", "sync", "export", "evaluate", "cite", "search"];

function categoryFromPermission(perm: string): string {
  return perm.split(":")[0] ?? perm;
}

function formatCategory(cat: string): string {
  return cat
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function groupByCategory(permissions: string[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const p of permissions) {
    const cat = categoryFromPermission(p);
    if (!out[cat]) out[cat] = [];
    out[cat].push(p);
  }
  return out;
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "active"
      ? "bg-emerald-50 text-emerald-700 border border-emerald-100"
      : status === "revoked"
        ? "bg-red-50 text-red-700 border border-red-100"
        : "bg-amber-50 text-amber-700 border border-amber-100";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${cls}`}>
      {status}
    </span>
  );
}

function PermissionDot({ has, overridden }: { has: boolean; overridden: boolean }) {
  if (!has) {
    return (
      <span
        className="inline-block h-4 w-4 rounded-full border border-[#d7d4e8] bg-white"
        title="Not granted"
        aria-label="not granted"
      />
    );
  }
  if (overridden) {
    return (
      <span
        className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-amber-400"
        title="Granted (overridden from default)"
        aria-label="granted, overridden"
      >
        <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 10 10" fill="currentColor">
          <path d="M5 1l1.2 2.4L9 3.9 6.8 6l.5 3L5 7.7 2.7 9l.5-3L1 3.9l2.8-.5z" />
        </svg>
      </span>
    );
  }
  return (
    <span
      className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-[#3525cd]"
      title="Granted"
      aria-label="granted"
    >
      <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M2 5l2.5 2.5L8 3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

// ── Role matrix tab ────────────────────────────────────────────────────────────

function RoleMatrixTab({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: QUERY_ROLE_MATRIX,
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
      queryClient.invalidateQueries({ queryKey: QUERY_ROLE_MATRIX });
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
          title="Role Matrix"
          description="You need roles:view permission."
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
      saveMutation.mutate({ role: editing.role.role, perms: Array.from(editing.pending) });
    }
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-[#68647b]">
        The role matrix shows which permissions each built-in role holds. Cells marked with{" "}
        <span className="inline-block h-3 w-3 rounded-full bg-amber-400 align-middle" /> differ
        from the canonical defaults shipped with Rudix.
      </p>

      {editing ? (
        <div className="rounded-xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold text-[#2a2640]">
                Editing: {editing.role.label}
              </h3>
              <p className="text-sm text-[#68647b]">{editing.role.description}</p>
            </div>
            <button
              type="button"
              onClick={() => { setEditing(null); setEditError(null); }}
              className="text-[#68647b] hover:text-[#2a2640]"
            >
              ✕
            </button>
          </div>

          <div className="max-h-[60vh] space-y-4 overflow-y-auto">
            {Object.entries(grouped).map(([cat, perms]) => (
              <div key={cat}>
                <p className="mb-1.5 text-xs font-bold uppercase tracking-wide text-[#5d58a8]">
                  {formatCategory(cat)}
                </p>
                <div className="grid grid-cols-1 gap-1.5 rounded-lg bg-[#f9f8ff] p-3 sm:grid-cols-2">
                  {perms.map((perm) => (
                    <label key={perm} className="flex cursor-pointer items-start gap-2">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 accent-[#3525cd]"
                        checked={editing.pending.has(perm)}
                        onChange={() => togglePerm(perm)}
                      />
                      <span className="text-sm text-[#2a2640]">
                        <span className="font-medium">{perm.split(":").slice(1).join(":")}</span>
                        <span className="block text-xs text-[#68647b]">{perm}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {editError && (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{editError}</p>
          )}

          <div className="mt-4 flex gap-3">
            <button
              type="button"
              onClick={handleSaveClick}
              disabled={saveMutation.isPending}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving…" : "Save changes"}
            </button>
            <button
              type="button"
              onClick={() => { setEditing(null); setEditError(null); }}
              disabled={saveMutation.isPending}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#d7d4e8] bg-white shadow-sm">
          <table className="w-full min-w-max text-sm">
            <thead>
              <tr className="border-b border-[#d7d4e8] bg-[#f9f8ff]">
                <th className="sticky left-0 bg-[#f9f8ff] px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  Permission
                </th>
                {roles.map((r) => (
                  <th
                    key={r.role}
                    className="px-3 py-3 text-center text-xs font-bold text-[#5d58a8] uppercase whitespace-nowrap"
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
                      className="sticky left-0 bg-[#f5f3ff] px-4 py-1.5 text-xs font-bold uppercase text-[#5d58a8]"
                    >
                      {formatCategory(cat)}
                    </td>
                  </tr>
                  {perms.map((perm) => (
                    <tr key={perm} className="border-b border-[#f0eeff] hover:bg-[#fdfcff]">
                      <td className="sticky left-0 bg-white px-4 py-2 font-mono text-xs text-[#2a2640]">
                        {perm}
                      </td>
                      {roles.map((r) => {
                        const has = r.permissions.includes(perm);
                        const overridden = r.overridden_permissions.includes(perm);
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
          <p className="mb-3 text-sm font-medium text-[#2a2640]">Edit role permissions</p>
          <div className="flex flex-wrap gap-3">
            {roles.map((r) => (
              <button
                key={r.role}
                type="button"
                onClick={() => startEdit(r)}
                className="rounded-lg border border-[#d7d4e8] bg-white px-3 py-1.5 text-sm font-medium text-[#3525cd] hover:border-[#3525cd] hover:bg-[#f0eeff] transition"
              >
                Edit {r.label}
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
              Confirm owner role change
            </h3>
            <p className="mb-4 text-sm text-[#68647b]">
              You are modifying the <strong>Owner</strong> role. This affects all organization
              owners. Are you sure?
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
                {saveMutation.isPending ? "Saving…" : "Confirm change"}
              </button>
              <button
                type="button"
                onClick={() => { setConfirmRole(null); setEditError(null); }}
                disabled={saveMutation.isPending}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Resource access tab (shared for grants + denies) ───────────────────────────

function ResourceAccessTab({
  kind,
  canManage,
}: {
  kind: "grant" | "deny";
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const queryKey = kind === "grant" ? QUERY_GRANTS : QUERY_DENIES;
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [showForm, setShowForm] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<ResourceAccessEntry | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const [formPrincipalType, setFormPrincipalType] = useState("user");
  const [formPrincipalValue, setFormPrincipalValue] = useState("");
  const [formResourceType, setFormResourceType] = useState("");
  const [formResourceId, setFormResourceId] = useState("");
  const [formAction, setFormAction] = useState("read_only");
  const [formReason, setFormReason] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: [...queryKey, resourceTypeFilter, statusFilter],
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

  const kindLabel = kind === "grant" ? "Grant" : "Deny";
  const items = data?.items ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={resourceTypeFilter}
          onChange={(e) => setResourceTypeFilter(e.target.value)}
          className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
        >
          <option value="">All resource types</option>
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
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="revoked">Revoked</option>
          <option value="expired">Expired</option>
        </select>
        <span className="flex-1" />
        {canManage && !showForm && (
          <button
            type="button"
            onClick={() => { setShowForm(true); setFormError(null); }}
            className="rounded-lg bg-[#3525cd] px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            + Add {kindLabel}
          </button>
        )}
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm space-y-4"
        >
          <h3 className="text-sm font-semibold text-[#2a2640]">New resource {kindLabel.toLowerCase()}</h3>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                Principal type <span className="text-red-500">*</span>
              </label>
              <select
                value={formPrincipalType}
                onChange={(e) => setFormPrincipalType(e.target.value)}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              >
                {["user", "team", "group", "role"].map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                Principal value <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={formPrincipalValue}
                onChange={(e) => setFormPrincipalValue(e.target.value)}
                required
                placeholder="e.g. user-uuid or team-name"
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                Resource type <span className="text-red-500">*</span>
              </label>
              <select
                value={formResourceType}
                onChange={(e) => setFormResourceType(e.target.value)}
                required
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              >
                <option value="">Select…</option>
                {RESOURCE_TYPES.map((rt) => (
                  <option key={rt} value={rt}>{rt}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                Resource ID <span className="text-[#68647b]">(blank = all)</span>
              </label>
              <input
                type="text"
                value={formResourceId}
                onChange={(e) => setFormResourceId(e.target.value)}
                placeholder="Leave blank to apply to all"
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">
                Action <span className="text-red-500">*</span>
              </label>
              <select
                value={formAction}
                onChange={(e) => setFormAction(e.target.value)}
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              >
                {ACTIONS.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[#2a2640]">Reason</label>
              <input
                type="text"
                value={formReason}
                onChange={(e) => setFormReason(e.target.value)}
                maxLength={1024}
                placeholder="Optional audit note"
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              />
            </div>
          </div>

          {formError && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{formError}</p>
          )}

          <div className="flex gap-3">
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
            >
              {createMutation.isPending ? "Saving…" : `Create ${kindLabel.toLowerCase()}`}
            </button>
            <button
              type="button"
              onClick={() => { setShowForm(false); setFormError(null); resetForm(); }}
              disabled={createMutation.isPending}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
            >
              Cancel
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
          No {kindLabel.toLowerCase()}s match the selected filters.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#d7d4e8] bg-white shadow-sm">
          <table className="w-full min-w-max text-sm">
            <thead>
              <tr className="border-b border-[#d7d4e8] bg-[#f9f8ff]">
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Principal</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Resource type</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Resource ID</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Action</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Status</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Expires</th>
                {canManage && (
                  <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]" />
                )}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-[#f0eeff] hover:bg-[#fdfcff]">
                  <td className="px-4 py-3">
                    <span className="rounded bg-[#f5f3ff] px-1.5 py-0.5 text-xs text-[#4d4880]">
                      {item.principal_type}
                    </span>{" "}
                    <span className="text-[#2a2640] font-mono text-xs">{item.principal_value}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-[#2a2640]">{item.resource_type}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[#68647b]">
                    {item.resource_id ?? <span className="italic text-[#a09dbf]">all</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-[#2a2640]">{item.action}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="px-4 py-3 text-xs text-[#68647b]">
                    {item.expires_at
                      ? new Date(item.expires_at).toLocaleDateString()
                      : <span className="italic text-[#a09dbf]">never</span>}
                  </td>
                  {canManage && (
                    <td className="px-4 py-3">
                      {item.status === "active" && (
                        <button
                          type="button"
                          onClick={() => { setRevokeTarget(item); setRevokeError(null); }}
                          className="text-xs font-medium text-red-600 hover:underline"
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-[#d7d4e8] px-4 py-2 text-xs text-[#68647b]">
            Showing {items.length} of {data?.total ?? 0}
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
              Revoke {kindLabel.toLowerCase()}?
            </h3>
            <p className="mb-1 text-sm text-[#68647b]">
              Principal: <strong>{revokeTarget.principal_value}</strong>
            </p>
            <p className="mb-4 text-sm text-[#68647b]">
              Resource: <strong>{revokeTarget.resource_type}</strong>
              {revokeTarget.resource_id ? ` / ${revokeTarget.resource_id}` : " (all)"}
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
                {revokeMutation.isPending ? "Revoking…" : "Revoke"}
              </button>
              <button
                type="button"
                onClick={() => { setRevokeTarget(null); setRevokeError(null); }}
                disabled={revokeMutation.isPending}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function AdminPermissionsPage() {
  const { hasPermission } = usePermissions();
  const canView = hasPermission("roles:view");
  const canManage = hasPermission("roles:manage");

  const [activeTab, setActiveTab] = useState<Tab>("role-matrix");

  if (!canView) {
    return (
      <ForbiddenState
        title="Access Management"
        description="You need the roles:view permission to access this page."
        backHref="/dashboard"
      />
    );
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "role-matrix", label: "Role Matrix" },
    { id: "resource-grants", label: "Resource Grants" },
    { id: "resource-denies", label: "Resource Denies" },
  ];

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 py-8">
      <div>
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">Admin</p>
        <h1 className="text-2xl font-extrabold text-[#2a2640]">Access Management</h1>
        <p className="mt-1 text-sm text-[#68647b]">
          Manage the role permission matrix and explicit resource-level grants and denies for
          your organization.
        </p>
      </div>

      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <strong>Security note:</strong> Backend authorization is the source of truth. Frontend
        permission checks are for UX only and never replace backend enforcement. Unsafe changes
        (removing the last owner, locking out all admins) are blocked automatically.
      </div>

      <div className="border-b border-[#d7d4e8]">
        <nav className="-mb-px flex gap-6" aria-label="Permissions tabs">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`pb-3 text-sm font-semibold transition border-b-2 ${
                activeTab === tab.id
                  ? "border-[#3525cd] text-[#3525cd]"
                  : "border-transparent text-[#68647b] hover:text-[#2a2640]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <div>
        {activeTab === "role-matrix" && <RoleMatrixTab canManage={canManage} />}
        {activeTab === "resource-grants" && (
          <ResourceAccessTab kind="grant" canManage={canManage} />
        )}
        {activeTab === "resource-denies" && (
          <ResourceAccessTab kind="deny" canManage={canManage} />
        )}
      </div>
    </div>
  );
}
