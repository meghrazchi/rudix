"use client";

import { useEffect, useRef, useState } from "react";

import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/states/EmptyState";
import { LoadingState } from "@/components/states/LoadingState";
import type { CollectionListItemResponse } from "@/lib/api/collections";

import {
  accessPolicyBadgeClass,
  accessPolicyLabel,
} from "@/components/collections/collection-format";

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
