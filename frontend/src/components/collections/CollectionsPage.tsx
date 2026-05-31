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
import { getTeamCapabilities, listTeamMembers, type TeamMember } from "@/lib/api/team";

const COLLECTIONS_PAGE_SIZE = 20;
const COLLECTION_DOCS_PAGE_SIZE = 20;

const CARD_ICONS = [
  "inventory_2", "account_balance", "book_2", "layers",
  "hub", "category", "psychology", "school", "insights",
  "folder_shared", "gavel", "support_agent", "science",
  "engineering", "manage_accounts",
];

function pickIcon(id: string): string {
  let h = 0;
  for (const c of id) h = (h + c.charCodeAt(0)) % CARD_ICONS.length;
  return CARD_ICONS[h]!;
}

type CollectionCapabilities = {
  canCreate: boolean;
  canEdit: boolean;
  canDelete: boolean;
  canManageDocuments: boolean;
  canManagePolicy: boolean;
};

function resolveCollectionCapabilities(role: AppRole | undefined): CollectionCapabilities {
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

function formatRelativeDate(value: string): string {
  try {
    const diff = Date.now() - new Date(value).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 2) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  } catch {
    return "";
  }
}

function accessPolicyLabel(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide": return "Org-wide";
    case "admin_only": return "Admin-only";
    case "selected_roles": return "Selected roles";
    case "selected_members": return "Selected members";
    default: return policy;
  }
}

function accessPolicyBadgeClass(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide": return "bg-green-50 text-green-700 border-green-200";
    case "admin_only": return "bg-amber-50 text-amber-800 border-amber-200";
    case "selected_roles": return "bg-blue-50 text-blue-700 border-blue-200";
    case "selected_members": return "bg-violet-50 text-violet-700 border-violet-200";
    default: return "bg-slate-50 text-slate-600 border-slate-200";
  }
}

function accessPolicyDescription(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide": return "All organization members can view and query this collection.";
    case "admin_only": return "Only organization owners and admins can access this collection.";
    case "selected_roles": return "Only members with the specified roles can access this collection.";
    case "selected_members": return "Only explicitly listed members can access this collection.";
    default: return "";
  }
}

function accessPolicyIcon(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide": return "public";
    case "admin_only": return "admin_panel_settings";
    case "selected_roles": return "group";
    case "selected_members": return "person_check";
    default: return "lock";
  }
}

const GRANTABLE_ROLES: Array<{ value: string; label: string }> = [
  { value: "member", label: "Member" },
  { value: "viewer", label: "Viewer" },
];

// ── Summary metrics ─────────────────────────────────────────────────────────

function SummaryMetrics({
  total,
  totalDocs,
  indexedDocs,
  restrictedCount,
}: {
  total: number;
  totalDocs: number;
  indexedDocs: number;
  restrictedCount: number;
}) {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {[
        { icon: "folder", color: "bg-[#3525cd]/10 text-[#3525cd]", label: "Total Collections", value: total },
        { icon: "description", color: "bg-slate-100 text-slate-600", label: "Visible Docs", value: totalDocs.toLocaleString() },
        { icon: "check_circle", color: "bg-green-50 text-green-700", label: "Indexed Docs", value: indexedDocs.toLocaleString() },
        { icon: "lock", color: "bg-amber-50 text-amber-700", label: "Restricted", value: restrictedCount },
      ].map(({ icon, color, label, value }) => (
        <div key={label} className="bg-white border border-[#e4e1ee] rounded-2xl p-5 flex items-center gap-4">
          <div className={`w-12 h-12 rounded-xl ${color} flex items-center justify-center`}>
            <span className="material-symbols-outlined">{icon}</span>
          </div>
          <div>
            <p className="text-[#6a6780] text-[11px] font-semibold tracking-wider uppercase">{label}</p>
            <h3 className="text-2xl font-bold text-[#1b1b24]">{value}</h3>
          </div>
        </div>
      ))}
    </section>
  );
}

// ── Collection card ──────────────────────────────────────────────────────────

function CollectionCard({
  collection: col,
  isSelected,
  capabilities,
  onSelect,
  onEdit,
  onDelete,
  isDeleting,
}: {
  collection: CollectionListItemResponse;
  isSelected: boolean;
  capabilities: CollectionCapabilities;
  onSelect: () => void;
  onEdit: (col: CollectionListItemResponse) => void;
  onDelete: (col: CollectionListItemResponse) => void;
  isDeleting: boolean;
}) {
  const icon = pickIcon(col.collection_id);
  const progress =
    col.document_count > 0
      ? Math.round((col.indexed_count / col.document_count) * 100)
      : 0;
  const progressColor =
    progress === 100
      ? "bg-green-500"
      : progress >= 80
        ? "bg-[#3525cd]"
        : "bg-amber-500";

  return (
    <div
      className={`bg-white border rounded-2xl p-6 hover:border-[#3525cd]/40 hover:shadow-xl hover:shadow-[#3525cd]/5 transition-all cursor-pointer group flex flex-col h-full ${
        isSelected
          ? "border-[#3525cd]/60 shadow-lg shadow-[#3525cd]/10"
          : "border-[#e4e1ee]"
      }`}
      onClick={onSelect}
    >
      <div className="flex justify-between items-start mb-4">
        <div
          className={`p-2 rounded-xl transition-colors ${
            isSelected
              ? "bg-[#3525cd] text-white"
              : "bg-[#f0ecf9] text-[#3525cd] group-hover:bg-[#3525cd] group-hover:text-white"
          }`}
        >
          <span
            className="material-symbols-outlined"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            {icon}
          </span>
        </div>
        <span
          className={`px-2 py-0.5 rounded-full text-[11px] font-bold border uppercase tracking-tight ${accessPolicyBadgeClass(col.access_policy)}`}
        >
          {accessPolicyLabel(col.access_policy)}
        </span>
      </div>

      <h4 className="text-lg font-semibold text-[#1b1b24] mb-1">{col.name}</h4>
      <p className="text-[#464555] text-sm line-clamp-2 mb-5 flex-1 min-h-[2.5rem]">
        {col.description ?? (
          <span className="text-[#b0abc8] italic">No description</span>
        )}
      </p>

      <div className="space-y-3">
        <div>
          <div className="flex justify-between text-[12px] mb-1.5">
            <span className="text-[#6a6780]">Indexing Progress</span>
            <span className="font-bold text-[#1b1b24]">
              {progress}% ({col.indexed_count}/{col.document_count})
            </span>
          </div>
          <div className="w-full bg-[#f0ecf9] h-1.5 rounded-full overflow-hidden">
            <div
              className={`${progressColor} h-full rounded-full`}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        <div className="flex items-center justify-between pt-3 border-t border-[#e4e1ee]/60">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-5 h-5 rounded-full bg-[#e4e1ee] flex items-center justify-center shrink-0">
              <span className="material-symbols-outlined text-[12px] text-[#6a6780]">
                person
              </span>
            </div>
            <span className="text-[12px] text-[#6a6780] font-medium truncate">
              {col.owner_email ?? col.owner_id}
            </span>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <span className="text-[11px] text-[#b0abc8]">
              {formatRelativeDate(col.updated_at)}
            </span>
            {capabilities.canEdit ? (
              <button
                type="button"
                aria-label="Edit"
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit(col);
                }}
                className="ml-1 p-1 rounded text-[#6a6780] hover:text-[#3525cd] hover:bg-[#f0ecf9] opacity-0 group-hover:opacity-100 transition-all"
              >
                <span className="material-symbols-outlined text-[16px]">edit</span>
              </button>
            ) : null}
            {capabilities.canDelete ? (
              <button
                type="button"
                aria-label="Delete"
                disabled={isDeleting}
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(col);
                }}
                className="p-1 rounded text-[#6a6780] hover:text-rose-600 hover:bg-rose-50 opacity-0 group-hover:opacity-100 transition-all disabled:opacity-40"
              >
                <span className="material-symbols-outlined text-[16px]">delete</span>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function NewCollectionCard({ onCreate }: { onCreate: () => void }) {
  return (
    <div
      className="bg-white border-2 border-dashed border-[#e4e1ee] rounded-2xl p-6 flex flex-col items-center justify-center text-center hover:bg-[#f5f3ff]/50 hover:border-[#3525cd]/30 transition-all group cursor-pointer"
      onClick={onCreate}
    >
      <div className="w-12 h-12 rounded-full bg-[#f0ecf9] flex items-center justify-center text-[#6a6780] mb-4 group-hover:scale-110 transition-transform">
        <span className="material-symbols-outlined text-[32px]">add</span>
      </div>
      <h4 className="text-base font-bold text-[#1b1b24] mb-1">Create New Collection</h4>
      <p className="text-[12px] text-[#6a6780] px-4">
        Connect new data sources and start building your custom RAG knowledge base.
      </p>
    </div>
  );
}

// ── Policy editor ────────────────────────────────────────────────────────────

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

  useEffect(() => {
    if (!policyQuery.data || isDirty) return;
    const data = policyQuery.data;
    setPolicy(data.access_policy);
    setRoleGrants(new Set(data.grants.filter((g) => g.grantee_type === "role").map((g) => g.grantee_value)));
    setMemberGrants(new Set(data.grants.filter((g) => g.grantee_type === "member").map((g) => g.grantee_value)));
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
    if (policy === "selected_roles")
      return Array.from(roleGrants).map((v) => ({ grantee_type: "role" as const, grantee_value: v }));
    if (policy === "selected_members")
      return Array.from(memberGrants).map((v) => ({ grantee_type: "member" as const, grantee_value: v }));
    return [];
  }

  function handlePolicyChange(next: CollectionAccessPolicy) {
    if ((policyQuery.data?.access_policy ?? "org_wide") === "org_wide" && next !== "org_wide") {
      setShowWarning(true);
    }
    setPolicy(next);
    setIsDirty(true);
  }

  function handleDiscard() {
    setIsDirty(false);
    setShowWarning(false);
    setSaveError(null);
    if (policyQuery.data) {
      setPolicy(policyQuery.data.access_policy);
      setRoleGrants(new Set(policyQuery.data.grants.filter((g) => g.grantee_type === "role").map((g) => g.grantee_value)));
      setMemberGrants(new Set(policyQuery.data.grants.filter((g) => g.grantee_type === "member").map((g) => g.grantee_value)));
    }
  }

  if (policyQuery.isLoading) return <LoadingState compact title="Loading access policy…" />;
  if (policyQuery.isError) {
    if (isForbiddenError(policyQuery.error))
      return <ForbiddenState compact title="Policy access denied" description="You do not have permission to manage this collection's access policy." requestId={extractRequestIdFromError(policyQuery.error)} />;
    return <ErrorState compact error={policyQuery.error} description={getApiErrorMessage(policyQuery.error)} onRetry={() => void policyQuery.refetch()} />;
  }

  const effectivePolicy = policy ?? policyQuery.data?.access_policy ?? "org_wide";
  const members: TeamMember[] = membersQuery.data?.items ?? [];
  const eligibleMembers = members.filter((m) => m.role !== "owner" && m.role !== "admin" && m.user_id);

  return (
    <div className="space-y-4">
      {showWarning ? (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5">
          <span className="material-symbols-outlined mt-0.5 shrink-0 text-base text-amber-700">warning</span>
          <p className="text-xs text-amber-800">
            Restricting <strong>{collectionName}</strong> will remove access for members who currently have it.
          </p>
        </div>
      ) : null}

      <div>
        <label className="mb-1.5 block text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">Mode</label>
        <select
          value={effectivePolicy}
          onChange={(e) => handlePolicyChange(e.target.value as CollectionAccessPolicy)}
          className="h-9 w-full rounded-xl border border-[#d2cee6] bg-white px-3 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
        >
          <option value="org_wide">Org-wide — all members</option>
          <option value="admin_only">Admin-only — owners and admins</option>
          <option value="selected_roles">Selected roles</option>
          <option value="selected_members">Selected members</option>
        </select>
        <p className="mt-1 text-[11px] text-[#7a768f]">{accessPolicyDescription(effectivePolicy)}</p>
      </div>

      {effectivePolicy === "selected_roles" ? (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">Roles with access</p>
          <p className="text-[11px] text-[#7a768f]">Owners and admins always have access.</p>
          {GRANTABLE_ROLES.map(({ value, label }) => (
            <label key={value} className="flex cursor-pointer items-center gap-3 rounded-xl border border-[#e4e1ee] bg-white px-3 py-2 hover:bg-[#f5f3ff]">
              <input type="checkbox" checked={roleGrants.has(value)} onChange={() => { setRoleGrants((prev) => { const n = new Set(prev); n.has(value) ? n.delete(value) : n.add(value); return n; }); setIsDirty(true); }} className="accent-[#3525cd]" />
              <span className="text-sm font-semibold text-[#2a2640]">{label}</span>
            </label>
          ))}
          {roleGrants.size === 0 ? <p className="text-[11px] text-amber-700">No roles selected — only admins will have access.</p> : null}
        </div>
      ) : null}

      {effectivePolicy === "selected_members" ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">Members with access</p>
          <p className="text-[11px] text-[#7a768f]">Owners and admins always have access.</p>
          {!teamCapabilities.listMembersEnabled ? (
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
              Configure <code>NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL</code> to enable the member picker.
            </p>
          ) : membersQuery.isLoading ? (
            <LoadingState compact title="Loading members…" />
          ) : eligibleMembers.length === 0 ? (
            <EmptyState compact title="No eligible members." description="All members are admins who already have access." />
          ) : (
            <ul className="max-h-44 space-y-0.5 overflow-auto rounded-xl border border-[#e4e1ee] bg-white p-2">
              {eligibleMembers.map((m) => (
                <li key={m.user_id}>
                  <label className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-[#f5f3ff]">
                    <input type="checkbox" checked={memberGrants.has(m.user_id!)} onChange={() => { setMemberGrants((prev) => { const n = new Set(prev); n.has(m.user_id!) ? n.delete(m.user_id!) : n.add(m.user_id!); return n; }); setIsDirty(true); }} className="accent-[#3525cd]" />
                    <span className="flex-1">
                      <span className="block text-sm font-semibold text-[#2a2640]">{m.name}</span>
                      <span className="block text-[11px] text-[#68647b]">{m.email}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          {memberGrants.size === 0 && teamCapabilities.listMembersEnabled ? <p className="text-[11px] text-amber-700">No members selected — only admins will have access.</p> : null}
        </div>
      ) : null}

      {!isDirty && policyQuery.data ? (
        <p className="text-[11px] text-[#68647b]">
          {effectivePolicy === "org_wide" && "All organization members currently have access."}
          {effectivePolicy === "admin_only" && "Only owners and admins have access."}
          {effectivePolicy === "selected_roles" && (() => {
            const roles = policyQuery.data.grants.filter((g) => g.grantee_type === "role").map((g) => g.grantee_value);
            return roles.length > 0 ? `Granted to: admins, ${roles.join(", ")}s.` : "Only admins have access.";
          })()}
          {effectivePolicy === "selected_members" && (() => {
            const count = policyQuery.data.grants.filter((g) => g.grantee_type === "member").length;
            return count === 0 ? "No members explicitly granted — only admins have access." : `${count} member${count === 1 ? "" : "s"} explicitly granted access.`;
          })()}
        </p>
      ) : null}

      {saveError ? <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{saveError}</p> : null}

      {isDirty ? (
        <div className="flex gap-2">
          <button type="button" onClick={handleDiscard} disabled={saveMutation.isPending} className="flex-1 rounded-xl border border-[#d2cee6] py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff] disabled:opacity-60">
            Discard
          </button>
          <button type="button" onClick={() => { if (policy) saveMutation.mutate({ access_policy: policy, grants: buildGrants() }); }} disabled={saveMutation.isPending} className="flex-1 rounded-xl bg-[#3525cd] py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:opacity-60">
            {saveMutation.isPending ? "Saving…" : "Save policy"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

// ── Collection detail drawer ─────────────────────────────────────────────────

function CollectionDetailDrawer({
  collectionId,
  capabilities,
  onClose,
  onEdit,
}: {
  collectionId: string;
  capabilities: CollectionCapabilities;
  onClose: () => void;
  onEdit: (collection: CollectionDetailResponse) => void;
}) {
  const queryClient = useQueryClient();
  const [docsOffset, setDocsOffset] = useState(0);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  const detailQuery = useQuery({
    queryKey: queryKeys.collections.detail(collectionId),
    queryFn: () => getCollection(collectionId),
  });

  const docsParams = { limit: COLLECTION_DOCS_PAGE_SIZE, offset: docsOffset };
  const docsQuery = useQuery({
    queryKey: queryKeys.collections.documents(collectionId, docsParams),
    queryFn: () => listCollectionDocuments(collectionId, docsParams),
  });

  const removeDocMutation = useMutation({
    mutationFn: (documentId: string) => removeDocumentFromCollection(collectionId, documentId),
    onSuccess: async () => {
      setActionFeedback("Document removed from collection.");
      await invalidateAfterMutation(queryClient, "collection.document.remove");
    },
    onError: (error) => { setActionFeedback(getApiErrorMessage(error)); },
  });

  const detail = detailQuery.data;
  const docs = docsQuery.data;
  const progress = detail && detail.document_count > 0 ? Math.round((detail.indexed_count / detail.document_count) * 100) : 0;
  const canGoNext = Boolean(docs) && docsOffset + COLLECTION_DOCS_PAGE_SIZE < (docs?.total ?? 0);
  const canGoPrev = docsOffset > 0;

  const fileIcon = (type: string) =>
    type === "pdf" ? "picture_as_pdf" : type === "docx" ? "article" : "description";

  return (
    <div className="fixed top-0 right-0 h-screen w-[480px] bg-white z-50 shadow-2xl border-l border-[#e4e1ee] flex flex-col">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[#e4e1ee] flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-[#f0ecf9] transition-colors shrink-0"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
          <h3 className="text-base font-semibold text-[#1b1b24] truncate">
            {detail?.name ?? "Collection Details"}
          </h3>
        </div>
        {detail && capabilities.canEdit ? (
          <button
            type="button"
            onClick={() => onEdit(detail)}
            className="ml-2 shrink-0 px-4 py-1.5 rounded-lg text-sm font-semibold border border-[#e4e1ee] hover:bg-[#f0ecf9] transition-colors text-[#2a2640]"
          >
            Edit
          </button>
        ) : null}
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6" style={{ scrollbarWidth: "thin" }}>
        {detailQuery.isLoading ? (
          <LoadingState title="Loading collection…" />
        ) : detailQuery.isError ? (
          isForbiddenError(detailQuery.error) ? (
            <ForbiddenState compact title="Access denied" description="You do not have permission to view this collection." requestId={extractRequestIdFromError(detailQuery.error)} />
          ) : (
            <ErrorState compact error={detailQuery.error} description={getApiErrorMessage(detailQuery.error)} onRetry={() => void detailQuery.refetch()} />
          )
        ) : detail ? (
          <>
            {/* Hero */}
            <section>
              <div className="flex gap-5 p-5 bg-[#f5f3ff] rounded-2xl">
                <div className="w-20 h-20 rounded-2xl bg-[#3525cd] flex items-center justify-center text-white shrink-0">
                  <span className="material-symbols-outlined text-[40px]" style={{ fontVariationSettings: "'FILL' 1" }}>
                    {pickIcon(collectionId)}
                  </span>
                </div>
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold text-[#6a6780] uppercase tracking-wider mb-1">Collection Metadata</p>
                  <h4 className="text-xl font-bold text-[#1b1b24] leading-tight">{detail.name}</h4>
                  {detail.description ? (
                    <p className="mt-1 text-sm text-[#6a6780] line-clamp-2">{detail.description}</p>
                  ) : null}
                  <div className="flex items-center gap-4 mt-2">
                    <div className="flex items-center gap-1 text-[12px] text-[#6a6780]">
                      <span className="material-symbols-outlined text-[16px]">database</span>
                      {detail.document_count} Docs
                    </div>
                    <div className="flex items-center gap-1 text-[12px] text-[#6a6780]">
                      <span className="material-symbols-outlined text-[16px]">check_circle</span>
                      {detail.indexed_count} Indexed
                    </div>
                  </div>
                </div>
              </div>
            </section>

            {/* Indexing health */}
            <section className="space-y-3">
              <h5 className="text-[11px] font-semibold text-[#6a6780] uppercase tracking-wider">Indexing Health</h5>
              <div className="grid grid-cols-2 gap-3">
                <div className="p-4 rounded-xl border border-[#e4e1ee] bg-white">
                  <p className="text-[11px] text-[#6a6780] mb-1">Completion</p>
                  <p className={`text-xl font-bold ${progress === 100 ? "text-green-600" : progress >= 80 ? "text-[#3525cd]" : "text-amber-600"}`}>
                    {progress}%
                  </p>
                </div>
                <div className="p-4 rounded-xl border border-[#e4e1ee] bg-white">
                  <p className="text-[11px] text-[#6a6780] mb-1">Owner</p>
                  <p className="text-sm font-bold text-[#1b1b24] truncate">{detail.owner_email ?? "—"}</p>
                </div>
              </div>
              <div className="w-full bg-[#f0ecf9] h-1.5 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${progress === 100 ? "bg-green-500" : progress >= 80 ? "bg-[#3525cd]" : "bg-amber-500"}`}
                  style={{ width: `${progress}%` }}
                />
              </div>
            </section>

            {/* Access policy */}
            <section className="space-y-3">
              <h5 className="text-[11px] font-semibold text-[#6a6780] uppercase tracking-wider">Access Policy</h5>
              {capabilities.canManagePolicy ? (
                <PolicyEditor collectionId={collectionId} collectionName={detail.name} />
              ) : (
                <div className="bg-[#f5f3ff] border border-[#3525cd]/20 rounded-xl p-4 flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-[#3525cd]/10 flex items-center justify-center text-[#3525cd] shrink-0">
                    <span className="material-symbols-outlined">{accessPolicyIcon(detail.access_policy)}</span>
                  </div>
                  <div>
                    <p className="text-sm font-bold text-[#1b1b24]">{accessPolicyLabel(detail.access_policy)}</p>
                    <p className="text-[11px] text-[#6a6780]">{accessPolicyDescription(detail.access_policy)}</p>
                  </div>
                </div>
              )}
            </section>

            {/* Documents */}
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <h5 className="text-[11px] font-semibold text-[#6a6780] uppercase tracking-wider">Indexed Documents</h5>
                <span className="text-[12px] text-[#6a6780]">{docs?.total ?? 0} total</span>
              </div>

              {actionFeedback ? (
                <p role="status" className="text-sm text-[#3f3778] bg-[#f3f1ff] rounded-xl px-3 py-2 border border-[#ddd7f6]">
                  {actionFeedback}
                </p>
              ) : null}

              {docsQuery.isLoading ? (
                <LoadingState compact title="Loading documents…" />
              ) : docsQuery.isError ? (
                <ErrorState compact error={docsQuery.error} description={getApiErrorMessage(docsQuery.error)} onRetry={() => void docsQuery.refetch()} />
              ) : docs && docs.items.length === 0 ? (
                <EmptyState compact title="No documents yet." description="Add documents from the Documents page." />
              ) : docs && docs.items.length > 0 ? (
                <div className="space-y-0.5">
                  {docs.items.map((doc) => (
                    <div key={doc.document_id} className="flex items-center justify-between p-2 hover:bg-[#f5f3ff] rounded-xl transition-colors border-b border-[#e4e1ee]/40 last:border-0">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="material-symbols-outlined text-[#6a6780] text-[20px] shrink-0">
                          {fileIcon(doc.file_type)}
                        </span>
                        <Link
                          href={`/documents/${encodeURIComponent(doc.document_id)}`}
                          className="text-sm font-medium text-[#1b1b24] hover:text-[#3525cd] truncate"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {doc.filename}
                        </Link>
                      </div>
                      <div className="flex items-center gap-2 shrink-0 ml-2">
                        <span className={`text-[11px] font-bold ${doc.status === "indexed" ? "text-green-600" : doc.status === "processing" ? "text-[#3525cd] animate-pulse" : "text-[#6a6780]"}`}>
                          {doc.status === "indexed" ? "Ready" : doc.status === "processing" ? "Indexing…" : doc.status}
                        </span>
                        {capabilities.canManageDocuments ? (
                          <button
                            type="button"
                            aria-label="Remove"
                            disabled={removeDocMutation.isPending}
                            onClick={() => {
                              if (window.confirm(`Remove "${doc.filename}" from this collection?`)) {
                                removeDocMutation.mutate(doc.document_id);
                              }
                            }}
                            className="p-1 rounded text-[#b0abc8] hover:text-rose-600 hover:bg-rose-50 transition-colors disabled:opacity-40"
                          >
                            <span className="material-symbols-outlined text-[16px]">remove_circle_outline</span>
                          </button>
                        ) : null}
                      </div>
                    </div>
                  ))}

                  {canGoPrev || canGoNext ? (
                    <div className="flex items-center justify-between pt-2">
                      <button type="button" disabled={!canGoPrev} onClick={() => setDocsOffset((p) => Math.max(0, p - COLLECTION_DOCS_PAGE_SIZE))} className="px-3 py-1 rounded-lg border border-[#e4e1ee] text-xs font-semibold text-[#3e376f] disabled:opacity-40">
                        Previous
                      </button>
                      <span className="text-xs text-[#6a6780]">{docs.items.length} of {docs.total}</span>
                      <button type="button" disabled={!canGoNext} onClick={() => setDocsOffset((p) => p + COLLECTION_DOCS_PAGE_SIZE)} className="px-3 py-1 rounded-lg border border-[#e4e1ee] text-xs font-semibold text-[#3e376f] disabled:opacity-40">
                        Next
                      </button>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>
          </>
        ) : null}
      </div>

      {/* Footer */}
      {detail ? (
        <div className="p-5 bg-[#f5f3ff] border-t border-[#e4e1ee] shrink-0">
          <Link
            href={`/chat?collection_id=${encodeURIComponent(collectionId)}`}
            className="w-full bg-[#3525cd] text-white py-3 rounded-xl font-bold flex items-center justify-center gap-2 hover:bg-[#2b1fa8] transition-all"
          >
            <span className="material-symbols-outlined">chat_bubble</span>
            Open Chat for this Collection
          </Link>
        </div>
      ) : null}
    </div>
  );
}

// ── Collection form dialog ───────────────────────────────────────────────────

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

type CollectionFormErrors = { name?: string };

function validateCollectionForm(form: CollectionFormState): CollectionFormErrors {
  const errors: CollectionFormErrors = {};
  if (!form.name.trim()) errors.name = "Name is required.";
  else if (form.name.trim().length > 120) errors.name = "Name must be 120 characters or fewer.";
  return errors;
}

function CollectionDialog({
  title,
  initial,
  saving,
  saveError,
  onSave,
  onClose,
}: {
  title: string;
  initial: CollectionFormState;
  saving: boolean;
  saveError: string | null;
  onSave: (form: CollectionFormState) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<CollectionFormState>(initial);
  const [fieldErrors, setFieldErrors] = useState<CollectionFormErrors>({});
  const nameRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => { nameRef.current?.focus(); }, []);

  function handleSubmit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validateCollectionForm(form);
    if (Object.keys(errors).length > 0) { setFieldErrors(errors); return; }
    setFieldErrors({});
    onSave(form);
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#17172a]/40 px-4" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100">Cancel</button>
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
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
              maxLength={120}
              placeholder="e.g. Engineering Handbook"
              className="h-9 w-full rounded-xl border border-[#d2cee6] bg-white px-3 text-sm font-medium text-[#2a2640] placeholder:font-normal placeholder:text-[#b0abc8] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            />
            {fieldErrors.name ? <p className="mt-1 text-xs text-rose-700">{fieldErrors.name}</p> : null}
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
              rows={3}
              maxLength={500}
              placeholder="Optional: describe this collection's purpose or contents."
              className="w-full rounded-xl border border-[#d2cee6] bg-white px-3 py-2 text-sm font-medium text-[#2a2640] placeholder:font-normal placeholder:text-[#b0abc8] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">Access Policy</label>
            <select
              value={form.access_policy}
              onChange={(e) => setForm((p) => ({ ...p, access_policy: e.target.value as CollectionAccessPolicy }))}
              className="h-9 w-full rounded-xl border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            >
              <option value="org_wide">Org-wide — all members</option>
              <option value="admin_only">Admin-only</option>
              <option value="selected_roles">Selected roles</option>
              <option value="selected_members">Selected members</option>
            </select>
            <p className="mt-1 text-xs text-[#7a768f]">{accessPolicyDescription(form.access_policy)}</p>
          </div>

          {saveError ? <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{saveError}</p> : null}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="rounded-xl border border-[#d2cee6] bg-white px-4 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]">Cancel</button>
            <button type="submit" disabled={saving} className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Assign collections dialog (exported) ─────────────────────────────────────

export function AssignCollectionsDialog({
  collectionList,
  loadingCollections,
  documentName,
  currentCollectionIds,
  saving,
  saveError,
  onSave,
  onClose,
}: {
  collectionList: CollectionListItemResponse[];
  loadingCollections: boolean;
  documentName: string;
  currentCollectionIds: string[];
  saving: boolean;
  saveError: string | null;
  onSave: (collectionIds: string[]) => void;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(currentCollectionIds));
  const initializedRef = useRef(false);

  useEffect(() => {
    if (!loadingCollections && !initializedRef.current) {
      initializedRef.current = true;
      setSelected(new Set(currentCollectionIds));
    }
  }, [loadingCollections, currentCollectionIds]);

  function toggle(id: string) {
    setSelected((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#17172a]/40 px-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">Assign to Collections</h2>
            <p className="text-xs text-[#68647b]">{documentName}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100">Cancel</button>
        </div>

        {loadingCollections ? (
          <LoadingState compact title="Loading collections…" />
        ) : collectionList.length === 0 ? (
          <EmptyState compact title="No collections found." description="Create a collection first from the Collections page." />
        ) : (
          <ul className="max-h-64 space-y-1 overflow-auto">
            {collectionList.map((col) => (
              <li key={col.collection_id}>
                <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-[#e5e3f1] px-3 py-2 hover:bg-[#f5f3ff]">
                  <input type="checkbox" checked={selected.has(col.collection_id)} onChange={() => toggle(col.collection_id)} className="accent-[#3525cd]" />
                  <span className="flex-1">
                    <span className="block text-sm font-semibold text-[#2a2640]">{col.name}</span>
                    <span className="block text-xs text-[#68647b]">
                      {col.document_count} doc{col.document_count !== 1 ? "s" : ""}{" "}·{" "}
                      <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase border ${accessPolicyBadgeClass(col.access_policy)}`}>
                        {accessPolicyLabel(col.access_policy)}
                      </span>
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}

        {saveError ? <p className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{saveError}</p> : null}

        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-xl border border-[#d2cee6] bg-white px-4 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]">Cancel</button>
          <button type="button" disabled={saving || loadingCollections} onClick={() => onSave(Array.from(selected))} className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Collections page ─────────────────────────────────────────────────────────

export function CollectionsPage() {
  const queryClient = useQueryClient();
  const { state } = useAuthSession();
  const capabilities = resolveCollectionCapabilities(state.session?.role);
  const collectionsEnabled = getFrontendRuntimeConfig().features.collectionsEnabled;

  const [offset, setOffset] = useState(0);
  const [nameSearch, setNameSearch] = useState("");
  const [debouncedNameSearch, setDebouncedNameSearch] = useState("");
  const [accessFilter, setAccessFilter] = useState<CollectionAccessPolicy | "all">("all");
  const [sortBy, setSortBy] = useState<"updated" | "name" | "docs">("updated");
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null);
  const [dialogMode, setDialogMode] = useState<"create" | { mode: "edit"; collection: CollectionDetailResponse } | null>(null);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);
  const [dialogSaveError, setDialogSaveError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => { setDebouncedNameSearch(nameSearch); setOffset(0); }, 300);
    return () => clearTimeout(t);
  }, [nameSearch]);

  const listQueryOptions = useMemo(
    () => ({ limit: COLLECTIONS_PAGE_SIZE, offset, name_query: debouncedNameSearch || undefined }),
    [offset, debouncedNameSearch],
  );

  const collectionsQuery = useQuery({
    queryKey: queryKeys.collections.list(listQueryOptions),
    queryFn: () => listCollections(listQueryOptions),
    enabled: collectionsEnabled,
    retry: (failureCount, error) => !isEndpointNotFoundError(error) && failureCount < 2,
  });

  const allCollections = collectionsQuery.data?.items ?? [];
  const total = collectionsQuery.data?.total ?? 0;
  const listForbidden = isForbiddenError(collectionsQuery.error);

  // Client-side filter + sort
  const visibleCollections = useMemo(() => {
    let list = accessFilter === "all" ? allCollections : allCollections.filter((c) => c.access_policy === accessFilter);
    if (sortBy === "name") list = [...list].sort((a, b) => a.name.localeCompare(b.name));
    else if (sortBy === "docs") list = [...list].sort((a, b) => b.document_count - a.document_count);
    return list;
  }, [allCollections, accessFilter, sortBy]);

  // Summary metrics
  const totalDocs = allCollections.reduce((s, c) => s + c.document_count, 0);
  const indexedDocs = allCollections.reduce((s, c) => s + c.indexed_count, 0);
  const restrictedCount = allCollections.filter((c) => c.access_policy !== "org_wide").length;

  const totalPages = Math.max(1, Math.ceil(Math.max(total, 1) / COLLECTIONS_PAGE_SIZE));
  const currentPage = Math.floor(offset / COLLECTIONS_PAGE_SIZE) + 1;

  const createMutation = useMutation({
    mutationFn: (form: CollectionFormState) =>
      createCollection({ name: form.name.trim(), description: form.description.trim() || null, access_policy: form.access_policy }),
    onSuccess: async (result) => {
      setDialogMode(null); setDialogSaveError(null);
      setActionFeedback(`Collection "${result.name}" created.`); setActionRequestId(null);
      setSelectedCollectionId(result.collection_id);
      await invalidateAfterMutation(queryClient, "collection.create");
    },
    onError: (error) => { setDialogSaveError(getApiErrorMessage(error)); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ collectionId, form }: { collectionId: string; form: CollectionFormState }) =>
      updateCollection(collectionId, { name: form.name.trim(), description: form.description.trim() || null, access_policy: form.access_policy }),
    onSuccess: async (result) => {
      setDialogMode(null); setDialogSaveError(null);
      setActionFeedback(`Collection "${result.name}" updated.`); setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "collection.update");
    },
    onError: (error) => { setDialogSaveError(getApiErrorMessage(error)); },
  });

  const deleteMutation = useMutation({
    mutationFn: (collectionId: string) => deleteCollection(collectionId),
    onSuccess: async (_, collectionId) => {
      if (selectedCollectionId === collectionId) setSelectedCollectionId(null);
      setActionFeedback("Collection deleted."); setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "collection.delete");
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  function handleCreateSave(form: CollectionFormState) { setDialogSaveError(null); createMutation.mutate(form); }
  function handleEditSave(form: CollectionFormState) {
    if (!dialogMode || dialogMode === "create") return;
    setDialogSaveError(null);
    updateMutation.mutate({ collectionId: dialogMode.collection.collection_id, form });
  }
  function handleDeleteCollection(col: CollectionListItemResponse) {
    if (!window.confirm(`Delete collection "${col.name}"? Documents will not be deleted.`)) return;
    deleteMutation.mutate(col.collection_id);
  }

  const isLoading = collectionsEnabled && collectionsQuery.isLoading;
  const isError = collectionsEnabled && collectionsQuery.isError;
  const showGrid = collectionsEnabled && !isLoading && !isError;

  return (
    <>
      <section className="space-y-6 px-4 py-6 lg:px-8 lg:py-8 min-h-screen">
        {/* Page header */}
        <section>
          <span className="text-[#3525cd] text-[11px] font-semibold tracking-widest uppercase mb-1 block">
            Knowledge base
          </span>
          <h2 className="text-3xl font-bold text-[#1b1b24]">Collections</h2>
          <p className="text-[#464555] mt-1 max-w-2xl text-sm">
            Organize documents into governed knowledge bases for scoped retrieval and chat.
            Apply granular access policies to ensure security across your RAG operations.
          </p>
        </section>

        {/* Summary metrics */}
        {showGrid && allCollections.length > 0 ? (
          <SummaryMetrics total={total} totalDocs={totalDocs} indexedDocs={indexedDocs} restrictedCount={restrictedCount} />
        ) : null}

        {/* Toolbar */}
        <section className="bg-white border border-[#e4e1ee] rounded-xl p-2 flex flex-wrap gap-3 items-center">
          <div className="flex-1 min-w-[180px] relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[#9993b8] text-[20px]">search</span>
            <input
              type="search"
              value={nameSearch}
              onChange={(e) => setNameSearch(e.target.value)}
              placeholder="Filter by name…"
              className="w-full text-sm pl-10 py-2 border-none bg-transparent focus:ring-0 outline-none text-[#1b1b24]"
            />
          </div>
          <div className="h-6 w-px bg-[#e4e1ee] hidden sm:block" />
          <div className="flex items-center gap-2">
            <span className="text-[#6a6780] text-[12px] font-semibold whitespace-nowrap">Access:</span>
            <select
              value={accessFilter}
              onChange={(e) => setAccessFilter(e.target.value as CollectionAccessPolicy | "all")}
              className="text-sm border-none bg-[#f5f3ff] rounded-lg py-1.5 pl-2 pr-6 focus:ring-2 focus:ring-[#3525cd]/20 outline-none text-[#2a2640]"
            >
              <option value="all">All Policies</option>
              <option value="org_wide">Org-wide</option>
              <option value="admin_only">Admin-only</option>
              <option value="selected_roles">Selected roles</option>
              <option value="selected_members">Selected members</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[#6a6780] text-[12px] font-semibold">Sort:</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as "updated" | "name" | "docs")}
              className="text-sm border-none bg-[#f5f3ff] rounded-lg py-1.5 pl-2 pr-6 focus:ring-2 focus:ring-[#3525cd]/20 outline-none text-[#2a2640]"
            >
              <option value="updated">Last Updated</option>
              <option value="name">Name A-Z</option>
              <option value="docs">Doc Count</option>
            </select>
          </div>
          {capabilities.canCreate ? (
            <button
              type="button"
              onClick={() => { setDialogSaveError(null); setDialogMode("create"); }}
              className="bg-[#3525cd] text-white px-4 py-2 rounded-full text-sm font-semibold flex items-center gap-1 hover:shadow-lg hover:shadow-[#3525cd]/20 transition-all active:scale-95"
            >
              <span className="material-symbols-outlined text-[18px]">add</span>
              New Collection
            </button>
          ) : null}
        </section>

        {/* Feedback banner */}
        {actionFeedback ? (
          <p role="status" className="rounded-xl border border-[#ddd7f6] bg-[#f3f1ff] px-4 py-2.5 text-sm text-[#3f3778]">
            {actionFeedback}
            {actionRequestId ? ` (Trace ID: ${actionRequestId})` : ""}
          </p>
        ) : null}

        {/* Error / empty states */}
        {!collectionsEnabled ? (
          <EmptyState title="Collections not available" description="Set NEXT_PUBLIC_FEATURE_COLLECTIONS_ENABLED=true to enable." />
        ) : null}
        {isLoading ? <LoadingState title="Loading collections…" /> : null}
        {isError && isEndpointNotFoundError(collectionsQuery.error) ? (
          <EmptyState title="Collections not yet available" description="The collections API is not deployed in this environment." />
        ) : null}
        {isError && !isEndpointNotFoundError(collectionsQuery.error) && listForbidden ? (
          <ForbiddenState compact title="Collections access denied" description="You do not have permission to view collections in this organization." requestId={extractRequestIdFromError(collectionsQuery.error)} />
        ) : null}
        {isError && !isEndpointNotFoundError(collectionsQuery.error) && !listForbidden ? (
          <ErrorState error={collectionsQuery.error} description={getApiErrorMessage(collectionsQuery.error)} onRetry={() => void collectionsQuery.refetch()} />
        ) : null}

        {/* Collection grid */}
        {showGrid ? (
          <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 pb-8">
            {visibleCollections.map((col) => (
              <CollectionCard
                key={col.collection_id}
                collection={col}
                isSelected={selectedCollectionId === col.collection_id}
                capabilities={capabilities}
                onSelect={() =>
                  setSelectedCollectionId(
                    selectedCollectionId === col.collection_id ? null : col.collection_id,
                  )
                }
                onEdit={(c) => {
                  setDialogSaveError(null);
                  setDialogMode({ mode: "edit", collection: c as CollectionDetailResponse });
                }}
                onDelete={handleDeleteCollection}
                isDeleting={
                  deleteMutation.isPending && deleteMutation.variables === col.collection_id
                }
              />
            ))}

            {visibleCollections.length === 0 ? (
              <div className="col-span-full">
                <EmptyState
                  title={nameSearch || accessFilter !== "all" ? "No collections match your filters." : "No collections yet."}
                  description={nameSearch || accessFilter !== "all" ? undefined : "Create your first collection to group documents for scoped retrieval and chat."}
                  action={
                    nameSearch || accessFilter !== "all" ? (
                      <button
                        type="button"
                        onClick={() => { setNameSearch(""); setAccessFilter("all"); }}
                        className="rounded-xl border border-[#d2cee6] bg-white px-3 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
                      >
                        Clear filters
                      </button>
                    ) : capabilities.canCreate ? (
                      <button
                        type="button"
                        onClick={() => { setDialogSaveError(null); setDialogMode("create"); }}
                        className="rounded-xl bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
                      >
                        New Collection
                      </button>
                    ) : undefined
                  }
                />
              </div>
            ) : null}

            {visibleCollections.length > 0 && capabilities.canCreate ? (
              <NewCollectionCard
                onCreate={() => { setDialogSaveError(null); setDialogMode("create"); }}
              />
            ) : null}
          </section>
        ) : null}

        {/* Pagination */}
        {showGrid && totalPages > 1 ? (
          <div className="flex items-center justify-between gap-3 pb-4">
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setOffset((p) => Math.max(0, p - COLLECTIONS_PAGE_SIZE))}
              className="flex items-center gap-1 rounded-xl border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="material-symbols-outlined text-[18px]">chevron_left</span>
              Previous
            </button>
            <p className="text-sm text-[#68647b]">Page {currentPage} of {totalPages}</p>
            <button
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => setOffset((p) => p + COLLECTIONS_PAGE_SIZE)}
              className="flex items-center gap-1 rounded-xl border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
            >
              Next
              <span className="material-symbols-outlined text-[18px]">chevron_right</span>
            </button>
          </div>
        ) : null}
      </section>

      {/* Drawer overlay + drawer */}
      {selectedCollectionId ? (
        <>
          <div
            className="fixed inset-0 bg-[#302f39]/20 z-40"
            onClick={() => setSelectedCollectionId(null)}
          />
          <CollectionDetailDrawer
            key={selectedCollectionId}
            collectionId={selectedCollectionId}
            capabilities={capabilities}
            onClose={() => setSelectedCollectionId(null)}
            onEdit={(collection) => {
              setDialogSaveError(null);
              setDialogMode({ mode: "edit", collection });
            }}
          />
        </>
      ) : null}

      {/* Dialogs */}
      {dialogMode === "create" ? (
        <CollectionDialog
          title="New Collection"
          initial={DEFAULT_FORM}
          saving={createMutation.isPending}
          saveError={dialogSaveError}
          onSave={handleCreateSave}
          onClose={() => { setDialogMode(null); setDialogSaveError(null); }}
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
          onClose={() => { setDialogMode(null); setDialogSaveError(null); }}
        />
      ) : null}
    </>
  );
}
