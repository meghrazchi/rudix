"use client";

import type { DocumentSortBy, SortOrder } from "@/lib/api/documents";

import type {
  FileTypeFilter,
  FreshnessFilter,
  QualityFilter,
  StatusFilter,
} from "@/components/documents/list/documents-list-format";
import type { DocumentsPageController } from "@/components/documents/list/useDocumentsPage";

/** Search, type, status, freshness, quality, and sort controls with the row count. */
export function DocumentsFilterBar({ ctl }: { ctl: DocumentsPageController }) {
  const {
    statusFilterOptions,
    freshnessFilterOptions,
    qualityFilterOptions,
    sortByOptions,
    fileTypeFilterOptions,
    tp,
    statusFilter,
    setStatusFilter,
    freshnessFilter,
    setFreshnessFilter,
    qualityFilter,
    setQualityFilter,
    sortBy,
    setSortBy,
    sortOrder,
    setSortOrder,
    setOffset,
    filenameSearch,
    setFilenameSearch,
    fileTypeFilter,
    setFileTypeFilter,
    documents,
    totalDocumentsCount,
  } = ctl;
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 rounded-xl border border-[#e5e3f1] bg-[#fcfbff] p-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {tp("searchLabel")}
          <div className="relative">
            <span className="material-symbols-outlined pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-base text-[#9993b8]">
              search
            </span>
            <input
              type="search"
              value={filenameSearch}
              onChange={(event) => setFilenameSearch(event.target.value)}
              placeholder={tp("searchPlaceholder")}
              className="h-9 w-44 rounded-lg border border-[#d2cee6] bg-white pr-3 pl-8 text-sm font-medium text-[#2a2640] transition-[width] duration-200 outline-none placeholder:font-normal placeholder:text-[#b0abc8] focus:w-64 focus:ring-2 focus:ring-[#3525cd]/20"
            />
          </div>
        </label>
        <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {tp("typeLabel")}
          <select
            value={fileTypeFilter}
            onChange={(event) => {
              setOffset(0);
              setFileTypeFilter(event.target.value as FileTypeFilter);
            }}
            className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
          >
            {fileTypeFilterOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {tp("statusLabel")}
          <select
            value={statusFilter}
            onChange={(event) => {
              setOffset(0);
              setStatusFilter(event.target.value as StatusFilter);
            }}
            className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
          >
            {statusFilterOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {tp("freshnessLabel")}
          <select
            value={freshnessFilter}
            onChange={(event) => {
              setOffset(0);
              setFreshnessFilter(event.target.value as FreshnessFilter);
            }}
            className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
          >
            {freshnessFilterOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {tp("qualityLabel")}
          <select
            value={qualityFilter}
            onChange={(event) => {
              setOffset(0);
              setQualityFilter(event.target.value as QualityFilter);
            }}
            className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
          >
            {qualityFilterOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {tp("sortLabel")}
          <select
            value={sortBy}
            onChange={(event) => {
              setOffset(0);
              setSortBy(event.target.value as DocumentSortBy);
            }}
            className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
          >
            {sortByOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {tp("orderLabel")}
          <select
            value={sortOrder}
            onChange={(event) => {
              setOffset(0);
              setSortOrder(event.target.value as SortOrder);
            }}
            className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
          >
            <option value="desc">{tp("orderDesc")}</option>
            <option value="asc">{tp("orderAsc")}</option>
          </select>
        </label>
      </div>
      <p className="text-sm text-[#68647b]">
        {tp("showing", {
          shown: documents.length,
          total: totalDocumentsCount,
        })}
      </p>
    </div>
  );
}
