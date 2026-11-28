"use client";

import { useTranslations } from "next-intl";

import type { CollectionListItemResponse } from "@/lib/api/collections";

import {
  accessPolicyBadgeClass,
  accessPolicyLabel,
  formatRelativeDate,
  pickIcon,
  type CollectionCapabilities,
} from "@/components/collections/collection-format";

// ── Summary metrics ─────────────────────────────────────────────────────────

export function SummaryMetrics({
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
export function CollectionCard({
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

export function NewCollectionCard({ onCreate }: { onCreate: () => void }) {
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
