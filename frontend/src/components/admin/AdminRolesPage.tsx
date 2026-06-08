"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";
import {
  createCustomRole,
  deleteCustomRole,
  listPermissions,
  listRoles,
  updateCustomRole,
  type BuiltinRole,
  type CustomRole,
  type PermissionEntry,
} from "@/lib/api/roles";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { usePermissions } from "@/lib/use-permissions";

type PanelState =
  | { kind: "idle" }
  | { kind: "create" }
  | { kind: "edit"; role: CustomRole }
  | { kind: "view_builtin"; role: BuiltinRole };

const QUERY_ROLES = ["admin", "roles", "list"] as const;
const QUERY_PERMISSIONS = ["admin", "permissions", "catalog"] as const;

function categoryLabel(category: string): string {
  return category
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function groupPermissions(
  permissions: PermissionEntry[],
): Record<string, PermissionEntry[]> {
  const grouped: Record<string, PermissionEntry[]> = {};
  for (const entry of permissions) {
    if (!grouped[entry.category]) {
      grouped[entry.category] = [];
    }
    grouped[entry.category].push(entry);
  }
  return grouped;
}

function PermissionCheckbox({
  entry,
  checked,
  onChange,
  disabled,
}: {
  entry: PermissionEntry;
  checked: boolean;
  onChange: (perm: string, checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="group flex cursor-pointer items-start gap-2">
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 cursor-pointer accent-[#3525cd]"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(entry.permission, e.target.checked)}
      />
      <span className="text-sm text-[#2a2640]">
        <span className="font-medium">{entry.permission.split(":")[1]}</span>
        {entry.description ? (
          <span className="block text-xs text-[#68647b]">
            {entry.description}
          </span>
        ) : null}
      </span>
    </label>
  );
}

function BuiltinRoleCard({
  role,
  onView,
}: {
  role: BuiltinRole;
  onView: (role: BuiltinRole) => void;
}) {
  return (
    <div className="rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-semibold text-[#2a2640]">{role.label}</span>
        <span className="rounded-full bg-[#f0eeff] px-2 py-0.5 text-xs font-medium text-[#5d58a8]">
          Built-in
        </span>
      </div>
      <p className="mb-3 text-sm text-[#68647b]">{role.description}</p>
      <div className="mb-3 flex flex-wrap gap-1">
        {role.permissions.slice(0, 5).map((p) => (
          <span
            key={p}
            className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#4d4880]"
          >
            {p}
          </span>
        ))}
        {role.permissions.length > 5 && (
          <span className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#4d4880]">
            +{role.permissions.length - 5} more
          </span>
        )}
      </div>
      <button
        type="button"
        onClick={() => onView(role)}
        className="text-sm font-medium text-[#3525cd] hover:underline"
      >
        View permissions
      </button>
    </div>
  );
}

function CustomRoleCard({
  role,
  onEdit,
  onDelete,
  canManage,
}: {
  role: CustomRole;
  onEdit: (role: CustomRole) => void;
  onDelete: (role: CustomRole) => void;
  canManage: boolean;
}) {
  return (
    <div className="rounded-xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-semibold text-[#2a2640]">{role.name}</span>
        {role.base_role && (
          <span className="rounded-full bg-[#e8f5e9] px-2 py-0.5 text-xs font-medium text-[#2e7d32]">
            Based on {role.base_role}
          </span>
        )}
      </div>
      {role.description && (
        <p className="mb-3 text-sm text-[#68647b]">{role.description}</p>
      )}
      <div className="mb-3 flex flex-wrap gap-1">
        {role.permissions.slice(0, 5).map((p) => (
          <span
            key={p}
            className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#4d4880]"
          >
            {p}
          </span>
        ))}
        {role.permissions.length > 5 && (
          <span className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#4d4880]">
            +{role.permissions.length - 5} more
          </span>
        )}
      </div>
      {canManage && (
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => onEdit(role)}
            className="text-sm font-medium text-[#3525cd] hover:underline"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => onDelete(role)}
            className="text-sm font-medium text-red-600 hover:underline"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

function RoleFormPanel({
  mode,
  existingRole,
  allPermissions,
  onClose,
  onSaved,
}: {
  mode: "create" | "edit";
  existingRole?: CustomRole;
  allPermissions: PermissionEntry[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(existingRole?.name ?? "");
  const [description, setDescription] = useState(
    existingRole?.description ?? "",
  );
  const [baseRole, setBaseRole] = useState(existingRole?.base_role ?? "");
  const [selectedPerms, setSelectedPerms] = useState<Set<string>>(
    new Set(existingRole?.permissions ?? []),
  );
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const createMutation = useMutation({
    mutationFn: () =>
      createCustomRole({
        name: name.trim(),
        description: description.trim() || null,
        base_role: baseRole || null,
        permissions: Array.from(selectedPerms),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_ROLES });
      onSaved();
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      updateCustomRole(existingRole!.id, {
        name: name.trim(),
        description: description.trim() || null,
        base_role: baseRole || null,
        permissions: Array.from(selectedPerms),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_ROLES });
      onSaved();
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const isPending = createMutation.isPending || updateMutation.isPending;
  const grouped = groupPermissions(allPermissions);

  function togglePerm(perm: string, checked: boolean) {
    setSelectedPerms((prev) => {
      const next = new Set(prev);
      if (checked) next.add(perm);
      else next.delete(perm);
      return next;
    });
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (mode === "create") createMutation.mutate();
    else updateMutation.mutate();
  }

  const BUILTIN_ROLES = [
    "owner",
    "admin",
    "member",
    "viewer",
    "reviewer",
    "developer",
    "security_admin",
    "billing_admin",
  ];

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-lg flex-col border-l border-[#d7d4e8] bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-[#d7d4e8] px-6 py-4">
        <h2 className="text-lg font-semibold text-[#2a2640]">
          {mode === "create" ? "Create Custom Role" : "Edit Custom Role"}
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="text-[#68647b] hover:text-[#2a2640]"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-1 flex-col overflow-y-auto"
      >
        <div className="flex-1 space-y-5 px-6 py-5">
          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={64}
              required
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              placeholder="e.g. Read-only analyst"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              maxLength={512}
              className="w-full resize-none rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              placeholder="Optional description"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Based on role (optional)
            </label>
            <select
              value={baseRole}
              onChange={(e) => setBaseRole(e.target.value)}
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
            >
              <option value="">None</option>
              {BUILTIN_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-[#68647b]">
              Inherits the selected role&apos;s permissions in addition to those
              below.
            </p>
          </div>

          <div>
            <p className="mb-2 text-sm font-medium text-[#2a2640]">
              Permissions
            </p>
            <div className="space-y-4">
              {Object.entries(grouped).map(([category, entries]) => (
                <div key={category}>
                  <p className="mb-1.5 text-xs font-bold tracking-wide text-[#5d58a8] uppercase">
                    {categoryLabel(category)}
                  </p>
                  <div className="space-y-2 rounded-lg bg-[#f9f8ff] p-3">
                    {entries.map((entry) => (
                      <PermissionCheckbox
                        key={entry.permission}
                        entry={entry}
                        checked={selectedPerms.has(entry.permission)}
                        onChange={togglePerm}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {error && (
          <p className="mx-6 mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <div className="flex gap-3 border-t border-[#d7d4e8] px-6 py-4">
          <button
            type="submit"
            disabled={isPending || !name.trim()}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
          >
            {isPending
              ? "Saving…"
              : mode === "create"
                ? "Create role"
                : "Save changes"}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </form>
    </aside>
  );
}

function BuiltinRolePanel({
  role,
  allPermissions,
  onClose,
}: {
  role: BuiltinRole;
  allPermissions: PermissionEntry[];
  onClose: () => void;
}) {
  const grouped = groupPermissions(allPermissions);
  const rolePerms = new Set(role.permissions);

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-lg flex-col border-l border-[#d7d4e8] bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-[#d7d4e8] px-6 py-4">
        <div>
          <h2 className="text-lg font-semibold text-[#2a2640]">{role.label}</h2>
          <p className="text-sm text-[#68647b]">{role.description}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-[#68647b] hover:text-[#2a2640]"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
        {Object.entries(grouped).map(([category, entries]) => (
          <div key={category}>
            <p className="mb-1.5 text-xs font-bold tracking-wide text-[#5d58a8] uppercase">
              {categoryLabel(category)}
            </p>
            <div className="space-y-2 rounded-lg bg-[#f9f8ff] p-3">
              {entries.map((entry) => (
                <PermissionCheckbox
                  key={entry.permission}
                  entry={entry}
                  checked={rolePerms.has(entry.permission)}
                  onChange={() => {}}
                  disabled
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}

export function AdminRolesPage() {
  const { hasPermission } = usePermissions();
  const canView = hasPermission("roles:view");
  const canManage = hasPermission("roles:manage");

  const [panel, setPanel] = useState<PanelState>({ kind: "idle" });
  const [deleteTarget, setDeleteTarget] = useState<CustomRole | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [forbiddenRequestId, setForbiddenRequestId] = useState<string | null>(
    null,
  );

  const queryClient = useQueryClient();

  const rolesQuery = useQuery({
    queryKey: QUERY_ROLES,
    queryFn: listRoles,
    enabled: canView,
  });

  const permissionsQuery = useQuery({
    queryKey: QUERY_PERMISSIONS,
    queryFn: listPermissions,
    enabled: canView,
  });

  const deleteMutation = useMutation({
    mutationFn: (roleId: string) => deleteCustomRole(roleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_ROLES });
      setDeleteTarget(null);
      setDeleteError(null);
    },
    onError: (err) => setDeleteError(getApiErrorMessage(err)),
  });

  if (!canView) {
    return (
      <ForbiddenState
        title="Roles &amp; Permissions"
        description="You need the roles:view permission to access this page."
        requestId={forbiddenRequestId}
        backHref="/dashboard"
      />
    );
  }

  const isLoading = rolesQuery.isLoading || permissionsQuery.isLoading;
  const loadError = rolesQuery.error ?? permissionsQuery.error;

  if (isLoading) return <LoadingState />;

  if (loadError) {
    if (isForbiddenError(loadError)) {
      return (
        <ForbiddenState
          title="Roles &amp; Permissions"
          description="You do not have access to role management."
          requestId={extractRequestIdFromError(loadError)}
          backHref="/dashboard"
        />
      );
    }
    return <ErrorState message={getApiErrorMessage(loadError)} />;
  }

  const roles = rolesQuery.data ?? { builtin_roles: [], custom_roles: [] };
  const allPermissions = permissionsQuery.data?.items ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-8">
      <div className="flex items-start justify-between">
        <div>
          <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            Admin
          </p>
          <h1 className="text-2xl font-extrabold text-[#2a2640]">
            Roles &amp; Permissions
          </h1>
          <p className="mt-1 text-sm text-[#68647b]">
            Manage built-in roles and create custom roles for your organization.
          </p>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={() => setPanel({ kind: "create" })}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            + Create role
          </button>
        )}
      </div>

      <section>
        <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
          Built-in roles
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {roles.builtin_roles.map((role) => (
            <BuiltinRoleCard
              key={role.role}
              role={role}
              onView={(r) => setPanel({ kind: "view_builtin", role: r })}
            />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
          Custom roles
          <span className="ml-2 text-sm font-normal text-[#68647b]">
            ({roles.custom_roles.length})
          </span>
        </h2>
        {roles.custom_roles.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[#d7d4e8] p-8 text-center text-sm text-[#68647b]">
            No custom roles yet.
            {canManage && (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => setPanel({ kind: "create" })}
                  className="font-medium text-[#3525cd] hover:underline"
                >
                  Create one
                </button>{" "}
                to extend the built-in role set.
              </>
            )}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {roles.custom_roles.map((role) => (
              <CustomRoleCard
                key={role.id}
                role={role}
                canManage={canManage}
                onEdit={(r) => setPanel({ kind: "edit", role: r })}
                onDelete={(r) => {
                  setDeleteTarget(r);
                  setDeleteError(null);
                }}
              />
            ))}
          </div>
        )}
      </section>

      {deleteTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-dialog-title"
        >
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h3
              id="delete-dialog-title"
              className="mb-2 text-base font-semibold text-[#2a2640]"
            >
              Delete &ldquo;{deleteTarget.name}&rdquo;?
            </h3>
            <p className="mb-4 text-sm text-[#68647b]">
              Members assigned this role will fall back to their base built-in
              role. This cannot be undone.
            </p>
            {deleteError && (
              <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {deleteError}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => deleteMutation.mutate(deleteTarget.id)}
                disabled={deleteMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Deleting…" : "Delete role"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setDeleteTarget(null);
                  setDeleteError(null);
                }}
                disabled={deleteMutation.isPending}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {panel.kind === "create" && (
        <RoleFormPanel
          mode="create"
          allPermissions={allPermissions}
          onClose={() => setPanel({ kind: "idle" })}
          onSaved={() => setPanel({ kind: "idle" })}
        />
      )}

      {panel.kind === "edit" && (
        <RoleFormPanel
          mode="edit"
          existingRole={panel.role}
          allPermissions={allPermissions}
          onClose={() => setPanel({ kind: "idle" })}
          onSaved={() => setPanel({ kind: "idle" })}
        />
      )}

      {panel.kind === "view_builtin" && (
        <BuiltinRolePanel
          role={panel.role}
          allPermissions={allPermissions}
          onClose={() => setPanel({ kind: "idle" })}
        />
      )}
    </div>
  );
}
