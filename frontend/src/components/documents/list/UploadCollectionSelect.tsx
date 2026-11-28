"use client";

import { useTranslations } from "next-intl";

import type { CollectionListItemResponse } from "@/lib/api/collections";
import type { CollectionSearchList } from "@/components/collections/useCollectionSearchList";
import { LoadMoreFooter } from "@/components/pagination/LoadMoreFooter";
import { PickerSearchInput } from "@/components/pagination/PickerSearchInput";

/**
 * Collection select of the upload modal. With `collectionSearch` it searches
 * collections by name on the server and pages with "Load more".
 */
export function UploadCollectionSelect({
  collections,
  collectionSearch,
  value,
  onChange,
  disabled,
}: {
  collections: CollectionListItemResponse[];
  collectionSearch?: CollectionSearchList;
  value: string;
  onChange: (collectionId: string) => void;
  disabled: boolean;
}) {
  const t = useTranslations("documents.uploadModal");
  const tc = useTranslations("collections.page");
  const tCommon = useTranslations("common");
  const searching = Boolean(collectionSearch?.search.trim());

  if (collections.length === 0 && !searching) {
    return null;
  }

  return (
    <div className="sm:col-span-2">
      <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {t("collectionLabel")}
      </label>
      {collectionSearch ? (
        <PickerSearchInput
          className="mb-2"
          value={collectionSearch.search}
          onChange={collectionSearch.setSearch}
          placeholder={tc("filterPlaceholder")}
          ariaLabel={`${tCommon("search")}: ${t("collectionLabel")}`}
          disabled={disabled}
        />
      ) : null}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
        disabled={disabled}
      >
        <option value="">{t("collectionNone")}</option>
        {collections.map((c) => (
          <option key={c.collection_id} value={c.collection_id}>
            {c.name}
          </option>
        ))}
      </select>
      {collectionSearch ? (
        <LoadMoreFooter
          shown={collections.length}
          total={collectionSearch.total}
          hasMore={collectionSearch.hasMore}
          isLoadingMore={collectionSearch.isLoadingMore}
          onLoadMore={collectionSearch.loadMore}
          searchHint
        />
      ) : null}
    </div>
  );
}
