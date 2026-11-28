"use client";

import type { CollectionAccessPolicy } from "@/lib/api/collections";

import type { CollectionsPageController } from "@/components/collections/useCollectionsPage";

/** Name search, access filter, sort, and the new-collection button. */
export function CollectionsToolbar({
  ctl,
}: {
  ctl: CollectionsPageController;
}) {
  const {
    tc,
    capabilities,
    nameSearch,
    setNameSearch,
    accessFilter,
    setAccessFilter,
    sortBy,
    setSortBy,
    setDialogMode,
    setDialogSaveError,
  } = ctl;
  return (
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
            setAccessFilter(e.target.value as CollectionAccessPolicy | "all")
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
  );
}
