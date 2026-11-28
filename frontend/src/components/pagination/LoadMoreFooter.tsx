"use client";

import { useTranslations } from "next-intl";

type LoadMoreFooterProps = {
  shown: number;
  total: number | null;
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
  /** Adds "Search to find more" while more rows exist (for pickers). */
  searchHint?: boolean;
  className?: string;
};

/** Row count, a "Load more" button, and a polite live region for loading. */
export function LoadMoreFooter({
  shown,
  total,
  hasMore,
  isLoadingMore,
  onLoadMore,
  searchHint = false,
  className,
}: LoadMoreFooterProps) {
  const t = useTranslations("common.pagination");
  const knownTotal = total ?? (hasMore ? null : shown);

  return (
    <div
      className={
        className ??
        "flex flex-wrap items-center justify-between gap-3 px-1 py-2 text-xs text-[#6a6780]"
      }
    >
      <p aria-live="polite" data-testid="load-more-count">
        {knownTotal === null
          ? null
          : t("showingCount", { shown, total: knownTotal })}
        {searchHint && hasMore ? (
          <span className="ms-1">· {t("searchToFind")}</span>
        ) : null}
      </p>
      <span role="status" aria-live="polite" className="sr-only">
        {isLoadingMore ? t("loadingMore") : ""}
      </span>
      {hasMore ? (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={isLoadingMore}
          aria-busy={isLoadingMore}
          className="rounded-lg border border-[#d2cee6] bg-white px-3 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isLoadingMore ? t("loadingMore") : t("loadMore")}
        </button>
      ) : null}
    </div>
  );
}
