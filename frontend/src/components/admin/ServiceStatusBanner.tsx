"use client";

import { useQuery } from "@tanstack/react-query";

import { getStatusBanner } from "@/lib/api/incidents";
import { queryKeys } from "@/lib/api/query";
import { useAuthSession } from "@/lib/use-auth-session";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-rose-600 text-white",
  high: "bg-orange-500 text-white",
  medium: "bg-amber-500 text-white",
  low: "bg-sky-500 text-white",
};

export function ServiceStatusBanner() {
  const { state } = useAuthSession();
  const isAuthenticated = state.status === "authenticated";

  const bannerQuery = useQuery({
    queryKey: queryKeys.statusBanner,
    queryFn: getStatusBanner,
    enabled: isAuthenticated,
    refetchInterval: 120_000,
    staleTime: 60_000,
  });

  const banner = bannerQuery.data;
  if (!banner) return null;
  if (!banner.has_active_incident && !banner.has_active_maintenance)
    return null;

  const isMaintenance = banner.has_active_maintenance;
  const severity = banner.highest_severity ?? "medium";
  const colorClass = isMaintenance
    ? "bg-slate-700 text-white"
    : (SEVERITY_COLORS[severity] ?? SEVERITY_COLORS.medium);

  const label = isMaintenance ? "Maintenance" : "Incident";
  const message =
    banner.banner_message ??
    (isMaintenance
      ? "Scheduled maintenance is in progress."
      : "We are investigating a service issue.");

  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-center justify-center gap-2 px-4 py-2 text-xs font-semibold ${colorClass}`}
    >
      <span className="rounded bg-white/20 px-1.5 py-0.5 text-[10px] font-bold tracking-wide uppercase">
        {label}
      </span>
      <span>{message}</span>
    </div>
  );
}
