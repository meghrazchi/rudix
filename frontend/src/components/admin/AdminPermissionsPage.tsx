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
import {
  explainDecision,
  getConflict,
  listConflicts,
  scanForConflicts,
  updateConflictStatus,
  type ConflictEntry,
  type ConflictSeverity,
  type ConflictStatus,
  type ExplainDecisionResponse,
  type TraceStep,
} from "@/lib/api/conflicts";

type Tab = "role-matrix" | "resource-grants" | "resource-denies" | "conflicts" | "access-debugger";

const QUERY_ROLE_MATRIX = ["admin", "permissions", "role-matrix"] as const;
const QUERY_GRANTS = ["admin", "permissions", "grants"] as const;
const QUERY_DENIES = ["admin", "permissions", "denies"] as const;
const QUERY_CONFLICTS = ["admin", "permissions", "conflicts"] as const;

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

// ── Severity badge ─────────────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<ConflictSeverity, string> = {
  info: "bg-sky-50 text-sky-700 border border-sky-100",
  warning: "bg-amber-50 text-amber-700 border border-amber-100",
  blocking: "bg-orange-50 text-orange-700 border border-orange-100",
  security_risk: "bg-red-50 text-red-700 border border-red-100",
};

function SeverityBadge({ severity }: { severity: ConflictSeverity }) {
  const cls = SEVERITY_STYLES[severity] ?? "bg-slate-50 text-slate-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${cls}`}>
      {severity.replace("_", " ")}
    </span>
  );
}

function ConflictStatusBadge({ status }: { status: ConflictStatus }) {
  const cls =
    status === "open"
      ? "bg-red-50 text-red-700 border border-red-100"
      : status === "investigating"
        ? "bg-amber-50 text-amber-700 border border-amber-100"
        : status === "resolved"
          ? "bg-emerald-50 text-emerald-700 border border-emerald-100"
          : "bg-slate-50 text-slate-600 border border-slate-100";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${cls}`}>
      {status}
    </span>
  );
}

// ── Conflict detail drawer ─────────────────────────────────────────────────────

function ConflictDrawer({
  conflictId,
  onClose,
  canManage,
}: {
  conflictId: string;
  onClose: () => void;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const { data: conflict, isLoading, error } = useQuery({
    queryKey: [...QUERY_CONFLICTS, conflictId],
    queryFn: () => getConflict(conflictId),
  });

  const [statusError, setStatusError] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const statusMutation = useMutation({
    mutationFn: (s: "investigating" | "resolved" | "dismissed") =>
      updateConflictStatus(conflictId, { status: s, resolution_note: note || null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_CONFLICTS });
      onClose();
    },
    onError: (err) => setStatusError(getApiErrorMessage(err)),
  });

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/30"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="relative flex h-full w-full max-w-xl flex-col bg-white shadow-2xl overflow-y-auto">
        <div className="flex items-center justify-between border-b border-[#d7d4e8] px-6 py-4">
          <h2 className="text-base font-semibold text-[#2a2640]">Conflict Detail</h2>
          <button type="button" onClick={onClose} className="text-[#68647b] hover:text-[#2a2640]">
            ✕
          </button>
        </div>

        {isLoading ? (
          <div className="flex-1 p-6"><LoadingState /></div>
        ) : error ? (
          <div className="p-6"><ErrorState description={getApiErrorMessage(error)} /></div>
        ) : conflict ? (
          <div className="flex-1 space-y-6 p-6">
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <p className="text-xs font-bold uppercase text-[#5d58a8]">{conflict.conflict_type.replace(/_/g, " ")}</p>
                <p className="mt-1 text-sm text-[#2a2640]">{conflict.conflict_summary ?? "No summary available"}</p>
              </div>
              <div className="flex flex-col items-end gap-1">
                <SeverityBadge severity={conflict.severity} />
                <ConflictStatusBadge status={conflict.status} />
              </div>
            </div>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-[#d7d4e8] bg-[#f9f8ff] p-4 text-xs">
              <div>
                <dt className="font-bold text-[#5d58a8] uppercase">Subject</dt>
                <dd className="mt-0.5 font-mono text-[#2a2640] break-all">{conflict.subject_value}</dd>
              </div>
              <div>
                <dt className="font-bold text-[#5d58a8] uppercase">Resource</dt>
                <dd className="mt-0.5 font-mono text-[#2a2640] break-all">
                  {conflict.resource_type}{conflict.resource_id ? `/${conflict.resource_id}` : " (all)"}
                </dd>
              </div>
              <div>
                <dt className="font-bold text-[#5d58a8] uppercase">Action</dt>
                <dd className="mt-0.5 text-[#2a2640]">{conflict.action}</dd>
              </div>
              <div>
                <dt className="font-bold text-[#5d58a8] uppercase">Detected</dt>
                <dd className="mt-0.5 text-[#68647b]">{new Date(conflict.detected_at).toLocaleString()}</dd>
              </div>
              {conflict.grant_id && (
                <div>
                  <dt className="font-bold text-[#5d58a8] uppercase">Grant ID</dt>
                  <dd className="mt-0.5 font-mono text-[#68647b] break-all">{conflict.grant_id}</dd>
                </div>
              )}
              {conflict.deny_id && (
                <div>
                  <dt className="font-bold text-[#5d58a8] uppercase">Deny ID</dt>
                  <dd className="mt-0.5 font-mono text-[#68647b] break-all">{conflict.deny_id}</dd>
                </div>
              )}
            </dl>

            {conflict.remediation.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-bold uppercase text-[#5d58a8]">Suggested remediation</p>
                <ul className="space-y-1.5">
                  {conflict.remediation.map((r, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-[#2a2640]">
                      <span className="mt-0.5 shrink-0 text-[#3525cd]">→</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {canManage && conflict.status !== "resolved" && conflict.status !== "dismissed" && (
              <div className="rounded-xl border border-[#d7d4e8] bg-white p-4 space-y-3">
                <p className="text-xs font-bold uppercase text-[#5d58a8]">Update status</p>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Resolution note (optional)"
                  rows={2}
                  maxLength={1024}
                  className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
                />
                {statusError && (
                  <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{statusError}</p>
                )}
                <div className="flex flex-wrap gap-2">
                  {conflict.status !== "investigating" && (
                    <button
                      type="button"
                      onClick={() => statusMutation.mutate("investigating")}
                      disabled={statusMutation.isPending}
                      className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                    >
                      Mark investigating
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => statusMutation.mutate("resolved")}
                    disabled={statusMutation.isPending}
                    className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
                  >
                    Mark resolved
                  </button>
                  <button
                    type="button"
                    onClick={() => statusMutation.mutate("dismissed")}
                    disabled={statusMutation.isPending}
                    className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ── Conflicts tab ──────────────────────────────────────────────────────────────

function ConflictsTab({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const [severityFilter, setSeverityFilter] = useState<ConflictSeverity | "">("");
  const [statusFilter, setStatusFilter] = useState<ConflictStatus | "">("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: [...QUERY_CONFLICTS, severityFilter, statusFilter, resourceTypeFilter],
    queryFn: () =>
      listConflicts({
        severity: severityFilter || undefined,
        status: statusFilter || undefined,
        resource_type: resourceTypeFilter || undefined,
      }),
  });

  const scanMutation = useMutation({
    mutationFn: scanForConflicts,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_CONFLICTS }),
  });

  const items = data?.items ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value as ConflictSeverity | "")}
          className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
        >
          <option value="">All severities</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="blocking">Blocking</option>
          <option value="security_risk">Security risk</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as ConflictStatus | "")}
          className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
        >
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="investigating">Investigating</option>
          <option value="resolved">Resolved</option>
          <option value="dismissed">Dismissed</option>
        </select>
        <select
          value={resourceTypeFilter}
          onChange={(e) => setResourceTypeFilter(e.target.value)}
          className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
        >
          <option value="">All resource types</option>
          {[
            "document", "collection", "connector", "connector_source_item",
            "citation", "graph_entity", "graph_evidence", "evaluation",
            "saved_answer", "knowledge_card", "api_key",
          ].map((rt) => (
            <option key={rt} value={rt}>{rt}</option>
          ))}
        </select>
        <span className="flex-1" />
        {canManage && (
          <button
            type="button"
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="rounded-lg border border-[#d7d4e8] bg-white px-3 py-1.5 text-sm font-semibold text-[#3525cd] hover:border-[#3525cd] hover:bg-[#f0eeff] disabled:opacity-50 transition"
          >
            {scanMutation.isPending ? "Scanning…" : "Run scan"}
          </button>
        )}
      </div>

      {scanMutation.isSuccess && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
          Scan complete — {scanMutation.data.conflicts_detected} conflicts detected,{" "}
          {scanMutation.data.conflicts_created} new.{" "}
          <span className="text-xs text-emerald-600">
            ({scanMutation.data.scan_duration_ms}ms)
          </span>
        </div>
      )}

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        isForbiddenError(error) ? (
          <ForbiddenState
            title="Permission Conflicts"
            description="You need security_center:view permission."
            requestId={extractRequestIdFromError(error)}
            backHref="/admin"
          />
        ) : (
          <ErrorState description={getApiErrorMessage(error)} />
        )
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#d7d4e8] p-8 text-center text-sm text-[#68647b]">
          No conflicts match the current filters.{" "}
          {canManage && (
            <button
              type="button"
              onClick={() => scanMutation.mutate()}
              className="text-[#3525cd] underline"
            >
              Run a scan
            </button>
          )}{" "}
          to detect new conflicts.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#d7d4e8] bg-white shadow-sm">
          <table className="w-full min-w-max text-sm">
            <thead>
              <tr className="border-b border-[#d7d4e8] bg-[#f9f8ff]">
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Type</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Subject</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Resource</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Severity</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Status</th>
                <th className="px-4 py-3 text-left text-xs font-bold uppercase text-[#5d58a8]">Detected</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr
                  key={c.id}
                  className="border-b border-[#f0eeff] hover:bg-[#fdfcff] cursor-pointer"
                  onClick={() => setSelectedId(c.id)}
                >
                  <td className="px-4 py-3 text-xs font-mono text-[#2a2640]">
                    {c.conflict_type.replace(/_/g, " ")}
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-[#68647b] max-w-[160px] truncate">
                    {c.subject_value}
                  </td>
                  <td className="px-4 py-3 text-xs text-[#2a2640]">
                    {c.resource_type}
                    {c.resource_id && (
                      <span className="ml-1 text-[#68647b]">/{c.resource_id}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <SeverityBadge severity={c.severity} />
                  </td>
                  <td className="px-4 py-3">
                    <ConflictStatusBadge status={c.status} />
                  </td>
                  <td className="px-4 py-3 text-xs text-[#68647b]">
                    {new Date(c.detected_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setSelectedId(c.id); }}
                      className="text-xs font-medium text-[#3525cd] hover:underline"
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-[#d7d4e8] px-4 py-2 text-xs text-[#68647b]">
            Showing {items.length} of {data?.total ?? 0}
          </div>
        </div>
      )}

      {selectedId && (
        <ConflictDrawer
          conflictId={selectedId}
          onClose={() => setSelectedId(null)}
          canManage={canManage}
        />
      )}
    </div>
  );
}

// ── Access debugger tab ───────────────────────────────────────────────────────

const RESOURCE_TYPES_FOR_EXPLAIN = [
  "document", "collection", "connector", "connector_source_item",
  "citation", "graph_entity", "graph_evidence", "evaluation",
  "saved_answer", "knowledge_card", "api_key",
];

const ACTIONS_FOR_EXPLAIN = [
  "list", "view", "search", "chat", "cite", "create",
  "manage", "sync", "export", "evaluate", "delete",
];

function TraceStepRow({ step }: { step: TraceStep }) {
  const dotCls =
    step.outcome === "allow"
      ? "bg-emerald-400"
      : step.outcome === "deny"
        ? "bg-red-400"
        : "bg-slate-300";
  return (
    <div className="flex items-start gap-3 py-1.5">
      <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dotCls}`} />
      <div className="flex-1 text-xs">
        <span className="font-mono text-[#2a2640]">{step.rule}</span>
        <span
          className={`ml-2 font-bold uppercase ${
            step.outcome === "allow"
              ? "text-emerald-600"
              : step.outcome === "deny"
                ? "text-red-600"
                : "text-slate-400"
          }`}
        >
          {step.outcome}
        </span>
        {step.detail && (
          <span className="ml-2 text-[#68647b]">({step.detail})</span>
        )}
      </div>
    </div>
  );
}

function AccessDebuggerTab() {
  const [subjectUserId, setSubjectUserId] = useState("");
  const [resourceType, setResourceType] = useState("document");
  const [action, setAction] = useState("view");
  const [resourceId, setResourceId] = useState("");
  const [result, setResult] = useState<ExplainDecisionResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const debugMutation = useMutation({
    mutationFn: () =>
      explainDecision({
        subject_user_id: subjectUserId.trim(),
        resource_type: resourceType,
        action,
        resource_id: resourceId.trim() || null,
      }),
    onSuccess: (data) => {
      setResult(data);
      setFormError(null);
    },
    onError: (err) => {
      setFormError(getApiErrorMessage(err));
      setResult(null);
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!subjectUserId.trim()) {
      setFormError("Subject user ID is required.");
      return;
    }
    debugMutation.mutate();
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-[#68647b]">
        Simulate the policy engine for any user in your organisation to see exactly why access is
        allowed or denied. Only structural access metadata is returned — no resource content is
        exposed.
      </p>

      <form onSubmit={handleSubmit} className="rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm space-y-4">
        <h3 className="text-sm font-semibold text-[#2a2640]">Check access</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs font-medium text-[#2a2640]">
              Subject user ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={subjectUserId}
              onChange={(e) => setSubjectUserId(e.target.value)}
              required
              placeholder="UUID of the user to check"
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm font-mono focus:border-[#3525cd] focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-[#2a2640]">Resource type</label>
            <select
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
            >
              {RESOURCE_TYPES_FOR_EXPLAIN.map((rt) => (
                <option key={rt} value={rt}>{rt}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-[#2a2640]">Action</label>
            <select
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
            >
              {ACTIONS_FOR_EXPLAIN.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs font-medium text-[#2a2640]">
              Resource ID <span className="text-[#68647b]">(optional)</span>
            </label>
            <input
              type="text"
              value={resourceId}
              onChange={(e) => setResourceId(e.target.value)}
              placeholder="Leave blank to check generic resource access"
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm font-mono focus:border-[#3525cd] focus:outline-none"
            />
          </div>
        </div>

        {formError && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{formError}</p>
        )}

        <button
          type="submit"
          disabled={debugMutation.isPending}
          className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
        >
          {debugMutation.isPending ? "Checking…" : "Check access"}
        </button>
      </form>

      {result && (
        <div className="rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm space-y-5">
          <div className="flex items-center gap-4">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-bold uppercase ${
                result.decision === "allow"
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-red-50 text-red-700"
              }`}
            >
              {result.decision === "allow" ? "✓" : "✗"} {result.decision}
            </span>
            <div className="text-xs text-[#68647b]">
              Rule: <span className="font-mono text-[#2a2640]">{result.matched_rule}</span>
              {result.deny_reason && (
                <span className="ml-3">
                  Reason: <span className="font-mono text-red-700">{result.deny_reason}</span>
                </span>
              )}
            </div>
          </div>

          <div>
            <p className="mb-2 text-xs font-bold uppercase text-[#5d58a8]">Policy trace</p>
            <div className="rounded-lg border border-[#d7d4e8] bg-[#f9f8ff] px-4 py-3 divide-y divide-[#ede9fb]">
              {result.trace.map((step, i) => (
                <TraceStepRow key={i} step={step} />
              ))}
            </div>
          </div>

          {result.remediation.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-bold uppercase text-[#5d58a8]">How to grant access</p>
              <ul className="space-y-1.5">
                {result.remediation.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-[#2a2640]">
                    <span className="mt-0.5 shrink-0 text-[#3525cd]">→</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-[10px] text-[#a09dbf]">Request ID: {result.request_id}</p>
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
    { id: "conflicts", label: "Conflicts" },
    { id: "access-debugger", label: "Access Debugger" },
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
        {activeTab === "conflicts" && <ConflictsTab canManage={canManage} />}
        {activeTab === "access-debugger" && <AccessDebuggerTab />}
      </div>
    </div>
  );
}
