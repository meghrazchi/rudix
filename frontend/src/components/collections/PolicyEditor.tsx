"use client";

import { useEffect, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  getCollectionPolicy,
  updateCollectionPolicy,
  type CollectionAccessGrant,
  type CollectionAccessPolicy,
} from "@/lib/api/collections";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import {
  getTeamCapabilities,
  listTeamMembers,
  type TeamMember,
} from "@/lib/api/team";

import { accessPolicyDescription } from "@/components/collections/collection-format";

type PolicyEditorProps = {
  collectionId: string;
  collectionName: string;
};

/** Access policy editor with role and member grants. */
export function PolicyEditor({
  collectionId,
  collectionName,
}: PolicyEditorProps) {
  const tc = useTranslations("collections.page");
  const queryClient = useQueryClient();
  const teamCapabilities = getTeamCapabilities();

  const policyQuery = useQuery({
    queryKey: queryKeys.collections.policy(collectionId),
    queryFn: () => getCollectionPolicy(collectionId),
  });

  const membersQuery = useQuery({
    queryKey: queryKeys.teamMemberPolicyPicker,
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
