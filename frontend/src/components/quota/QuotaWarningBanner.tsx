"use client";

import { useQuery } from "@tanstack/react-query";

import {
  getMyQuotaUsage,
  type QuotaType,
  type QuotaUsageItem,
} from "@/lib/api/quotas";
import { queryKeys } from "@/lib/api/query";
import { useAuthSession } from "@/lib/use-auth-session";

type Severity = "warning" | "error";

function usageItemSeverity(item: QuotaUsageItem): Severity | null {
  if (item.over_hard_limit) return "error";
  if (item.over_soft_limit || item.near_limit) return "warning";
  return null;
}

const QUOTA_TYPE_LABELS: Partial<Record<QuotaType, string>> = {
  uploads: "uploads",
  questions: "chat questions",
  tokens: "tokens",
  storage_bytes: "storage",
  evaluations: "evaluations",
  api_calls: "API calls",
  connectors: "connectors",
  agent_runs: "agent runs",
};

function bannerMessage(
  items: QuotaUsageItem[],
): { severity: Severity; text: string } | null {
  const overHard = items.filter((i) => i.over_hard_limit);
  const overSoft = items.filter((i) => i.over_soft_limit && !i.over_hard_limit);
  const near = items.filter(
    (i) => i.near_limit && !i.over_soft_limit && !i.over_hard_limit,
  );

  if (overHard.length > 0) {
    const names = overHard
      .map((i) => QUOTA_TYPE_LABELS[i.quota_type as QuotaType] ?? i.quota_type)
      .join(", ");
    return {
      severity: "error",
      text: `Hard limit reached for ${names}. Further actions are blocked until the limit resets.`,
    };
  }
  if (overSoft.length > 0) {
    const names = overSoft
      .map((i) => QUOTA_TYPE_LABELS[i.quota_type as QuotaType] ?? i.quota_type)
      .join(", ");
    return {
      severity: "warning",
      text: `Soft limit exceeded for ${names}. Contact your admin to increase limits.`,
    };
  }
  if (near.length > 0) {
    const names = near
      .map((i) => QUOTA_TYPE_LABELS[i.quota_type as QuotaType] ?? i.quota_type)
      .join(", ");
    return {
      severity: "warning",
      text: `Approaching quota limit for ${names}.`,
    };
  }
  return null;
}

type QuotaWarningBannerProps = {
  /** Restrict banner to specific quota types. Shows all when omitted. */
  filterTypes?: QuotaType[];
  className?: string;
};

/**
 * Drop-in banner for chat, upload, and other pages.
 * Silently hides when no limits are near — no placeholder rendered.
 */
export function QuotaWarningBanner({
  filterTypes,
  className,
}: QuotaWarningBannerProps) {
  const { state } = useAuthSession();
  const isAuthenticated = state.status === "authenticated";

  const usageQuery = useQuery({
    queryKey: queryKeys.quotas.myUsage,
    queryFn: () => getMyQuotaUsage(),
    enabled: isAuthenticated,
    // Low-noise: don't retry aggressively — quota data is supplementary
    retry: 1,
    staleTime: 60_000,
  });

  if (!isAuthenticated || !usageQuery.data) return null;

  const items = filterTypes
    ? usageQuery.data.quota_usage.filter((i) =>
        filterTypes.includes(i.quota_type as QuotaType),
      )
    : usageQuery.data.quota_usage;

  const msg = bannerMessage(items);
  if (!msg) return null;

  const isError = msg.severity === "error";

  return (
    <div
      role="alert"
      className={[
        "flex items-start gap-3 rounded-md px-4 py-3 text-sm",
        isError
          ? "bg-red-50 text-red-800 dark:bg-red-900/20 dark:text-red-300"
          : "bg-amber-50 text-amber-800 dark:bg-amber-900/20 dark:text-amber-300",
        className ?? "",
      ].join(" ")}
    >
      <span aria-hidden className="mt-0.5 shrink-0 text-base">
        {isError ? "🚫" : "⚠️"}
      </span>
      <span>{msg.text}</span>
    </div>
  );
}
