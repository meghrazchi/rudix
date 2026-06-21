"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  createCollection,
  addDocumentToCollection,
  deleteCollection,
  getCollection,
  getCollectionPolicy,
  listCollectionDocuments,
  listCollections,
  refreshCollectionRules,
  removeDocumentFromCollection,
  setCollectionRules,
  updateCollection,
  updateCollectionPolicy,
  type CollectionAccessGrant,
  type CollectionAccessPolicy,
  type CollectionDetailResponse,
  type CollectionListItemResponse,
  type DynamicRuleSet,
} from "@/lib/api/collections";
import {
  DynamicRuleBuilder,
  emptyRuleSet,
} from "@/components/collections/DynamicRuleBuilder";
import {
  listDocuments,
  type DocumentListItemResponse,
} from "@/lib/api/documents";
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
const COLLECTION_DOCS_PAGE_SIZE = 20;
const COLLECTION_DOCS_INITIAL_LIMIT = 10;
const COLLECTION_PICKER_PAGE_SIZE = 10;

const CARD_ICONS = [
  "inventory_2",
  "account_balance",
  "book_2",
  "layers",
  "hub",
  "category",
  "psychology",
  "school",
  "insights",
  "folder_shared",
  "gavel",
  "support_agent",
  "science",
  "engineering",
  "manage_accounts",
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

function formatRelativeDate(
  value: string,
  tc: ReturnType<typeof useTranslations>,
): string {
  try {
    const diff = Date.now() - new Date(value).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 2) return tc("relativeJustNow");
    if (mins < 60) return tc("relativeMinutesAgo", { n: mins });
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return tc("relativeHoursAgo", { n: hrs });
    return tc("relativeDaysAgo", { n: Math.floor(hrs / 24) });
  } catch {
    return "";
  }
}

function accessPolicyLabel(
  policy: CollectionAccessPolicy,
  tc: ReturnType<typeof useTranslations>,
): string {
  switch (policy) {
    case "org_wide":
      return tc("policyLabelOrgWide");
    case "admin_only":
      return tc("policyLabelAdminOnly");
    case "selected_roles":
      return tc("policyLabelSelectedRoles");
    case "selected_members":
      return tc("policyLabelSelectedMembers");
    default:
      return policy;
  }
}

function accessPolicyBadgeClass(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide":
      return "bg-green-50 text-green-700 border-green-200";
    case "admin_only":
      return "bg-amber-50 text-amber-800 border-amber-200";
    case "selected_roles":
      return "bg-blue-50 text-blue-700 border-blue-200";
    case "selected_members":
      return "bg-violet-50 text-violet-700 border-violet-200";
    default:
      return "bg-slate-50 text-slate-600 border-slate-200";
  }
}

function accessPolicyDescription(
  policy: CollectionAccessPolicy,
  tc: ReturnType<typeof useTranslations>,
): string {
  switch (policy) {
    case "org_wide":
      return tc("policyDescOrgWide");
    case "admin_only":
      return tc("policyDescAdminOnly");
    case "selected_roles":
      return tc("policyDescSelectedRoles");
    case "selected_members":
      return tc("policyDescSelectedMembers");
    default:
      return "";
  }
}

function accessPolicyIcon(policy: CollectionAccessPolicy): string {
  switch (policy) {
    case "org_wide":
      return "public";
    case "admin_only":
      return "admin_panel_settings";
    case "selected_roles":
      return "group";
    case "selected_members":
      return "person_check";
    default:
      return "lock";
  }
}

type ManageCollectionDocumentsDialogProps = {
  collectionName: string;
  initialDocumentIds: string[];
  saving: boolean;
  saveError: string | null;
  onClose: () => void;
  onSave: (documentIds: string[]) => void;
};

function ManageCollectionDocumentsDialog({
  collectionName,
  initialDocumentIds,
  saving,
  saveError,
  onClose,
  onSave,
}: ManageCollectionDocumentsDialogProps) {
  const tc = useTranslations("collections.page");
  const [searchQuery, setSearchQuery] = useState("");
  const [pageOffset, setPageOffset] = useState(0);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(
    () => new Set(initialDocumentIds),
  );

  const documentsQuery = useQuery({
    queryKey: [
      ...queryKeys.documents.all,
      "collection-picker",
      searchQuery.trim(),
      pageOffset,
    ],
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: COLLECTION_PICKER_PAGE_SIZE,
        offset: pageOffset,
        filename_query: searchQuery.trim() || undefined,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
    placeholderData: (previous) => previous,
  });

  const documents = documentsQuery.data?.items ?? [];
  const totalDocuments = documentsQuery.data?.total ?? 0;
  const currentPage = Math.floor(pageOffset / COLLECTION_PICKER_PAGE_SIZE) + 1;
  const totalPages = Math.max(
    1,
    Math.ceil(totalDocuments / COLLECTION_PICKER_PAGE_SIZE),
  );
  const canGoPrev = pageOffset > 0;
  const canGoNext = pageOffset + COLLECTION_PICKER_PAGE_SIZE < totalDocuments;
  const selectedCount = selectedDocumentIds.size;
  const selectedOnPage = documents.filter((document) =>
    selectedDocumentIds.has(document.document_id),
  );
  const allOnPageSelected =
    documents.length > 0 && selectedOnPage.length === documents.length;
  const someOnPageSelected =
    selectedOnPage.length > 0 && selectedOnPage.length < documents.length;

  function toggleDocument(documentId: string) {
    setSelectedDocumentIds((previous) => {
      const next = new Set(previous);
      if (next.has(documentId)) {
        next.delete(documentId);
      } else {
        next.add(documentId);
      }
      return next;
    });
  }

  function togglePageSelection() {
    setSelectedDocumentIds((previous) => {
      const next = new Set(previous);
      if (allOnPageSelected) {
        for (const document of documents) {
          next.delete(document.document_id);
        }
      } else {
        for (const document of documents) {
          next.add(document.document_id);
        }
      }
      return next;
    });
  }

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-[#17172a]/40 px-4"
      onClick={onClose}
    >
      <div
        className="flex w-full max-w-2xl flex-col rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">
              {tc("manageDocumentsTitle")}
            </h2>
            <p className="text-sm text-[#68647b]">{collectionName}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            {tc("cancel")}
          </button>
        </div>

        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="relative flex-1">
            <span className="material-symbols-outlined absolute top-1/2 left-3 -translate-y-1/2 text-[20px] text-[#9993b8]">
              search
            </span>
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => {
                setSearchQuery(event.target.value);
                setPageOffset(0);
              }}
              placeholder={tc("manageDocumentsSearchPlaceholder")}
              className="h-10 w-full rounded-xl border border-[#d2cee6] bg-white pr-3 pl-10 text-sm text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            />
          </div>
          <span className="rounded-full bg-[#f3f1ff] px-3 py-1 text-xs font-semibold text-[#3525cd]">
            {tc("manageDocumentsSelected", { n: selectedCount })}
          </span>
        </div>

        <div className="mb-3 flex items-center justify-between gap-3 rounded-2xl border border-[#e4e1ee] bg-[#faf9ff] px-3 py-2 text-xs text-[#6a6780]">
          <label className="flex cursor-pointer items-center gap-2 font-semibold text-[#2a2640]">
            <input
              type="checkbox"
              checked={allOnPageSelected}
              ref={(input) => {
                if (input) {
                  input.indeterminate = someOnPageSelected;
                }
              }}
              onChange={togglePageSelection}
              className="accent-[#3525cd]"
            />
            <span>{tc("selectAllOnPage")}</span>
          </label>
          <span className="font-semibold">
            {tc("pageOf", { page: currentPage, total: totalPages })}
          </span>
        </div>

        <div className="max-h-[28rem] overflow-y-auto rounded-2xl border border-[#e4e1ee] bg-[#faf9ff] p-3">
          {documentsQuery.isLoading ? (
            <LoadingState compact title={tc("loadingDocuments")} />
          ) : documentsQuery.isError ? (
            <ErrorState
              compact
              error={documentsQuery.error}
              description={getApiErrorMessage(documentsQuery.error)}
              onRetry={() => void documentsQuery.refetch()}
            />
          ) : documents.length === 0 ? (
            <EmptyState
              compact
              title={tc("noDocumentsTitle")}
              description={tc("manageDocumentsNoMatch")}
            />
          ) : (
            <div className="space-y-2">
              {documents.map((document: DocumentListItemResponse) => {
                const selected = selectedDocumentIds.has(document.document_id);
                return (
                  <button
                    key={document.document_id}
                    type="button"
                    onClick={() => toggleDocument(document.document_id)}
                    className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2 text-left transition-colors ${
                      selected
                        ? "border-[#3525cd] bg-[#ece8ff]"
                        : "border-[#e2dff1] bg-white hover:bg-[#f7f5ff]"
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-[#2a2640]">
                        {document.filename}
                      </span>
                      <span className="mt-0.5 block text-xs text-[#6a6780]">
                        {document.source_provider_label ??
                          tc("documentSourceFallback")}
                      </span>
                    </span>
                    <span className="rounded-full bg-[#f1f0f5] px-2 py-1 text-[10px] font-semibold text-[#6a6780]">
                      {selected ? tc("selected") : tc("select")}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {totalDocuments > COLLECTION_PICKER_PAGE_SIZE ? (
          <div className="mt-3 flex items-center justify-between gap-3">
            <button
              type="button"
              disabled={!canGoPrev}
              onClick={() =>
                setPageOffset((previous) =>
                  Math.max(0, previous - COLLECTION_PICKER_PAGE_SIZE),
                )
              }
              className="rounded-lg border border-[#e4e1ee] px-3 py-1.5 text-xs font-semibold text-[#3e376f] disabled:opacity-40"
            >
              {tc("previousDocs")}
            </button>
            <span className="text-xs text-[#6a6780]">
              {tc("docsShowing", {
                shown: documents.length,
                total: totalDocuments,
              })}
            </span>
            <button
              type="button"
              disabled={!canGoNext}
              onClick={() =>
                setPageOffset((previous) =>
                  Math.min(
                    previous + COLLECTION_PICKER_PAGE_SIZE,
                    Math.max(0, (totalPages - 1) * COLLECTION_PICKER_PAGE_SIZE),
                  ),
                )
              }
              className="rounded-lg border border-[#e4e1ee] px-3 py-1.5 text-xs font-semibold text-[#3e376f] disabled:opacity-40"
            >
              {tc("nextDocs")}
            </button>
          </div>
        ) : null}

        {saveError ? (
          <p className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {saveError}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[#d2cee6] bg-white px-4 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
          >
            {tc("cancel")}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => onSave(Array.from(selectedDocumentIds))}
            className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? tc("saving") : tc("updateDocuments")}
          </button>
        </div>
      </div>
    </div>
  );
}

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
  const tc = useTranslations("collections.page");
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {[
        {
          icon: "folder",
          color: "bg-[#3525cd]/10 text-[#3525cd]",
          label: tc("metricTotalCollections"),
          value: total,
        },
        {
          icon: "description",
          color: "bg-slate-100 text-slate-600",
          label: tc("metricVisibleDocs"),
          value: totalDocs.toLocaleString(),
        },
        {
          icon: "check_circle",
          color: "bg-green-50 text-green-700",
          label: tc("metricIndexedDocs"),
          value: indexedDocs.toLocaleString(),
        },
        {
          icon: "lock",
          color: "bg-amber-50 text-amber-700",
          label: tc("metricRestricted"),
          value: restrictedCount,
        },
      ].map(({ icon, color, label, value }) => (
        <div
          key={label}
          className="flex items-center gap-4 rounded-2xl border border-[#e4e1ee] bg-white p-5"
        >
          <div
            className={`h-12 w-12 rounded-xl ${color} flex items-center justify-center`}
          >
            <span className="material-symbols-outlined">{icon}</span>
          </div>
          <div>
            <p className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
              {label}
            </p>
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
  const tc = useTranslations("collections.page");
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
      className={`group flex h-full cursor-pointer flex-col rounded-2xl border bg-white p-6 transition-all hover:border-[#3525cd]/40 hover:shadow-xl hover:shadow-[#3525cd]/5 ${
        isSelected
          ? "border-[#3525cd]/60 shadow-lg shadow-[#3525cd]/10"
          : "border-[#e4e1ee]"
      }`}
      onClick={onSelect}
    >
      <div className="mb-4 flex items-start justify-between">
        <div
          className={`rounded-xl p-2 transition-colors ${
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
        <div className="flex items-center gap-1.5">
          {col.is_dynamic ? (
            <span className="rounded-full border border-violet-300 bg-violet-50 px-2 py-0.5 text-[11px] font-bold tracking-tight text-violet-700 uppercase">
              Dynamic
            </span>
          ) : null}
          <span
            className={`rounded-full border px-2 py-0.5 text-[11px] font-bold tracking-tight uppercase ${accessPolicyBadgeClass(col.access_policy)}`}
          >
            {accessPolicyLabel(col.access_policy, tc)}
          </span>
        </div>
      </div>

      <h4 className="mb-1 text-lg font-semibold text-[#1b1b24]">{col.name}</h4>
      <p className="mb-5 line-clamp-2 min-h-[2.5rem] flex-1 text-sm text-[#464555]">
        {col.description ?? (
          <span className="text-[#b0abc8] italic">{tc("noDescription")}</span>
        )}
      </p>

      <div className="space-y-3">
        <div>
          <div className="mb-1.5 flex justify-between text-[12px]">
            <span className="text-[#6a6780]">{tc("indexingProgress")}</span>
            <span className="font-bold text-[#1b1b24]">
              {progress}% ({col.indexed_count}/{col.document_count})
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-[#f0ecf9]">
            <div
              className={`${progressColor} h-full rounded-full`}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-[#e4e1ee]/60 pt-3">
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#e4e1ee]">
              <span className="material-symbols-outlined text-[12px] text-[#6a6780]">
                person
              </span>
            </div>
            <span className="truncate text-[12px] font-medium text-[#6a6780]">
              {col.owner_email ?? col.owner_id}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <span className="text-[11px] text-[#b0abc8]">
              {formatRelativeDate(col.updated_at, tc)}
            </span>
            {capabilities.canEdit ? (
              <button
                type="button"
                aria-label={tc("editAriaLabel")}
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit(col);
                }}
                className="ml-1 rounded p-1 text-[#6a6780] opacity-0 transition-all group-hover:opacity-100 hover:bg-[#f0ecf9] hover:text-[#3525cd]"
              >
                <span className="material-symbols-outlined text-[16px]">
                  edit
                </span>
              </button>
            ) : null}
            {capabilities.canDelete ? (
              <button
                type="button"
                aria-label={tc("deleteAriaLabel")}
                disabled={isDeleting}
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(col);
                }}
                className="rounded p-1 text-[#6a6780] opacity-0 transition-all group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40"
              >
                <span className="material-symbols-outlined text-[16px]">
                  delete
                </span>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function NewCollectionCard({ onCreate }: { onCreate: () => void }) {
  const tc = useTranslations("collections.page");
  return (
    <div
      className="group flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-[#e4e1ee] bg-white p-6 text-center transition-all hover:border-[#3525cd]/30 hover:bg-[#f5f3ff]/50"
      onClick={onCreate}
    >
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#f0ecf9] text-[#6a6780] transition-transform group-hover:scale-110">
        <span className="material-symbols-outlined text-[32px]">add</span>
      </div>
      <h4 className="mb-1 text-base font-bold text-[#1b1b24]">
        {tc("createNewTitle")}
      </h4>
      <p className="px-4 text-[12px] text-[#6a6780]">{tc("createNewDesc")}</p>
    </div>
  );
}

// ── Policy editor ────────────────────────────────────────────────────────────

type PolicyEditorProps = {
  collectionId: string;
  collectionName: string;
};

function PolicyEditor({ collectionId, collectionName }: PolicyEditorProps) {
  const tc = useTranslations("collections.page");
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
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
    mutationFn: (req: {
      access_policy: CollectionAccessPolicy;
      grants: CollectionAccessGrant[];
    }) => updateCollectionPolicy(collectionId, req),
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
      return Array.from(roleGrants).map((v) => ({
        grantee_type: "role" as const,
        grantee_value: v,
      }));
    if (policy === "selected_members")
      return Array.from(memberGrants).map((v) => ({
        grantee_type: "member" as const,
        grantee_value: v,
      }));
    return [];
  }

  function handlePolicyChange(next: CollectionAccessPolicy) {
    if (
      (policyQuery.data?.access_policy ?? "org_wide") === "org_wide" &&
      next !== "org_wide"
    ) {
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
      setRoleGrants(
        new Set(
          policyQuery.data.grants
            .filter((g) => g.grantee_type === "role")
            .map((g) => g.grantee_value),
        ),
      );
      setMemberGrants(
        new Set(
          policyQuery.data.grants
            .filter((g) => g.grantee_type === "member")
            .map((g) => g.grantee_value),
        ),
      );
    }
  }

  if (policyQuery.isLoading)
    return <LoadingState compact title={tc("loadingPolicy")} />;
  if (policyQuery.isError) {
    if (isForbiddenError(policyQuery.error))
      return (
        <ForbiddenState
          compact
          title={tc("policyDeniedTitle")}
          description={tc("policyDeniedDesc")}
          requestId={extractRequestIdFromError(policyQuery.error)}
        />
      );
    return (
      <ErrorState
        compact
        error={policyQuery.error}
        description={getApiErrorMessage(policyQuery.error)}
        onRetry={() => void policyQuery.refetch()}
      />
    );
  }

  const effectivePolicy =
    policy ?? policyQuery.data?.access_policy ?? "org_wide";
  const members: TeamMember[] = membersQuery.data?.items ?? [];
  const eligibleMembers = members.filter(
    (m) => m.role !== "owner" && m.role !== "admin" && m.user_id,
  );

  return (
    <div className="space-y-4">
      {showWarning ? (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5">
          <span className="material-symbols-outlined mt-0.5 shrink-0 text-base text-amber-700">
            warning
          </span>
          <p className="text-xs text-amber-800">
            {tc("restrictWarning", { name: collectionName })}
          </p>
        </div>
      ) : null}

      <div>
        <label className="mb-1.5 block text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
          {tc("policyModeLabel")}
        </label>
        <select
          value={effectivePolicy}
          onChange={(e) =>
            handlePolicyChange(e.target.value as CollectionAccessPolicy)
          }
          className="h-9 w-full rounded-xl border border-[#d2cee6] bg-white px-3 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
        >
          <option value="org_wide">{tc("policyOptOrgWide")}</option>
          <option value="admin_only">{tc("policyOptAdminOnlyFull")}</option>
          <option value="selected_roles">
            {tc("policyLabelSelectedRoles")}
          </option>
          <option value="selected_members">
            {tc("policyLabelSelectedMembers")}
          </option>
        </select>
        <p className="mt-1 text-[11px] text-[#7a768f]">
          {accessPolicyDescription(effectivePolicy, tc)}
        </p>
      </div>

      {effectivePolicy === "selected_roles" ? (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
            {tc("rolesWithAccess")}
          </p>
          <p className="text-[11px] text-[#7a768f]">
            {tc("adminsAlwaysHaveAccess")}
          </p>
          {[
            { value: "member", label: tc("roleMember") },
            { value: "viewer", label: tc("roleViewer") },
          ].map(({ value, label }) => (
            <label
              key={value}
              className="flex cursor-pointer items-center gap-3 rounded-xl border border-[#e4e1ee] bg-white px-3 py-2 hover:bg-[#f5f3ff]"
            >
              <input
                type="checkbox"
                checked={roleGrants.has(value)}
                onChange={() => {
                  setRoleGrants((prev) => {
                    const n = new Set(prev);
                    if (n.has(value)) {
                      n.delete(value);
                    } else {
                      n.add(value);
                    }
                    return n;
                  });
                  setIsDirty(true);
                }}
                className="accent-[#3525cd]"
              />
              <span className="text-sm font-semibold text-[#2a2640]">
                {label}
              </span>
            </label>
          ))}
          {roleGrants.size === 0 ? (
            <p className="text-[11px] text-amber-700">
              {tc("noRolesSelected")}
            </p>
          ) : null}
        </div>
      ) : null}

      {effectivePolicy === "selected_members" ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
            {tc("membersWithAccess")}
          </p>
          <p className="text-[11px] text-[#7a768f]">
            {tc("adminsAlwaysHaveAccess")}
          </p>
          {!teamCapabilities.listMembersEnabled ? (
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
              Configure <code>NEXT_PUBLIC_TEAM_MEMBERS_LIST_URL</code> to enable
              the member picker.
            </p>
          ) : membersQuery.isLoading ? (
            <LoadingState compact title={tc("loadingMembers")} />
          ) : eligibleMembers.length === 0 ? (
            <EmptyState
              compact
              title={tc("noEligibleMembersTitle")}
              description={tc("noEligibleMembersDesc")}
            />
          ) : (
            <ul className="max-h-44 space-y-0.5 overflow-auto rounded-xl border border-[#e4e1ee] bg-white p-2">
              {eligibleMembers.map((m) => (
                <li key={m.user_id}>
                  <label className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-[#f5f3ff]">
                    <input
                      type="checkbox"
                      checked={memberGrants.has(m.user_id!)}
                      onChange={() => {
                        setMemberGrants((prev) => {
                          const n = new Set(prev);
                          if (n.has(m.user_id!)) {
                            n.delete(m.user_id!);
                          } else {
                            n.add(m.user_id!);
                          }
                          return n;
                        });
                        setIsDirty(true);
                      }}
                      className="accent-[#3525cd]"
                    />
                    <span className="flex-1">
                      <span className="block text-sm font-semibold text-[#2a2640]">
                        {m.name}
                      </span>
                      <span className="block text-[11px] text-[#68647b]">
                        {m.email}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          {memberGrants.size === 0 && teamCapabilities.listMembersEnabled ? (
            <p className="text-[11px] text-amber-700">
              {tc("noMembersSelected")}
            </p>
          ) : null}
        </div>
      ) : null}

      {!isDirty && policyQuery.data ? (
        <p className="text-[11px] text-[#68647b]">
          {effectivePolicy === "org_wide" && tc("statusOrgWide")}
          {effectivePolicy === "admin_only" && tc("statusAdminOnly")}
          {effectivePolicy === "selected_roles" &&
            (() => {
              const roles = policyQuery.data.grants
                .filter((g) => g.grantee_type === "role")
                .map((g) => g.grantee_value);
              return roles.length > 0
                ? tc("statusGrantedToRoles", { roles: roles.join(", ") + "s" })
                : tc("statusOnlyAdmins");
            })()}
          {effectivePolicy === "selected_members" &&
            (() => {
              const count = policyQuery.data.grants.filter(
                (g) => g.grantee_type === "member",
              ).length;
              return count === 0
                ? tc("statusNoMembersGranted")
                : tc("statusMembersGranted", { count });
            })()}
        </p>
      ) : null}

      {saveError ? (
        <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {saveError}
        </p>
      ) : null}

      {isDirty ? (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleDiscard}
            disabled={saveMutation.isPending}
            className="flex-1 rounded-xl border border-[#d2cee6] py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff] disabled:opacity-60"
          >
            {tc("discard")}
          </button>
          <button
            type="button"
            onClick={() => {
              if (policy)
                saveMutation.mutate({
                  access_policy: policy,
                  grants: buildGrants(),
                });
            }}
            disabled={saveMutation.isPending}
            className="flex-1 rounded-xl bg-[#3525cd] py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:opacity-60"
          >
            {saveMutation.isPending ? tc("saving") : tc("savePolicy")}
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
  const tc = useTranslations("collections.page");
  const queryClient = useQueryClient();
  const [docsLimit, setDocsLimit] = useState(COLLECTION_DOCS_INITIAL_LIMIT);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [isDocumentPickerOpen, setIsDocumentPickerOpen] = useState(false);
  const [documentSaveError, setDocumentSaveError] = useState<string | null>(
    null,
  );

  const detailQuery = useQuery({
    queryKey: queryKeys.collections.detail(collectionId),
    queryFn: () => getCollection(collectionId),
  });

  const docsParams = { limit: docsLimit, offset: 0 };
  const docsQuery = useQuery({
    queryKey: queryKeys.collections.documents(collectionId, docsParams),
    queryFn: () => listCollectionDocuments(collectionId, docsParams),
  });

  const allCollectionDocsQuery = useQuery({
    queryKey: [
      ...queryKeys.collections.documents(collectionId, {
        limit: 200,
        offset: 0,
      }),
      "all",
    ],
    queryFn: () =>
      listCollectionDocuments(collectionId, { limit: 200, offset: 0 }),
  });

  const refreshRulesMutation = useMutation({
    mutationFn: () => refreshCollectionRules(collectionId),
    onSuccess: async (result) => {
      setActionFeedback(
        `Rules refreshed — ${result.matched_count} document${result.matched_count === 1 ? "" : "s"} matched.`,
      );
      await invalidateAfterMutation(queryClient, "collection.rules.refresh");
      await invalidateAfterMutation(queryClient, "collection.document.add");
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
    },
  });

  const removeDocMutation = useMutation({
    mutationFn: (documentId: string) =>
      removeDocumentFromCollection(collectionId, documentId),
    onSuccess: async () => {
      setActionFeedback(tc("docRemovedFeedback"));
      await invalidateAfterMutation(queryClient, "collection.document.remove");
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
    },
  });

  const manageDocumentsMutation = useMutation({
    mutationFn: async (documentIds: string[]) => {
      const currentDocumentIds = new Set(
        (allCollectionDocsQuery.data?.items ?? []).map(
          (doc) => doc.document_id,
        ),
      );
      const nextDocumentIds = new Set(documentIds);

      const toAdd = Array.from(nextDocumentIds).filter(
        (documentId) => !currentDocumentIds.has(documentId),
      );
      const toRemove = Array.from(currentDocumentIds).filter(
        (documentId) => !nextDocumentIds.has(documentId),
      );

      await Promise.all([
        ...toAdd.map((documentId) =>
          addDocumentToCollection(collectionId, documentId),
        ),
        ...toRemove.map((documentId) =>
          removeDocumentFromCollection(collectionId, documentId),
        ),
      ]);
    },
    onSuccess: async () => {
      setIsDocumentPickerOpen(false);
      setDocumentSaveError(null);
      setActionFeedback(tc("docSavedFeedback"));
      await invalidateAfterMutation(queryClient, "collection.document.add");
      await invalidateAfterMutation(queryClient, "collection.document.remove");
    },
    onError: (error) => {
      setDocumentSaveError(getApiErrorMessage(error));
    },
  });

  const detail = detailQuery.data;
  const docs = docsQuery.data;
  const progress =
    detail && detail.document_count > 0
      ? Math.round((detail.indexed_count / detail.document_count) * 100)
      : 0;
  const canLoadMore =
    Boolean(docs) && (docs?.items.length ?? 0) < (docs?.total ?? 0);
  const existingDocumentIds = (allCollectionDocsQuery.data?.items ?? []).map(
    (doc) => doc.document_id,
  );

  const fileIcon = (type: string) =>
    type === "pdf"
      ? "picture_as_pdf"
      : type === "docx"
        ? "article"
        : "description";

  return (
    <div className="fixed top-0 right-0 z-50 flex h-screen w-[480px] flex-col border-l border-[#e4e1ee] bg-white shadow-2xl">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[#e4e1ee] px-6 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-[#f0ecf9]"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
          <h3 className="truncate text-base font-semibold text-[#1b1b24]">
            {detail?.name ?? tc("drawerFallbackTitle")}
          </h3>
        </div>
        {detail && capabilities.canEdit ? (
          <button
            type="button"
            onClick={() => onEdit(detail)}
            className="ml-2 shrink-0 rounded-lg border border-[#e4e1ee] px-4 py-1.5 text-sm font-semibold text-[#2a2640] transition-colors hover:bg-[#f0ecf9]"
          >
            {tc("drawerEdit")}
          </button>
        ) : null}
      </div>

      {/* Scrollable content */}
      <div
        className="flex-1 space-y-6 overflow-y-auto p-6"
        style={{ scrollbarWidth: "thin" }}
      >
        {detailQuery.isLoading ? (
          <LoadingState title={tc("loadingCollection")} />
        ) : detailQuery.isError ? (
          isForbiddenError(detailQuery.error) ? (
            <ForbiddenState
              compact
              title={tc("drawerDeniedTitle")}
              description={tc("drawerDeniedDesc")}
              requestId={extractRequestIdFromError(detailQuery.error)}
            />
          ) : (
            <ErrorState
              compact
              error={detailQuery.error}
              description={getApiErrorMessage(detailQuery.error)}
              onRetry={() => void detailQuery.refetch()}
            />
          )
        ) : detail ? (
          <>
            {/* Hero */}
            <section>
              <div className="flex gap-5 rounded-2xl bg-[#f5f3ff] p-5">
                <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-[#3525cd] text-white">
                  <span
                    className="material-symbols-outlined text-[40px]"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    {pickIcon(collectionId)}
                  </span>
                </div>
                <div className="min-w-0">
                  <p className="mb-1 text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
                    {tc("collectionMetadata")}
                  </p>
                  <h4 className="text-xl leading-tight font-bold text-[#1b1b24]">
                    {detail.name}
                  </h4>
                  {detail.description ? (
                    <p className="mt-1 line-clamp-2 text-sm text-[#6a6780]">
                      {detail.description}
                    </p>
                  ) : null}
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <div className="flex items-center gap-1 text-[12px] text-[#6a6780]">
                      <span className="material-symbols-outlined text-[16px]">
                        database
                      </span>
                      {tc("drawerDocsCount", { n: detail.document_count })}
                    </div>
                    <div className="flex items-center gap-1 text-[12px] text-[#6a6780]">
                      <span className="material-symbols-outlined text-[16px]">
                        check_circle
                      </span>
                      {tc("drawerIndexedCount", { n: detail.indexed_count })}
                    </div>
                    {detail.is_dynamic ? (
                      <span className="rounded-full border border-violet-300 bg-violet-50 px-2 py-0.5 text-[10px] font-bold text-violet-700 uppercase">
                        Dynamic
                      </span>
                    ) : null}
                  </div>
                  {detail.is_dynamic && detail.last_rule_evaluated_at ? (
                    <p className="mt-1 text-[11px] text-[#6a6780]">
                      Last evaluated:{" "}
                      {formatRelativeDate(detail.last_rule_evaluated_at, tc)}
                    </p>
                  ) : null}
                </div>
              </div>
            </section>

            {/* Dynamic collection controls */}
            {detail.is_dynamic ? (
              <section className="space-y-2">
                <div className="flex items-center justify-between">
                  <h5 className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
                    Membership rules
                  </h5>
                  {capabilities.canEdit ? (
                    <button
                      type="button"
                      disabled={refreshRulesMutation.isPending}
                      onClick={() => refreshRulesMutation.mutate()}
                      className="flex items-center gap-1 rounded-lg border border-[#d2cee6] bg-white px-2 py-1 text-[11px] font-semibold text-[#3525cd] hover:bg-[#f0ecf9] disabled:opacity-60"
                    >
                      <span className="material-symbols-outlined text-[14px]">
                        {refreshRulesMutation.isPending
                          ? "hourglass_empty"
                          : "refresh"}
                      </span>
                      {refreshRulesMutation.isPending
                        ? "Refreshing…"
                        : "Refresh now"}
                    </button>
                  ) : null}
                </div>
                {detail.rule_schema ? (
                  <div className="rounded-xl border border-[#e4e1ee] bg-[#faf9ff] px-3 py-2">
                    <p className="mb-1 text-[10px] font-semibold tracking-wider text-[#6a6780] uppercase">
                      Match{" "}
                      {detail.rule_schema.logic === "and"
                        ? "all conditions"
                        : "any condition"}
                    </p>
                    <ul className="space-y-0.5">
                      {detail.rule_schema.conditions.map((cond, i) => (
                        <li key={i} className="text-xs text-[#464555]">
                          <span className="font-semibold text-[#2a2640]">
                            {cond.field}
                          </span>{" "}
                          <span className="text-[#6a6780]">
                            {cond.operator}
                          </span>{" "}
                          <span className="font-semibold text-[#3525cd]">
                            {Array.isArray(cond.value)
                              ? cond.value.join(", ")
                              : cond.value}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="text-xs text-[#b0abc8] italic">
                    No rules configured yet.
                  </p>
                )}
              </section>
            ) : null}

            {/* Indexing health */}
            <section className="space-y-3">
              <h5 className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
                {tc("indexingHealthTitle")}
              </h5>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-[#e4e1ee] bg-white p-4">
                  <p className="mb-1 text-[11px] text-[#6a6780]">
                    {tc("completionLabel")}
                  </p>
                  <p
                    className={`text-xl font-bold ${progress === 100 ? "text-green-600" : progress >= 80 ? "text-[#3525cd]" : "text-amber-600"}`}
                  >
                    {progress}%
                  </p>
                </div>
                <div className="rounded-xl border border-[#e4e1ee] bg-white p-4">
                  <p className="mb-1 text-[11px] text-[#6a6780]">
                    {tc("ownerLabel")}
                  </p>
                  <p className="truncate text-sm font-bold text-[#1b1b24]">
                    {detail.owner_email ?? "—"}
                  </p>
                </div>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-[#f0ecf9]">
                <div
                  className={`h-full rounded-full ${progress === 100 ? "bg-green-500" : progress >= 80 ? "bg-[#3525cd]" : "bg-amber-500"}`}
                  style={{ width: `${progress}%` }}
                />
              </div>
            </section>

            {/* Access policy */}
            <section className="space-y-3">
              <h5 className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
                {tc("accessPolicySectionTitle")}
              </h5>
              {capabilities.canManagePolicy ? (
                <PolicyEditor
                  collectionId={collectionId}
                  collectionName={detail.name}
                />
              ) : (
                <div className="flex items-center gap-3 rounded-xl border border-[#3525cd]/20 bg-[#f5f3ff] p-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#3525cd]/10 text-[#3525cd]">
                    <span className="material-symbols-outlined">
                      {accessPolicyIcon(detail.access_policy)}
                    </span>
                  </div>
                  <div>
                    <p className="text-sm font-bold text-[#1b1b24]">
                      {accessPolicyLabel(detail.access_policy, tc)}
                    </p>
                    <p className="text-[11px] text-[#6a6780]">
                      {accessPolicyDescription(detail.access_policy, tc)}
                    </p>
                  </div>
                </div>
              )}
            </section>

            {/* Documents */}
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <h5 className="text-[11px] font-semibold tracking-wider text-[#6a6780] uppercase">
                  {tc("indexedDocumentsTitle")}
                </h5>
                <span className="text-[12px] text-[#6a6780]">
                  {tc("docsTotal", { n: docs?.total ?? 0 })}
                </span>
              </div>

              {actionFeedback ? (
                <p
                  role="status"
                  className="rounded-xl border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
                >
                  {actionFeedback}
                </p>
              ) : null}

              {capabilities.canManageDocuments &&
              !detail.is_dynamic &&
              (docs?.items.length ?? 0) > 0 ? (
                <div className="flex items-center justify-between gap-3 rounded-xl border border-[#e4e1ee] bg-white px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-[#1b1b24]">
                      {tc("manageDocumentsTitle")}
                    </p>
                    <p className="text-xs text-[#6a6780]">
                      {tc("manageDocumentsSubtitle")}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setDocumentSaveError(null);
                      setIsDocumentPickerOpen(true);
                    }}
                    className="rounded-xl bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
                  >
                    {tc("manageDocumentsButton")}
                  </button>
                </div>
              ) : null}
              {detail.is_dynamic && (docs?.items.length ?? 0) === 0 ? (
                <p className="rounded-xl border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-700">
                  This dynamic collection has no matching documents yet. Adjust
                  the rules or refresh to update membership.
                </p>
              ) : null}

              {docsQuery.isLoading ? (
                <LoadingState compact title={tc("loadingDocuments")} />
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
                  title={tc("noDocumentsTitle")}
                  description={tc("noDocumentsDesc")}
                  action={
                    capabilities.canManageDocuments && !detail.is_dynamic ? (
                      <button
                        type="button"
                        onClick={() => {
                          setDocumentSaveError(null);
                          setIsDocumentPickerOpen(true);
                        }}
                        className="rounded-xl bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
                      >
                        {tc("manageDocumentsButton")}
                      </button>
                    ) : undefined
                  }
                />
              ) : docs && docs.items.length > 0 ? (
                <div className="space-y-0.5">
                  {docs.items.map((doc) => (
                    <div
                      key={doc.document_id}
                      className="flex items-center justify-between rounded-xl border-b border-[#e4e1ee]/40 p-2 transition-colors last:border-0 hover:bg-[#f5f3ff]"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="material-symbols-outlined shrink-0 text-[20px] text-[#6a6780]">
                          {fileIcon(doc.file_type)}
                        </span>
                        <Link
                          href={`/documents/${encodeURIComponent(doc.document_id)}`}
                          className="truncate text-sm font-medium text-[#1b1b24] hover:text-[#3525cd]"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {doc.filename}
                        </Link>
                      </div>
                      <div className="ml-2 flex shrink-0 items-center gap-2">
                        <span
                          className={`text-[11px] font-bold ${doc.status === "indexed" ? "text-green-600" : doc.status === "processing" ? "animate-pulse text-[#3525cd]" : "text-[#6a6780]"}`}
                        >
                          {doc.status === "indexed"
                            ? tc("docStatusReady")
                            : doc.status === "processing"
                              ? tc("docStatusIndexing")
                              : doc.status}
                        </span>
                        {capabilities.canManageDocuments &&
                        !detail.is_dynamic ? (
                          <button
                            type="button"
                            aria-label={tc("removeAriaLabel")}
                            disabled={removeDocMutation.isPending}
                            onClick={() => {
                              if (
                                window.confirm(
                                  tc("removeDocConfirm", {
                                    filename: doc.filename,
                                  }),
                                )
                              ) {
                                removeDocMutation.mutate(doc.document_id);
                              }
                            }}
                            className="rounded p-1 text-[#b0abc8] transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40"
                          >
                            <span className="material-symbols-outlined text-[16px]">
                              remove_circle_outline
                            </span>
                          </button>
                        ) : null}
                      </div>
                    </div>
                  ))}

                  {canLoadMore ? (
                    <div className="flex items-center justify-between gap-3 pt-2">
                      <span className="text-xs text-[#6a6780]">
                        {tc("docsShowing", {
                          shown: docs.items.length,
                          total: docs.total,
                        })}
                      </span>
                      <button
                        type="button"
                        onClick={() =>
                          setDocsLimit((current) =>
                            Math.min(
                              current + COLLECTION_DOCS_PAGE_SIZE,
                              docs.total,
                            ),
                          )
                        }
                        className="rounded-lg border border-[#e4e1ee] px-3 py-1 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
                      >
                        {tc("loadMoreDocs")}
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
        <div className="shrink-0 border-t border-[#e4e1ee] bg-[#f5f3ff] p-5">
          <Link
            href={`/chat?collection_id=${encodeURIComponent(collectionId)}`}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#3525cd] py-3 font-bold text-white transition-all hover:bg-[#2b1fa8]"
          >
            <span className="material-symbols-outlined">chat_bubble</span>
            {tc("openChatForCollection")}
          </Link>
        </div>
      ) : null}

      {isDocumentPickerOpen && detail ? (
        <ManageCollectionDocumentsDialog
          key={`${detail.collection_id}:${existingDocumentIds.join(",")}`}
          collectionName={detail.name}
          initialDocumentIds={existingDocumentIds}
          saving={manageDocumentsMutation.isPending}
          saveError={documentSaveError}
          onClose={() => {
            setIsDocumentPickerOpen(false);
            setDocumentSaveError(null);
          }}
          onSave={(documentIds) => manageDocumentsMutation.mutate(documentIds)}
        />
      ) : null}
    </div>
  );
}

// ── Collection form dialog ───────────────────────────────────────────────────

type CollectionFormState = {
  name: string;
  description: string;
  access_policy: CollectionAccessPolicy;
  is_dynamic: boolean;
  rule_schema: DynamicRuleSet;
};

const DEFAULT_FORM: CollectionFormState = {
  name: "",
  description: "",
  access_policy: "org_wide",
  is_dynamic: false,
  rule_schema: {
    logic: "and",
    conditions: [{ field: "file_type", operator: "eq", value: "pdf" }],
  },
};

type CollectionFormErrors = { name?: string };

function validateCollectionForm(
  form: CollectionFormState,
  msgs: { nameRequired: string; nameTooLong: string },
): CollectionFormErrors {
  const errors: CollectionFormErrors = {};
  if (!form.name.trim()) errors.name = msgs.nameRequired;
  else if (form.name.trim().length > 120) errors.name = msgs.nameTooLong;
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
  const tc = useTranslations("collections.page");
  const [form, setForm] = useState<CollectionFormState>(initial);
  const [fieldErrors, setFieldErrors] = useState<CollectionFormErrors>({});
  const nameRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  function handleSubmit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validateCollectionForm(form, {
      nameRequired: tc("errorNameRequired"),
      nameTooLong: tc("errorNameTooLong"),
    });
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});
    onSave(form);
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-[#17172a]/40 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            {tc("cancel")}
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {tc("fieldNameLabel")} <span className="text-rose-600">*</span>
            </label>
            <input
              ref={nameRef}
              type="text"
              value={form.name}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
              maxLength={120}
              placeholder={tc("fieldNamePlaceholder")}
              className="h-9 w-full rounded-xl border border-[#d2cee6] bg-white px-3 text-sm font-medium text-[#2a2640] outline-none placeholder:font-normal placeholder:text-[#b0abc8] focus:ring-2 focus:ring-[#3525cd]/20"
            />
            {fieldErrors.name ? (
              <p className="mt-1 text-xs text-rose-700">{fieldErrors.name}</p>
            ) : null}
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {tc("fieldDescLabel")}
            </label>
            <textarea
              value={form.description}
              onChange={(e) =>
                setForm((p) => ({ ...p, description: e.target.value }))
              }
              rows={3}
              maxLength={500}
              placeholder={tc("fieldDescPlaceholder")}
              className="w-full rounded-xl border border-[#d2cee6] bg-white px-3 py-2 text-sm font-medium text-[#2a2640] outline-none placeholder:font-normal placeholder:text-[#b0abc8] focus:ring-2 focus:ring-[#3525cd]/20"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {tc("fieldAccessPolicyLabel")}
            </label>
            <select
              value={form.access_policy}
              onChange={(e) =>
                setForm((p) => ({
                  ...p,
                  access_policy: e.target.value as CollectionAccessPolicy,
                }))
              }
              className="h-9 w-full rounded-xl border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            >
              <option value="org_wide">{tc("policyOptOrgWide")}</option>
              <option value="admin_only">{tc("policyLabelAdminOnly")}</option>
              <option value="selected_roles">
                {tc("policyLabelSelectedRoles")}
              </option>
              <option value="selected_members">
                {tc("policyLabelSelectedMembers")}
              </option>
            </select>
            <p className="mt-1 text-xs text-[#7a768f]">
              {accessPolicyDescription(form.access_policy, tc)}
            </p>
          </div>

          {/* Dynamic toggle */}
          <div className="rounded-xl border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <label className="flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={form.is_dynamic}
                onChange={(e) =>
                  setForm((p) => ({ ...p, is_dynamic: e.target.checked }))
                }
                className="accent-[#3525cd]"
              />
              <div>
                <p className="text-sm font-semibold text-[#2a2640]">
                  Dynamic collection
                </p>
                <p className="text-[11px] text-[#6a6780]">
                  Membership is automatically updated based on document metadata
                  rules.
                </p>
              </div>
            </label>
            {form.is_dynamic ? (
              <div className="mt-3 border-t border-[#e4e1ee] pt-3">
                <DynamicRuleBuilder
                  collectionId={null}
                  value={form.rule_schema}
                  onChange={(next) =>
                    setForm((p) => ({ ...p, rule_schema: next }))
                  }
                />
              </div>
            ) : null}
          </div>

          {saveError ? (
            <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {saveError}
            </p>
          ) : null}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-[#d2cee6] bg-white px-4 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
            >
              {tc("cancel")}
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? tc("saving") : tc("save")}
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
  const tc = useTranslations("collections.page");
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(currentCollectionIds),
  );
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
      if (n.has(id)) {
        n.delete(id);
      } else {
        n.add(id);
      }
      return n;
    });
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-[#17172a]/40 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">
              {tc("assignTitle")}
            </h2>
            <p className="text-xs text-[#68647b]">{documentName}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            {tc("cancel")}
          </button>
        </div>

        {loadingCollections ? (
          <LoadingState compact title={tc("loadingCollections")} />
        ) : collectionList.length === 0 ? (
          <EmptyState
            compact
            title={tc("noCollectionsTitle")}
            description={tc("noCollectionsDesc")}
          />
        ) : (
          <ul className="max-h-64 space-y-1 overflow-auto">
            {collectionList.map((col) => (
              <li key={col.collection_id}>
                <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-[#e5e3f1] px-3 py-2 hover:bg-[#f5f3ff]">
                  <input
                    type="checkbox"
                    checked={selected.has(col.collection_id)}
                    onChange={() => toggle(col.collection_id)}
                    className="accent-[#3525cd]"
                  />
                  <span className="flex-1">
                    <span className="block text-sm font-semibold text-[#2a2640]">
                      {col.name}
                    </span>
                    <span className="block text-xs text-[#68647b]">
                      {tc("docCountLabel", { n: col.document_count })} ·{" "}
                      <span
                        className={`rounded-full border px-1.5 py-0.5 text-[10px] font-bold uppercase ${accessPolicyBadgeClass(col.access_policy)}`}
                      >
                        {accessPolicyLabel(col.access_policy, tc)}
                      </span>
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}

        {saveError ? (
          <p className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {saveError}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[#d2cee6] bg-white px-4 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
          >
            {tc("cancel")}
          </button>
          <button
            type="button"
            disabled={saving || loadingCollections}
            onClick={() => onSave(Array.from(selected))}
            className="rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? tc("saving") : tc("save")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Collections page ─────────────────────────────────────────────────────────

export function CollectionsPage() {
  const tc = useTranslations("collections.page");
  const queryClient = useQueryClient();
  const { state } = useAuthSession();
  const capabilities = resolveCollectionCapabilities(state.session?.role);
  const collectionsEnabled =
    getFrontendRuntimeConfig().features.collectionsEnabled;

  const [offset, setOffset] = useState(0);
  const [nameSearch, setNameSearch] = useState("");
  const [debouncedNameSearch, setDebouncedNameSearch] = useState("");
  const [accessFilter, setAccessFilter] = useState<
    CollectionAccessPolicy | "all"
  >("all");
  const [sortBy, setSortBy] = useState<"updated" | "name" | "docs">("updated");
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
    const t = setTimeout(() => {
      setDebouncedNameSearch(nameSearch);
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
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

  const allCollections = useMemo(
    () => collectionsQuery.data?.items ?? [],
    [collectionsQuery.data?.items],
  );
  const total = collectionsQuery.data?.total ?? 0;
  const listForbidden = isForbiddenError(collectionsQuery.error);

  // Client-side filter + sort
  const visibleCollections = useMemo(() => {
    let list =
      accessFilter === "all"
        ? allCollections
        : allCollections.filter((c) => c.access_policy === accessFilter);
    if (sortBy === "name")
      list = [...list].sort((a, b) => a.name.localeCompare(b.name));
    else if (sortBy === "docs")
      list = [...list].sort((a, b) => b.document_count - a.document_count);
    return list;
  }, [allCollections, accessFilter, sortBy]);

  // Summary metrics
  const totalDocs = allCollections.reduce((s, c) => s + c.document_count, 0);
  const indexedDocs = allCollections.reduce((s, c) => s + c.indexed_count, 0);
  const restrictedCount = allCollections.filter(
    (c) => c.access_policy !== "org_wide",
  ).length;

  const totalPages = Math.max(
    1,
    Math.ceil(Math.max(total, 1) / COLLECTIONS_PAGE_SIZE),
  );
  const currentPage = Math.floor(offset / COLLECTIONS_PAGE_SIZE) + 1;

  const createMutation = useMutation({
    mutationFn: (form: CollectionFormState) =>
      createCollection({
        name: form.name.trim(),
        description: form.description.trim() || null,
        access_policy: form.access_policy,
        is_dynamic: form.is_dynamic,
        rule_schema: form.is_dynamic ? form.rule_schema : null,
      }),
    onSuccess: async (result) => {
      setDialogMode(null);
      setDialogSaveError(null);
      setActionFeedback(tc("feedbackCreated", { name: result.name }));
      setActionRequestId(null);
      setSelectedCollectionId(result.collection_id);
      await invalidateAfterMutation(queryClient, "collection.create");
    },
    onError: (error) => {
      setDialogSaveError(getApiErrorMessage(error));
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({
      collectionId,
      form,
    }: {
      collectionId: string;
      form: CollectionFormState;
    }) => {
      const updated = await updateCollection(collectionId, {
        name: form.name.trim(),
        description: form.description.trim() || null,
        access_policy: form.access_policy,
      });
      if (form.is_dynamic) {
        await setCollectionRules(collectionId, form.rule_schema);
      }
      return updated;
    },
    onSuccess: async (result) => {
      setDialogMode(null);
      setDialogSaveError(null);
      setActionFeedback(tc("feedbackUpdated", { name: result.name }));
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
      if (selectedCollectionId === collectionId) setSelectedCollectionId(null);
      setActionFeedback(tc("feedbackDeleted"));
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
    if (!dialogMode || dialogMode === "create") return;
    setDialogSaveError(null);
    updateMutation.mutate({
      collectionId: dialogMode.collection.collection_id,
      form,
    });
  }
  function handleDeleteCollection(col: CollectionListItemResponse) {
    if (!window.confirm(tc("deleteConfirm", { name: col.name }))) return;
    deleteMutation.mutate(col.collection_id);
  }

  const isLoading = collectionsEnabled && collectionsQuery.isLoading;
  const isError = collectionsEnabled && collectionsQuery.isError;
  const showGrid = collectionsEnabled && !isLoading && !isError;

  return (
    <>
      <section className="min-h-screen space-y-6 px-4 py-6 lg:px-8 lg:py-8">
        {/* Page header */}
        <section>
          <span className="mb-1 block text-[11px] font-semibold tracking-widest text-[#3525cd] uppercase">
            {tc("eyebrow")}
          </span>
          <h2 className="text-3xl font-bold text-[#1b1b24]">
            {tc("pageTitle")}
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-[#464555]">
            {tc("pageDescription")}
          </p>
        </section>

        {/* Summary metrics */}
        {showGrid && allCollections.length > 0 ? (
          <SummaryMetrics
            total={total}
            totalDocs={totalDocs}
            indexedDocs={indexedDocs}
            restrictedCount={restrictedCount}
          />
        ) : null}

        {/* Toolbar */}
        <section className="flex flex-wrap items-center gap-3 rounded-xl border border-[#e4e1ee] bg-white p-2">
          <div className="relative min-w-[180px] flex-1">
            <span className="material-symbols-outlined absolute top-1/2 left-3 -translate-y-1/2 text-[20px] text-[#9993b8]">
              search
            </span>
            <input
              type="search"
              value={nameSearch}
              onChange={(e) => setNameSearch(e.target.value)}
              placeholder={tc("filterPlaceholder")}
              className="w-full border-none bg-transparent py-2 pl-10 text-sm text-[#1b1b24] outline-none focus:ring-0"
            />
          </div>
          <div className="hidden h-6 w-px bg-[#e4e1ee] sm:block" />
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-semibold whitespace-nowrap text-[#6a6780]">
              {tc("accessFilterLabel")}
            </span>
            <select
              value={accessFilter}
              onChange={(e) =>
                setAccessFilter(
                  e.target.value as CollectionAccessPolicy | "all",
                )
              }
              className="rounded-lg border-none bg-[#f5f3ff] py-1.5 pr-6 pl-2 text-sm text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            >
              <option value="all">{tc("filterAllPolicies")}</option>
              <option value="org_wide">{tc("policyLabelOrgWide")}</option>
              <option value="admin_only">{tc("policyLabelAdminOnly")}</option>
              <option value="selected_roles">
                {tc("policyLabelSelectedRoles")}
              </option>
              <option value="selected_members">
                {tc("policyLabelSelectedMembers")}
              </option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-semibold text-[#6a6780]">
              {tc("sortLabel")}
            </span>
            <select
              value={sortBy}
              onChange={(e) =>
                setSortBy(e.target.value as "updated" | "name" | "docs")
              }
              className="rounded-lg border-none bg-[#f5f3ff] py-1.5 pr-6 pl-2 text-sm text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
            >
              <option value="updated">{tc("sortLastUpdated")}</option>
              <option value="name">{tc("sortNameAZ")}</option>
              <option value="docs">{tc("sortDocCount")}</option>
            </select>
          </div>
          {capabilities.canCreate ? (
            <button
              type="button"
              onClick={() => {
                setDialogSaveError(null);
                setDialogMode("create");
              }}
              className="flex items-center gap-1 rounded-full bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition-all hover:shadow-lg hover:shadow-[#3525cd]/20 active:scale-95"
            >
              <span className="material-symbols-outlined text-[18px]">add</span>
              {tc("newCollectionButton")}
            </button>
          ) : null}
        </section>

        {/* Feedback banner */}
        {actionFeedback ? (
          <p
            role="status"
            className="rounded-xl border border-[#ddd7f6] bg-[#f3f1ff] px-4 py-2.5 text-sm text-[#3f3778]"
          >
            {actionFeedback}
            {actionRequestId
              ? ` ${tc("traceIdSuffix", { id: actionRequestId })}`
              : ""}
          </p>
        ) : null}

        {/* Error / empty states */}
        {!collectionsEnabled ? (
          <EmptyState
            title={tc("collectionsNotAvailableTitle")}
            description={tc("collectionsNotAvailableDesc")}
          />
        ) : null}
        {isLoading ? (
          <LoadingState title={tc("loadingCollectionsTitle")} />
        ) : null}
        {isError && isEndpointNotFoundError(collectionsQuery.error) ? (
          <EmptyState
            title={tc("apiNotDeployedTitle")}
            description={tc("apiNotDeployedDesc")}
          />
        ) : null}
        {isError &&
        !isEndpointNotFoundError(collectionsQuery.error) &&
        listForbidden ? (
          <ForbiddenState
            compact
            title={tc("listForbiddenTitle")}
            description={tc("listForbiddenDesc")}
            requestId={extractRequestIdFromError(collectionsQuery.error)}
          />
        ) : null}
        {isError &&
        !isEndpointNotFoundError(collectionsQuery.error) &&
        !listForbidden ? (
          <ErrorState
            error={collectionsQuery.error}
            description={getApiErrorMessage(collectionsQuery.error)}
            onRetry={() => void collectionsQuery.refetch()}
          />
        ) : null}

        {/* Collection grid */}
        {showGrid ? (
          <section className="grid grid-cols-1 gap-6 pb-8 md:grid-cols-2 xl:grid-cols-3">
            {visibleCollections.map((col) => (
              <CollectionCard
                key={col.collection_id}
                collection={col}
                isSelected={selectedCollectionId === col.collection_id}
                capabilities={capabilities}
                onSelect={() =>
                  setSelectedCollectionId(
                    selectedCollectionId === col.collection_id
                      ? null
                      : col.collection_id,
                  )
                }
                onEdit={(c) => {
                  setDialogSaveError(null);
                  setDialogMode({
                    mode: "edit",
                    collection: c as CollectionDetailResponse,
                  });
                }}
                onDelete={handleDeleteCollection}
                isDeleting={
                  deleteMutation.isPending &&
                  deleteMutation.variables === col.collection_id
                }
              />
            ))}

            {visibleCollections.length === 0 ? (
              <div className="col-span-full">
                <EmptyState
                  title={
                    nameSearch || accessFilter !== "all"
                      ? tc("noMatchTitle")
                      : tc("noCollectionsYetTitle")
                  }
                  description={
                    nameSearch || accessFilter !== "all"
                      ? undefined
                      : tc("noCollectionsYetDesc")
                  }
                  action={
                    nameSearch || accessFilter !== "all" ? (
                      <button
                        type="button"
                        onClick={() => {
                          setNameSearch("");
                          setAccessFilter("all");
                        }}
                        className="rounded-xl border border-[#d2cee6] bg-white px-3 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
                      >
                        {tc("clearFilters")}
                      </button>
                    ) : capabilities.canCreate ? (
                      <button
                        type="button"
                        onClick={() => {
                          setDialogSaveError(null);
                          setDialogMode("create");
                        }}
                        className="rounded-xl bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
                      >
                        {tc("newCollectionEmpty")}
                      </button>
                    ) : undefined
                  }
                />
              </div>
            ) : null}

            {visibleCollections.length > 0 && capabilities.canCreate ? (
              <NewCollectionCard
                onCreate={() => {
                  setDialogSaveError(null);
                  setDialogMode("create");
                }}
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
              onClick={() =>
                setOffset((p) => Math.max(0, p - COLLECTIONS_PAGE_SIZE))
              }
              className="flex items-center gap-1 rounded-xl border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="material-symbols-outlined text-[18px]">
                chevron_left
              </span>
              {tc("previousPage")}
            </button>
            <p className="text-sm text-[#68647b]">
              {tc("pageOf", { page: currentPage, total: totalPages })}
            </p>
            <button
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => setOffset((p) => p + COLLECTIONS_PAGE_SIZE)}
              className="flex items-center gap-1 rounded-xl border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {tc("nextPage")}
              <span className="material-symbols-outlined text-[18px]">
                chevron_right
              </span>
            </button>
          </div>
        ) : null}
      </section>

      {/* Drawer overlay + drawer */}
      {selectedCollectionId ? (
        <>
          <div
            className="fixed inset-0 z-40 bg-[#302f39]/20"
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
          title={tc("dialogTitleNew")}
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
          title={tc("dialogTitleEdit")}
          initial={{
            name: dialogMode.collection.name,
            description: dialogMode.collection.description ?? "",
            access_policy: dialogMode.collection.access_policy,
            is_dynamic: dialogMode.collection.is_dynamic,
            rule_schema: dialogMode.collection.rule_schema ?? emptyRuleSet(),
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
    </>
  );
}
