"use client";

import type { CollectionDetailResponse } from "@/lib/api/collections";

import { PolicyEditor } from "@/components/collections/PolicyEditor";
import {
  accessPolicyDescription,
  accessPolicyIcon,
  accessPolicyLabel,
  formatRelativeDate,
  pickIcon,
  type CollectionCapabilities,
} from "@/components/collections/collection-format";
import type { CollectionDrawerController } from "@/components/collections/useCollectionDetailDrawer";

/** Drawer hero, dynamic rules, indexing health, and access policy. */
export function CollectionDrawerOverview({
  ctl,
  detail,
  capabilities,
}: {
  ctl: CollectionDrawerController;
  detail: CollectionDetailResponse;
  capabilities: CollectionCapabilities;
}) {
  const { tc, refreshRulesMutation, progress, collectionId } = ctl;
  return (
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
                {refreshRulesMutation.isPending ? "Refreshing…" : "Refresh now"}
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
                    <span className="text-[#6a6780]">{cond.operator}</span>{" "}
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
    </>
  );
}
