"use client";

import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { EmptyState } from "@/components/states/EmptyState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  statusBadgeClass,
  formatDate,
} from "@/components/admin/team/teamShared";
import { RoleChangeRow } from "@/components/admin/team/RoleChangeRow";
import { useTeamController } from "@/components/admin/team/useTeamController";

export function MembersSection({
  ctl,
}: {
  ctl: ReturnType<typeof useTeamController>;
}) {
  const {
    t,
    locale,
    searchInput,
    setSearchInput,
    searchQuery,
    roleFilter,
    setRoleFilter,
    statusFilter,
    setStatusFilter,
    setPageIndex,
    setConfirmAction,
    setSetPasswordMember,
    capabilities,
    offset,
    membersQuery,
    updateRoleMutation,
    isMutating,
    members,
    membersTotal,
    hasPrev,
    hasNext,
  } = ctl;

  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#ebe8f7] px-5 py-4">
        <h2 className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
          {t("members")}
          {membersTotal > 0 && (
            <span className="ml-1.5 rounded-full bg-[#f0edf9] px-2 py-0.5 text-xs font-semibold text-[#5a5278]">
              {membersTotal}
            </span>
          )}
        </h2>

        {/* Search */}
        <div className="relative ml-auto">
          <svg
            className="absolute top-1/2 left-2.5 -translate-y-1/2 text-[#999]"
            width="13"
            height="13"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder={t("searchPlaceholder")}
            aria-label={t("searchMembers")}
            className="h-8 w-52 rounded-lg border border-[#d2cee6] bg-white pr-3 pl-7 text-xs text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </div>

        {/* Role filter */}
        <select
          aria-label={t("filterByRole")}
          value={roleFilter}
          onChange={(e) => {
            setRoleFilter(e.target.value);
            setPageIndex(0);
          }}
          className="h-8 rounded-lg border border-[#d2cee6] px-2 text-xs text-[#2f2a46] outline-none focus:border-[#3525cd]"
        >
          <option value="">{t("allRoles")}</option>
          <option value="owner">{t("roles.owner")}</option>
          <option value="admin">{t("roles.admin")}</option>
          <option value="member">{t("roles.member")}</option>
          <option value="viewer">{t("roles.viewer")}</option>
          <option value="reviewer">{t("roles.reviewer")}</option>
          <option value="developer">{t("roles.developer")}</option>
        </select>

        {/* Status filter */}
        <select
          aria-label={t("filterByStatus")}
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPageIndex(0);
          }}
          className="h-8 rounded-lg border border-[#d2cee6] px-2 text-xs text-[#2f2a46] outline-none focus:border-[#3525cd]"
        >
          <option value="">{t("allStatuses")}</option>
          <option value="active">{t("statuses.active")}</option>
          <option value="invited">{t("statuses.invited")}</option>
        </select>
      </div>

      {membersQuery.isLoading ? (
        <div className="p-8">
          <LoadingState compact title={t("loading.members")} />
        </div>
      ) : membersQuery.isError ? (
        <div className="p-6">
          <ErrorState
            compact
            error={membersQuery.error}
            description={getApiErrorMessage(membersQuery.error)}
            onRetry={() => void membersQuery.refetch()}
          />
        </div>
      ) : members.length === 0 ? (
        <div className="p-8">
          <EmptyState
            compact
            title={
              searchQuery
                ? t("empty.membersFiltered", { search: searchQuery })
                : t("empty.members")
            }
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-[#f0edf9] text-sm">
            <thead className="bg-[#faf9ff]">
              <tr>
                {["name", "email", "role", "status", "joined", "actions"].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-4 py-2.5 text-left text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase"
                    >
                      {t(`columns.${h}`)}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#f8f6ff] bg-white">
              {members.map((member) => (
                <tr key={member.member_id} className="hover:bg-[#fdfcff]">
                  <td className="px-4 py-3 font-medium text-[#2f2a46]">
                    {member.name}
                  </td>
                  <td className="px-4 py-3 text-[#4d4963]">{member.email}</td>
                  <td className="px-4 py-3">
                    <RoleChangeRow
                      member={member}
                      isDisabled={isMutating || !capabilities.updateRoleEnabled}
                      onRoleChange={(memberId, role) =>
                        updateRoleMutation.mutate({ memberId, role })
                      }
                    />
                  </td>
                  <td className="px-4 py-3">
                    <span className={statusBadgeClass(member.status)}>
                      {t(`statuses.${member.status}`)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[#7a7690]">
                    {formatDate(member.created_at, locale)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        disabled={isMutating}
                        onClick={() => setSetPasswordMember(member)}
                        className="rounded border border-[#d2cee6] px-2 py-0.5 text-[11px] font-semibold text-[#3f3b58] hover:bg-[#f8f6ff] disabled:opacity-60"
                      >
                        {t("password.title")}
                      </button>
                      {member.role !== "owner" && (
                        <>
                          <button
                            type="button"
                            disabled={isMutating}
                            onClick={() =>
                              setConfirmAction({ kind: "deactivate", member })
                            }
                            className="rounded border border-amber-300 px-2 py-0.5 text-[11px] font-semibold text-amber-700 hover:bg-amber-50 disabled:opacity-60"
                          >
                            {t("actions.deactivate")}
                          </button>
                          <button
                            type="button"
                            disabled={
                              isMutating || !capabilities.removeMemberEnabled
                            }
                            onClick={() =>
                              setConfirmAction({ kind: "remove", member })
                            }
                            className="rounded border border-rose-300 px-2 py-0.5 text-[11px] font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-60"
                          >
                            {t("actions.remove")}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {membersTotal > 0 && (
        <div className="flex items-center justify-between border-t border-[#ebe8f7] bg-[#fcfbff] px-5 py-2.5">
          <p className="text-xs text-[#6a6780]">
            {t("pagination.range", {
              start: offset + 1,
              end: Math.min(offset + members.length, membersTotal),
              total: membersTotal,
            })}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPageIndex((p) => Math.max(0, p - 1))}
              disabled={!hasPrev || membersQuery.isFetching}
              className="rounded border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#4b4662] hover:bg-[#f8f6ff] disabled:opacity-60"
            >
              {t("pagination.previous")}
            </button>
            <button
              type="button"
              onClick={() => setPageIndex((p) => p + 1)}
              disabled={!hasNext || membersQuery.isFetching}
              className="rounded border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#4b4662] hover:bg-[#f8f6ff] disabled:opacity-60"
            >
              {t("pagination.next")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
