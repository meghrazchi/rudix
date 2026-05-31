"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  createCollection,
  deleteCollection,
  getCollection,
  getCollectionPolicy,
  listCollectionDocuments,
  listCollections,
  removeDocumentFromCollection,
  updateCollection,
  updateCollectionPolicy,
  type CollectionAccessGrant,
  type CollectionAccessPolicy,
  type CollectionDetailResponse,
  type CollectionListItemResponse,
} from "@/lib/api/collections";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import {
  extractRequestIdFromError,
  isForbiddenError,
  isEndpointNotFoundError,
} from "@/lib/forbidden";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { useAuthSession } from "@/lib/use-auth-session";
import type { AppRole } from "@/lib/auth-session";
import {
  getTeamCapabilities,
  listTeamMembers,
  type TeamMember,
} from "@/lib/api/team";

const COLLECTIONS_PAGE_SIZE = 20;
const COLLECTION_DOCS_PAGE_SIZE = 10;

type CollectionCapabilities = {
  canCreate: boolean;
  canEdit: boolean;
  canDelete: boolean;
  canManageDocuments: boolean;
  canManagePolicy: boolean;
};

function resolveCollectionCapabilities(
  role: AppRole | undefined,
): CollectionCapabilities {
  const isAdminLike = role === "owner" || role === "admin";
  const isMember = role === "member";
  return {
    canCreate: isAdminLike || isMember,
    canEdit: isAdminLike || isMember,
    canDelete: isAdminLike,
    canManageDocuments: isAdminLike || isMember,
    canManagePolicy: isAdminLike,
  };
}

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function accessPolicyLabel(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide":
      return "Org-wide";
    case "admin_only":
      return "Admin-only";
    case "selected_roles":
      return "Selected roles";
    case "selected_members":
      return "Selected members";
    default:
      return policy;
  }
}

function accessPolicyBadgeClass(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide":
      return "bg-emerald-100 text-emerald-800";
    case "admin_only":
      return "bg-rose-100 text-rose-800";
    case "selected_roles":
      return "bg-amber-100 text-amber-800";
    case "selected_members":
      return "bg-blue-100 text-blue-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function accessPolicyDescription(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide":
      return "All organization members can view and query this collection.";
    case "admin_only":
      return "Only organization owners and admins can access this collection.";
    case "selected_roles":
      return "Only members with the specified roles can access this collection.";
    case "selected_members":
      return "Only explicitly listed members can access this collection.";
    default:
      return "";
  }
}

const GRANTABLE_ROLES: Array<{ value: string; label: string }> = [
  { value: "member", label: "Member" },
  { value: "viewer", label: "Viewer" },
];

// ── Policy editor ──────────────────────────────────────────────────────────────

type PolicyEditorProps = {
  collectionId: string;
  collectionName: string;
};

function PolicyEditor({ collectionId, collectionName }: PolicyEditorProps) {
  const queryClient = useQueryClient();
  const teamCapabilities = getTeamCapabilities();

  const policyQuery = useQuery({
    queryKey: queryKeys.collections.policy(collectionId),
    queryFn: () => getCollectionPolicy(collectionId),
  });

  const membersQuery = useQuery({
    queryKey: ["team", "members", "policy-picker"],
    queryFn: () => listTeamMembers({ limit: 200 }),
    enabled: teamCapabilities.listMembersEnabled,
  });

  const [policy, setPolicy] = useState<CollectionAccessPolicy | null>(null);
  const [roleGrants, setRoleGrants] = useState<Set<string>>(new Set());
  const [memberGrants, setMemberGrants] = useState<Set<string>>(new Set());
  const [isDirty, setIsDirty] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [showWarning, setShowWarning] = useState(false);

  // Sync state when policy data arrives
  useEffect(() => {
    if (!policyQuery.data || isDirty) return;
    const data = policyQuery.data;
    setPolicy(data.access_policy);
    setRoleGrants(
      new Set(
        data.grants
          .filter((g) => g.grantee_type === "role")
          .map((g) => g.grantee_value),
      ),
    );
    setMemberGrants(
      new Set(
        data.grants
          .filter((g) => g.grantee_type === "member")
          .map((g) => g.grantee_value),
      ),
    );
  }, [policyQuery.data, isDirty]);

  const saveMutation = useMutation({
    mutationFn: (req: { access_policy: CollectionAccessPolicy; grants: CollectionAccessGrant[] }) =>
      updateCollectionPolicy(collectionId, req),
    onSuccess: async () => {
      setSaveError(null);
      setIsDirty(false);
      setShowWarning(false);
      await invalidateAfterMutation(queryClient, "collection.policy.update");
    },
    onError: (error) => {
      setSaveError(getApiErrorMessage(error));
    },
  });

  function buildGrants(): CollectionAccessGrant[] {
    if (!policy) return [];
    if (policy === "selected_roles") {
      return Array.from(roleGrants).map((v) => ({ grantee_type: "role" as const, grantee_value: v }));
    }
    if (policy === "selected_members") {
      return Array.from(memberGrants).map((v) => ({ grantee_type: "member" as const, grantee_value: v }));
    }
    return [];
  }

  function handlePolicyChange(next: CollectionAccessPolicy) {
    const current = policyQuery.data?.access_policy ?? "org_wide";
    const isMoreRestrictive =
      current === "org_wide" && next !== "org_wide";
    if (isMoreRestrictive) {
      setShowWarning(true);
    }
    setPolicy(next);
    setIsDirty(true);
  }

  function handleRoleToggle(role: string) {
    setRoleGrants((prev) => {
      const next = new Set(prev);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return next;
    });
    setIsDirty(true);
  }

  function handleMemberToggle(userId: string) {
    setMemberGrants((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
    setIsDirty(true);
  }

  function handleSave() {
    if (!policy) return;
    saveMutation.mutate({ access_policy: policy, grants: buildGrants() });
  }

  function handleDiscard() {
    setIsDirty(false);
    setShowWarning(false);
    setSaveError(null);
    if (policyQuery.data) {
      const data = policyQuery.data;
      setPolicy(data.access_policy);
      setRoleGrants(new Set(data.grants.filter((g) => g.grantee_type === "role").map((g) => g.grantee_value)));
      setMemberGrants(new Set(data.grants.filter((g) => g.grantee_type === "member").map((g) => g.grantee_value)));
    }
  }

  if (policyQuery.isLoading) {
    return <LoadingState compact title="Loading access policy…" />;
  }
  if (policyQuery.isError) {
    if (isForbiddenError(policyQuery.error)) {
      return (
        <ForbiddenState
          compact
          title="Policy access denied"
          description="You do not have permission to view or manage this collection's access policy."
          requestId={extractRequestIdFromError(policyQuery.error)}
        />
      );
    }
    return (
      <ErrorState
        compact
        error={policyQuery.error}
        description={getApiErrorMessage(policyQuery.error)}
        onRetry={() => void policyQuery.refetch()}
      />
    );
  }

  const effectivePolicy = policy ?? policyQuery.data?.access_policy ?? "org_wide";

  const members: TeamMember[] = membersQuery.data?.items ?? [];
  const filteredMembers = members.filter(
    (m) => m.role !== "owner" && m.role !== "admin" && m.user_id,
  );

  return (
    <div className="space-y-4 rounded-xl border border-[#e5e3f1] bg-[#faf9ff] p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          Access Policy
        </p>
        {isDirty ? (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleDiscard}
              disabled={saveMutation.isPending}
              className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-60"
            >
              Discard
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saveMutation.isPending}
              className="rounded bg-[#3525cd] px-3 py-1 text-xs font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saveMutation.isPending ? "Saving…" : "Save policy"}
            </button>
          </div>
        ) : null}
      </div>

      {showWarning ? (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <span className="material-symbols-outlined mt-0.5 shrink-0 text-base text-amber-700">
            warning
          </span>
          <p className="text-xs text-amber-800">
            You are restricting access to <strong>{collectionName}</strong>. Members who
            currently have access may lose it immediately after saving.
          </p>
        </div>
      ) : null}

      <div>
        <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          Mode
        </label>
        <select
          value={effectivePolicy}
          onChange={(e) => handlePolicyChange(e.target.value as CollectionAccessPolicy)}
          className="h-9 w-full rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
        >
          <option value="org_wide">Org-wide — all members</option>
          <option value="admin_only">Admin-only — owners and admins</option>
          <option value="selected_roles">Selected roles</option>
          <option value="selected_members">Selected members</option>
        </select>
        <p className="mt-1 text-xs text-[#7a768f]">
          {accessPolicyDescription(effectivePolicy)}
        </p>
      </div>

      {effectivePolicy === "selected_roles" ? (
        <div>
          <p className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Roles with access
          </p>
          <p className="mb-2 text-xs text-[#7a768f]">
            Owners and admins always have access. Choose which other roles can see this collection.
          </p>
          <div className="space-y-1">
            {GRANTABLE_ROLES.map(({ value, label }) => (
              <label
                key={value}
                className="flex cursor-pointer items-center gap-3 rounded-lg border border-[#e5e3f1] bg-white px-3 py-2 hover:bg-[#f5f3ff]"
              >
                <input
                  type="checkbox"
                  checked={roleGrants.has(value)}
                  onChange={() => handleRoleToggle(value)}
                  className="accent-[#3525cd]"
                />
                <span className="text-sm font-semibold text-[#2a2640]">{label}</span>
              </label>
            ))}
          </div>
          {roleGrants.size === 0 ? (
            <p className="mt-1 text-xs text-amber-700">
              No roles selected — only admins will have access.
            </p>
          ) : null}
        </div>
      ) : null}

      {effectivePolicy === "selected_members" ? (
        <div>
          <p className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Members with access
          </p>
          <p className="mb-2 text-xs text-[#7a768f]">
            Owners and admins always have access. Select additional members below.
          </p>
          {!teamCapabilities.listMembersEnabled ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Team members list is not configured. Set{" "}
              <code>NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL</code> to enable the member picker.
            </p>
          ) : membersQuery.isLoading ? (
            <LoadingState compact title="Loading members…" />
          ) : filteredMembers.length === 0 ? (
            <EmptyState
              compact
              title="No eligible members."
              description="All organization members are admins or owners who already have access."
            />
          ) : (
            <ul className="max-h-52 space-y-1 overflow-auto rounded-lg border border-[#e5e3f1] bg-white p-2">
              {filteredMembers.map((m) => (
                <li key={m.user_id}>
                  <label className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-[#f5f3ff]">
                    <input
                      type="checkbox"
                      checked={memberGrants.has(m.user_id!)}
                      onChange={() => handleMemberToggle(m.user_id!)}
                      className="accent-[#3525cd]"
                    />
                    <span className="flex-1">
                      <span className="block text-sm font-semibold text-[#2a2640]">
                        {m.name}
                      </span>
                      <span className="block text-xs text-[#68647b]">
                        {m.email}{" "}
                        <span className="rounded-full bg-[#f0eeff] px-1.5 py-0.5 text-[10px] font-bold uppercase text-[#4535b5]">
                          {m.role}
                        </span>
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          {memberGrants.size === 0 && teamCapabilities.listMembersEnabled ? (
            <p className="mt-1 text-xs text-amber-700">
              No members selected — only admins will have access.
            </p>
          ) : null}
        </div>
      ) : null}

      {saveError ? (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {saveError}
        </p>
      ) : null}

      {!isDirty && policyQuery.data ? (
        <CurrentAccessSummary
          policy={policyQuery.data.access_policy}
          grants={policyQuery.data.grants}
          members={members}
        />
      ) : null}
    </div>
  );
}

type CurrentAccessSummaryProps = {
  policy: CollectionAccessPolicy;
  grants: CollectionAccessGrant[];
  members: TeamMember[];
};

function CurrentAccessSummary({ policy, grants, members }: CurrentAccessSummaryProps) {
  if (policy === "org_wide") {
    return (
      <p className="text-xs text-[#68647b]">
        All organization members currently have access.
      </p>
    );
  }
  if (policy === "admin_only") {
    return (
      <p className="text-xs text-[#68647b]">Only owners and admins have access.</p>
    );
  }
  if (policy === "selected_roles") {
    const roles = grants.filter((g) => g.grantee_type === "role").map((g) => g.grantee_value);
    return (
      <p className="text-xs text-[#68647b]">
        Access granted to: <strong>owners, admins</strong>
        {roles.length > 0 ? `, and ${roles.join(", ")}s` : " only"}.
      </p>
    );
  }
  if (policy === "selected_members") {
    const memberIds = new Set(
      grants.filter((g) => g.grantee_type === "member").map((g) => g.grantee_value),
    );
    const named = members
      .filter((m) => m.user_id && memberIds.has(m.user_id))
      .map((m) => m.name || m.email);
    const count = memberIds.size;
    return (
      <p className="text-xs text-[#68647b]">
        {count === 0
          ? "No members explicitly granted — only admins have access."
          : named.length > 0
            ? `Explicitly granted: ${named.join(", ")}.`
            : `${count} member${count === 1 ? "" : "s"} explicitly granted.`}
      </p>
    );
  }
  return null;
}

// ── Form / dialog ──────────────────────────────────────────────────────────────

type CollectionFormState = {
  name: string;
  description: string;
  access_policy: CollectionAccessPolicy;
};

const DEFAULT_FORM: CollectionFormState = {
  name: "",
  description: "",
  access_policy: "org_wide",
};

type CollectionFormErrors = {
  name?: string;
};

function validateCollectionForm(form: CollectionFormState): CollectionFormErrors {
  const errors: CollectionFormErrors = {};
  if (!form.name.trim()) {
    errors.name = "Name is required.";
  } else if (form.name.trim().length > 120) {
    errors.name = "Name must be 120 characters or fewer.";
  }
  return errors;
}

type CollectionDialogProps = {
  title: string;
  initial: CollectionFormState;
  saving: boolean;
  saveError: string | null;
  onSave: (form: CollectionFormState) => void;
  onClose: () => void;
};

function CollectionDialog({
  title,
  initial,
  saving,
  saveError,
  onSave,
  onClose,
}: CollectionDialogProps) {
  const [form, setForm] = useState<CollectionFormState>(initial);
  const [fieldErrors, setFieldErrors] = useState<CollectionFormErrors>({});
  const nameRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validateCollectionForm(form);
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});
    onSave(form);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#17172a]/40 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            Cancel
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Name <span className="text-rose-600">*</span>
            </label>
            <input
              ref={nameRef}
              type="text"
              value={form.name}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, name: event.target.value }))
              }
              maxLength={120}
              placeholder="e.g. Engineering Handbook"
              className="h-9 w-full rounded-lg border border-[#d2cee6] bg-white px-3 text-sm font-medium text-[#2a2640] placeholder:font-normal placeholder:text-[#b0abc8] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            />
            {fieldErrors.name ? (
              <p className="mt-1 text-xs text-rose-700">{fieldErrors.name}</p>
            ) : null}
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Description
            </label>
            <textarea
              value={form.description}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  description: event.target.value,
                }))
              }
              rows={3}
              maxLength={500}
              placeholder="Optional: describe this collection's purpose or contents."
              className="w-full rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm font-medium text-[#2a2640] placeholder:font-normal placeholder:text-[#b0abc8] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Access Policy
            </label>
            <select
              value={form.access_policy}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  access_policy: event.target.value as CollectionAccessPolicy,
                }))
              }
              className="h-9 w-full rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            >
              <option value="org_wide">Org-wide — all members</option>
              <option value="admin_only">Admin-only</option>
              <option value="selected_roles">Selected roles</option>
              <option value="selected_members">Selected members</option>
            </select>
            <p className="mt-1 text-xs text-[#7a768f]">
              {accessPolicyDescription(form.access_policy)}
            </p>
          </div>

          {saveError ? (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {saveError}
            </p>
          ) : null}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#d2cee6] bg-white px-4 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Collection detail panel ────────────────────────────────────────────────────

type CollectionDetailPanelProps = {
  collectionId: string;
  capabilities: CollectionCapabilities;
  onClose: () => void;
  onEdit: (collection: CollectionDetailResponse) => void;
};

function CollectionDetailPanel({
  collectionId,
  capabilities,
  onClose,
  onEdit,
}: CollectionDetailPanelProps) {
  const queryClient = useQueryClient();
  const [docsOffset, setDocsOffset] = useState(0);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  const detailQuery = useQuery({
    queryKey: queryKeys.collections.detail(collectionId),
    queryFn: () => getCollection(collectionId),
  });

  const docsQueryParams = { limit: COLLECTION_DOCS_PAGE_SIZE, offset: docsOffset };
  const docsQuery = useQuery({
    queryKey: queryKeys.collections.documents(collectionId, docsQueryParams),
    queryFn: () =>
      listCollectionDocuments(collectionId, docsQueryParams),
  });

  const removeDocMutation = useMutation({
    mutationFn: (documentId: string) =>
      removeDocumentFromCollection(collectionId, documentId),
    onSuccess: async () => {
      setActionFeedback("Document removed from collection.");
      await invalidateAfterMutation(
        queryClient,
        "collection.document.remove",
      );
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
    },
  });

  const detail = detailQuery.data;
  const docs = docsQuery.data;
  const canGoNext =
    Boolean(docs) && docsOffset + COLLECTION_DOCS_PAGE_SIZE < (docs?.total ?? 0);
  const canGoPrev = docsOffset > 0;

  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-wide text-[#3525cd] uppercase">
            Collection detail
          </p>
          {detail ? (
            <h2 className="mt-0.5 text-lg font-bold text-[#2a2640]">
              {detail.name}
            </h2>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {detail && capabilities.canEdit ? (
            <button
              type="button"
              onClick={() => onEdit(detail)}
              className="rounded border border-[#d2cee6] px-3 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f3f1ff]"
            >
              Edit
            </button>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            Close
          </button>
        </div>
      </div>

      {detailQuery.isLoading ? (
        <LoadingState title="Loading collection…" />
      ) : null}

      {detailQuery.isError ? (
        isForbiddenError(detailQuery.error) ? (
          <ForbiddenState
            compact
            title="Collection access denied"
            description="You do not have permission to view this collection."
            requestId={extractRequestIdFromError(detailQuery.error)}
          />
        ) : (
          <ErrorState
            error={detailQuery.error}
            description={getApiErrorMessage(detailQuery.error)}
            onRetry={() => void detailQuery.refetch()}
          />
        )
      ) : null}

      {detail ? (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="Documents" value={detail.document_count} />
            <MetricCard label="Indexed" value={detail.indexed_count} />
            <MetricCard
              label="Access policy"
              value={
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${accessPolicyBadgeClass(detail.access_policy)}`}
                >
                  {accessPolicyLabel(detail.access_policy)}
                </span>
              }
            />
            <MetricCard label="Owner" value={detail.owner_email ?? detail.owner_id} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <MetricCard label="Created" value={formatDate(detail.created_at)} />
            <MetricCard label="Updated" value={formatDate(detail.updated_at)} />
          </div>

          {detail.description ? (
            <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
              <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                Description
              </p>
              <p className="text-sm text-[#2a2640]">{detail.description}</p>
            </div>
          ) : null}

          {capabilities.canManagePolicy ? (
            <PolicyEditor
              collectionId={collectionId}
              collectionName={detail.name}
            />
          ) : null}

          {actionFeedback ? (
            <p
              role="status"
              className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
            >
              {actionFeedback}
            </p>
          ) : null}

          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <h3 className="text-base font-bold text-[#2a2640]">
                Documents in this collection
              </h3>
              {docsQuery.isFetching ? (
                <span className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Refreshing…
                </span>
              ) : null}
            </div>

            {docsQuery.isLoading ? (
              <LoadingState compact title="Loading documents…" />
            ) : docsQuery.isError ? (
              <ErrorState
                compact
                error={docsQuery.error}
                description={getApiErrorMessage(docsQuery.error)}
                onRetry={() => void docsQuery.refetch()}
              />
            ) : docs && docs.items.length === 0 ? (
              <EmptyState
                compact
                title="No documents in this collection yet."
                description="Add documents from the Documents page using the collection assignment action."
              />
            ) : docs && docs.items.length > 0 ? (
              <div className="overflow-hidden rounded-xl border border-[#e5e3f1]">
                <table className="min-w-full border-collapse bg-white text-left">
                  <thead className="border-b border-[#e5e3f1] bg-[#f8f7ff]">
                    <tr className="text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase">
                      <th className="px-4 py-2">Filename</th>
                      <th className="px-4 py-2">Status</th>
                      <th className="px-4 py-2">Updated</th>
                      {capabilities.canManageDocuments ? (
                        <th className="px-4 py-2 text-right">Actions</th>
                      ) : null}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#ece9f6]">
                    {docs.items.map((doc) => (
                      <tr
                        key={doc.document_id}
                        className="align-top transition-colors hover:bg-[#faf9ff]"
                      >
                        <td className="px-4 py-2">
                          <Link
                            href={`/documents/${encodeURIComponent(doc.document_id)}`}
                            className="text-sm font-semibold text-[#3525cd] hover:underline"
                          >
                            {doc.filename}
                          </Link>
                          <p className="text-xs text-[#7a768f]">
                            {doc.document_id}
                          </p>
                        </td>
                        <td className="px-4 py-2">
                          <span className="rounded-full bg-[#f0eeff] px-2 py-0.5 text-[10px] font-bold uppercase text-[#4535b5]">
                            {doc.status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-sm text-[#68647b]">
                          {formatDate(doc.updated_at)}
                        </td>
                        {capabilities.canManageDocuments ? (
                          <td className="px-4 py-2 text-right">
                            <button
                              type="button"
                              aria-label="Remove from collection"
                              disabled={removeDocMutation.isPending}
                              onClick={() => {
                                const confirmed = window.confirm(
                                  `Remove "${doc.filename}" from this collection?`,
                                );
                                if (!confirmed) return;
                                removeDocMutation.mutate(doc.document_id);
                              }}
                              className="rounded p-1 text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              <span className="material-symbols-outlined text-[16px]">
                                remove_circle_outline
                              </span>
                            </button>
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="flex items-center justify-between gap-2 border-t border-[#e5e3f1] bg-[#fcfbff] px-4 py-2">
                  <p className="text-xs text-[#6e6a86]">
                    Showing {docs.items.length} of {docs.total} documents.
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={!canGoPrev}
                      onClick={() =>
                        setDocsOffset((prev) =>
                          Math.max(0, prev - COLLECTION_DOCS_PAGE_SIZE),
                        )
                      }
                      className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      disabled={!canGoNext}
                      onClick={() =>
                        setDocsOffset((prev) => prev + COLLECTION_DOCS_PAGE_SIZE)
                      }
                      className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Next
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          <div className="rounded-xl border border-[#e5e3f1] bg-[#faf9ff] p-3">
            <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Usage stats
            </p>
            <p className="text-sm text-[#68647b]">
              Usage analytics will appear here once available.
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function MetricCard({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
      <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </p>
      <div className="text-sm font-semibold text-[#2a2640]">{value}</div>
    </div>
  );
}

// ── Assign collections dialog ──────────────────────────────────────────────────

type AssignCollectionsDialogProps = {
  collectionList: CollectionListItemResponse[];
  loadingCollections: boolean;
  documentName: string;
  currentCollectionIds: string[];
  saving: boolean;
  saveError: string | null;
  onSave: (collectionIds: string[]) => void;
  onClose: () => void;
};

export function AssignCollectionsDialog({
  collectionList,
  loadingCollections,
  documentName,
  currentCollectionIds,
  saving,
  saveError,
  onSave,
  onClose,
}: AssignCollectionsDialogProps) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(currentCollectionIds),
  );

  function toggleCollection(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#17172a]/40 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">
              Assign to Collections
            </h2>
            <p className="text-xs text-[#68647b]">{documentName}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            Cancel
          </button>
        </div>

        {loadingCollections ? (
          <LoadingState compact title="Loading collections…" />
        ) : collectionList.length === 0 ? (
          <EmptyState
            compact
            title="No collections found."
            description="Create a collection first from the Collections page."
          />
        ) : (
          <ul className="max-h-64 space-y-1 overflow-auto">
            {collectionList.map((col) => (
              <li key={col.collection_id}>
                <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-[#e5e3f1] px-3 py-2 hover:bg-[#f5f3ff]">
                  <input
                    type="checkbox"
                    checked={selected.has(col.collection_id)}
                    onChange={() => toggleCollection(col.collection_id)}
                    className="accent-[#3525cd]"
                  />
                  <span className="flex-1">
                    <span className="block text-sm font-semibold text-[#2a2640]">
                      {col.name}
                    </span>
                    <span className="block text-xs text-[#68647b]">
                      {col.document_count} doc{col.document_count !== 1 ? "s" : ""}{" "}
                      •{" "}
                      <span
                        className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase ${accessPolicyBadgeClass(col.access_policy)}`}
                      >
                        {accessPolicyLabel(col.access_policy)}
                      </span>
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}

        {saveError ? (
          <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {saveError}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[#d2cee6] bg-white px-4 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={saving || loadingCollections}
            onClick={() => onSave(Array.from(selected))}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Collections page ───────────────────────────────────────────────────────────

export function CollectionsPage() {
  const queryClient = useQueryClient();
  const { state } = useAuthSession();
  const capabilities = resolveCollectionCapabilities(state.session?.role);
  const collectionsEnabled = getFrontendRuntimeConfig().features.collectionsEnabled;

  const [offset, setOffset] = useState(0);
  const [nameSearch, setNameSearch] = useState("");
  const [debouncedNameSearch, setDebouncedNameSearch] = useState("");
  const [selectedCollectionId, setSelectedCollectionId] = useState<
    string | null
  >(null);
  const [dialogMode, setDialogMode] = useState<
    "create" | { mode: "edit"; collection: CollectionDetailResponse } | null
  >(null);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);
  const [dialogSaveError, setDialogSaveError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedNameSearch(nameSearch);
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [nameSearch]);

  const listQueryOptions = useMemo(
    () => ({
      limit: COLLECTIONS_PAGE_SIZE,
      offset,
      name_query: debouncedNameSearch || undefined,
    }),
    [offset, debouncedNameSearch],
  );

  const collectionsQuery = useQuery({
    queryKey: queryKeys.collections.list(listQueryOptions),
    queryFn: () => listCollections(listQueryOptions),
    enabled: collectionsEnabled,
    retry: (failureCount, error) =>
      !isEndpointNotFoundError(error) && failureCount < 2,
  });

  const collections = collectionsQuery.data?.items ?? [];
  const total = collectionsQuery.data?.total ?? 0;
  const totalPages = Math.max(
    1,
    Math.ceil(Math.max(total, 1) / COLLECTIONS_PAGE_SIZE),
  );
  const currentPage = Math.floor(offset / COLLECTIONS_PAGE_SIZE) + 1;
  const listForbidden = isForbiddenError(collectionsQuery.error);

  const createMutation = useMutation({
    mutationFn: (form: CollectionFormState) =>
      createCollection({
        name: form.name.trim(),
        description: form.description.trim() || null,
        access_policy: form.access_policy,
      }),
    onSuccess: async (result) => {
      setDialogMode(null);
      setDialogSaveError(null);
      setActionFeedback(`Collection "${result.name}" created.`);
      setActionRequestId(null);
      setSelectedCollectionId(result.collection_id);
      await invalidateAfterMutation(queryClient, "collection.create");
    },
    onError: (error) => {
      setDialogSaveError(getApiErrorMessage(error));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      collectionId,
      form,
    }: {
      collectionId: string;
      form: CollectionFormState;
    }) =>
      updateCollection(collectionId, {
        name: form.name.trim(),
        description: form.description.trim() || null,
        access_policy: form.access_policy,
      }),
    onSuccess: async (result) => {
      setDialogMode(null);
      setDialogSaveError(null);
      setActionFeedback(`Collection "${result.name}" updated.`);
      setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "collection.update");
    },
    onError: (error) => {
      setDialogSaveError(getApiErrorMessage(error));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (collectionId: string) => deleteCollection(collectionId),
    onSuccess: async (_, collectionId) => {
      if (selectedCollectionId === collectionId) {
        setSelectedCollectionId(null);
      }
      setActionFeedback("Collection deleted.");
      setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "collection.delete");
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  function handleCreateSave(form: CollectionFormState) {
    setDialogSaveError(null);
    createMutation.mutate(form);
  }

  function handleEditSave(form: CollectionFormState) {
    if (dialogMode === null || dialogMode === "create") return;
    setDialogSaveError(null);
    updateMutation.mutate({
      collectionId: dialogMode.collection.collection_id,
      form,
    });
  }

  function handleDeleteCollection(collection: CollectionListItemResponse) {
    const confirmed = window.confirm(
      `Delete collection "${collection.name}"? Documents will not be deleted, but they will be removed from this collection.`,
    );
    if (!confirmed) return;
    deleteMutation.mutate(collection.collection_id);
  }

  return (
    <section className="space-y-6 bg-white px-4 py-5 lg:px-8 lg:py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-[#1b1b24]">
            Knowledge Base Collections
          </h2>
          <p className="mt-0.5 text-sm text-[#68647b]">
            Organize documents by department, project, or workflow for scoped
            retrieval.
          </p>
        </div>
        {capabilities.canCreate ? (
          <button
            type="button"
            onClick={() => {
              setDialogSaveError(null);
              setDialogMode("create");
            }}
            className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white transition-all hover:bg-[#2b1fa8]"
          >
            New Collection
          </button>
        ) : (
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold tracking-wide text-slate-600 uppercase">
            Read-only role
          </span>
        )}
      </div>

      <section className="space-y-4 rounded-xl border border-[#e5e3f1] bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-3 rounded-xl border border-[#e5e3f1] bg-[#fcfbff] p-3">
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Search
            <div className="relative">
              <span className="material-symbols-outlined pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-base text-[#9993b8]">
                search
              </span>
              <input
                type="search"
                value={nameSearch}
                onChange={(event) => setNameSearch(event.target.value)}
                placeholder="Search by name…"
                className="h-9 w-44 rounded-lg border border-[#d2cee6] bg-white pl-8 pr-3 text-sm font-medium text-[#2a2640] placeholder:font-normal placeholder:text-[#b0abc8] outline-none transition-[width] duration-200 focus:w-64 focus:ring-2 focus:ring-[#3525cd]/20"
              />
            </div>
          </label>
          <p className="text-sm text-[#68647b]">
            Showing{" "}
            <span className="font-semibold text-[#1b1b24]">
              {collections.length}
            </span>{" "}
            of{" "}
            <span className="font-semibold text-[#1b1b24]">{total}</span>{" "}
            collections
          </p>
        </div>

        {actionFeedback ? (
          <p
            role="status"
            className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
          >
            {actionFeedback}
            {actionRequestId ? ` (Trace ID: ${actionRequestId})` : ""}
          </p>
        ) : null}

        {!collectionsEnabled ? (
          <EmptyState
            title="Collections not available"
            description="Collections are not enabled in this deployment. Set NEXT_PUBLIC_FEATURE_COLLECTIONS_ENABLED=true to enable."
          />
        ) : null}

        {collectionsEnabled && collectionsQuery.isLoading ? (
          <LoadingState title="Loading collections…" />
        ) : null}

        {collectionsEnabled &&
        collectionsQuery.isError &&
        isEndpointNotFoundError(collectionsQuery.error) ? (
          <EmptyState
            title="Collections not yet available"
            description="The collections API is not deployed in this environment. Contact your administrator or check back later."
          />
        ) : null}

        {collectionsEnabled &&
        collectionsQuery.isError &&
        !isEndpointNotFoundError(collectionsQuery.error) &&
        listForbidden ? (
          <ForbiddenState
            compact
            title="Collections access denied"
            description="You do not have permission to view collections in this organization."
            requestId={extractRequestIdFromError(collectionsQuery.error)}
          />
        ) : null}

        {collectionsEnabled &&
        collectionsQuery.isError &&
        !isEndpointNotFoundError(collectionsQuery.error) &&
        !listForbidden ? (
          <ErrorState
            error={collectionsQuery.error}
            description={getApiErrorMessage(collectionsQuery.error)}
            onRetry={() => void collectionsQuery.refetch()}
          />
        ) : null}

        {collectionsEnabled &&
        !collectionsQuery.isLoading &&
        !collectionsQuery.isError &&
        collections.length === 0 ? (
          <EmptyState
            title={
              debouncedNameSearch
                ? `No collections match "${debouncedNameSearch}".`
                : "No collections yet."
            }
            description={
              debouncedNameSearch
                ? undefined
                : "Create your first collection to group documents for scoped retrieval and chat."
            }
            action={
              debouncedNameSearch ? (
                <button
                  type="button"
                  onClick={() => setNameSearch("")}
                  className="rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
                >
                  Clear search
                </button>
              ) : capabilities.canCreate ? (
                <button
                  type="button"
                  onClick={() => {
                    setDialogSaveError(null);
                    setDialogMode("create");
                  }}
                  className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
                >
                  New Collection
                </button>
              ) : undefined
            }
          />
        ) : null}

        {collectionsEnabled &&
        !collectionsQuery.isLoading &&
        !collectionsQuery.isError &&
        collections.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-[#e5e3f1]">
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse bg-white text-left">
                <thead className="border-b border-[#e5e3f1] bg-[#f8f7ff]">
                  <tr className="text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase">
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3 text-center">Documents</th>
                    <th className="px-4 py-3 text-center">Indexed</th>
                    <th className="px-4 py-3">Access</th>
                    <th className="px-4 py-3">Owner</th>
                    <th className="px-4 py-3">Updated</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#ece9f6]">
                  {collections.map((col) => {
                    const isSelected =
                      selectedCollectionId === col.collection_id;
                    const deleteBusy =
                      deleteMutation.isPending &&
                      deleteMutation.variables === col.collection_id;

                    return (
                      <tr
                        key={col.collection_id}
                        className={`group align-top transition-colors ${isSelected ? "bg-[#f5f3ff]" : "hover:bg-[#faf9ff]"}`}
                      >
                        <td className="px-4 py-3">
                          <button
                            type="button"
                            onClick={() =>
                              setSelectedCollectionId(
                                isSelected ? null : col.collection_id,
                              )
                            }
                            className="text-left"
                          >
                            <p className="font-semibold text-[#3525cd] hover:underline">
                              {col.name}
                            </p>
                            {col.description ? (
                              <p className="mt-0.5 max-w-xs truncate text-xs text-[#7a768f]">
                                {col.description}
                              </p>
                            ) : null}
                            <p className="text-xs text-[#b0abc8]">
                              {col.collection_id}
                            </p>
                          </button>
                        </td>
                        <td className="px-4 py-3 text-center font-mono text-sm text-[#1b1b24]">
                          {col.document_count}
                        </td>
                        <td className="px-4 py-3 text-center font-mono text-sm text-[#1b1b24]">
                          {col.indexed_count}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${accessPolicyBadgeClass(col.access_policy)}`}
                          >
                            {accessPolicyLabel(col.access_policy)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-[#68647b]">
                          {col.owner_email ?? col.owner_id}
                        </td>
                        <td className="px-4 py-3 text-sm text-[#68647b]">
                          {formatDate(col.updated_at)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end gap-1 opacity-40 transition-opacity group-hover:opacity-100">
                            <button
                              type="button"
                              aria-label="Inspect"
                              onClick={() =>
                                setSelectedCollectionId(
                                  isSelected ? null : col.collection_id,
                                )
                              }
                              className="rounded p-1 text-[#3525cd] hover:bg-[#3525cd]/10"
                            >
                              <span className="material-symbols-outlined text-[18px]">
                                visibility
                              </span>
                            </button>
                            {capabilities.canEdit ? (
                              <button
                                type="button"
                                aria-label="Edit"
                                onClick={() => {
                                  setDialogSaveError(null);
                                  setDialogMode({
                                    mode: "edit",
                                    collection:
                                      col as CollectionDetailResponse,
                                  });
                                }}
                                className="rounded p-1 text-blue-700 hover:bg-blue-100"
                              >
                                <span className="material-symbols-outlined text-[18px]">
                                  edit
                                </span>
                              </button>
                            ) : null}
                            {capabilities.canDelete ? (
                              <button
                                type="button"
                                aria-label="Delete"
                                disabled={deleteBusy}
                                onClick={() => handleDeleteCollection(col)}
                                className="rounded p-1 text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                              >
                                <span className="material-symbols-outlined text-[18px]">
                                  delete
                                </span>
                              </button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {totalPages > 1 ? (
              <div className="flex items-center justify-between gap-3 border-t border-[#e5e3f1] bg-[#fcfbff] px-4 py-3">
                <button
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() =>
                    setOffset((prev) =>
                      Math.max(0, prev - COLLECTIONS_PAGE_SIZE),
                    )
                  }
                  className="flex items-center gap-1 rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <span
                    aria-hidden="true"
                    className="material-symbols-outlined text-[18px]"
                  >
                    chevron_left
                  </span>
                  Previous
                </button>
                <p className="text-sm text-[#68647b]">
                  Page {currentPage} of {totalPages}
                </p>
                <button
                  type="button"
                  disabled={currentPage >= totalPages}
                  onClick={() =>
                    setOffset((prev) => prev + COLLECTIONS_PAGE_SIZE)
                  }
                  className="flex items-center gap-1 rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Next
                  <span
                    aria-hidden="true"
                    className="material-symbols-outlined text-[18px]"
                  >
                    chevron_right
                  </span>
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {selectedCollectionId ? (
        <CollectionDetailPanel
          key={selectedCollectionId}
          collectionId={selectedCollectionId}
          capabilities={capabilities}
          onClose={() => setSelectedCollectionId(null)}
          onEdit={(collection) => {
            setDialogSaveError(null);
            setDialogMode({ mode: "edit", collection });
          }}
        />
      ) : null}

      {dialogMode === "create" ? (
        <CollectionDialog
          title="New Collection"
          initial={DEFAULT_FORM}
          saving={createMutation.isPending}
          saveError={dialogSaveError}
          onSave={handleCreateSave}
          onClose={() => {
            setDialogMode(null);
            setDialogSaveError(null);
          }}
        />
      ) : dialogMode !== null ? (
        <CollectionDialog
          title="Edit Collection"
          initial={{
            name: dialogMode.collection.name,
            description: dialogMode.collection.description ?? "",
            access_policy: dialogMode.collection.access_policy,
          }}
          saving={updateMutation.isPending}
          saveError={dialogSaveError}
          onSave={handleEditSave}
          onClose={() => {
            setDialogMode(null);
            setDialogSaveError(null);
          }}
        />
      ) : null}
    </section>
  );
}
