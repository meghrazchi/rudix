"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { getApiErrorMessage } from "@/lib/api/errors";
import {
  listSyncConflicts,
  resolveSyncConflict,
  type SyncConflict,
  type SyncConflictStatus,
} from "@/lib/api/connector-sync";
import { queryKeys } from "@/lib/api/query";

// ── Helpers ───────────────────────────────────────────────────────────────────

const CONFLICT_TYPE_ICON: Record<string, string> = {
  acl_changed: "lock_person",
  renamed: "drive_file_rename_outline",
  moved: "drive_file_move",
  permission_revoked: "no_accounts",
};

const STATUS_BADGE: Record<string, string> = {
  open: "bg-amber-100 text-amber-800 border-amber-200",
  resolved: "bg-emerald-100 text-emerald-800 border-emerald-200",
  dismissed: "bg-[#e4e1ee] text-[#464555] border-[#d7d4e8]",
};

function ConflictTypeChip({ type }: { type: string }) {
  const t = useTranslations("connectors.detail.conflicts");
  const label = t.has(`types.${type}`) ? t(`types.${type}`) : type;
  const icon = CONFLICT_TYPE_ICON[type] ?? "warning";
  const isRevoked = type === "permission_revoked";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold ${
        isRevoked
          ? "border-rose-200 bg-rose-100 text-rose-700"
          : "border-[#d7d4e8] bg-[#f0ecf9] text-[#3525cd]"
      }`}
    >
      <span className="material-symbols-outlined text-[13px]">{icon}</span>
      {label}
    </span>
  );
}

// ── Conflict row ──────────────────────────────────────────────────────────────

function ConflictRow({
  conflict,
  connectionId,
  onResolved,
}: {
  conflict: SyncConflict;
  connectionId: string;
  onResolved: () => void;
}) {
  const t = useTranslations("connectors.detail.conflicts");
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resolveMutation = useMutation({
    mutationFn: ({
      resolution,
      strategy,
    }: {
      resolution: "resolved" | "dismissed";
      strategy?: string;
    }) =>
      resolveSyncConflict(connectionId, conflict.id, {
        resolution,
        resolution_strategy: strategy,
      }),
    onSuccess: () => {
      setError(null);
      onResolved();
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const isOpen = conflict.status === "open";
  const badge = STATUS_BADGE[conflict.status] ?? STATUS_BADGE.open;

  return (
    <div className="rounded-xl border border-[#d7d4e8] bg-white">
      <div className="flex items-start justify-between gap-3 p-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <ConflictTypeChip type={conflict.conflict_type} />
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${badge}`}
            >
              {t.has(`statuses.${conflict.status}`)
                ? t(`statuses.${conflict.status}`)
                : conflict.status}
            </span>
          </div>
          <p
            className="truncate font-mono text-[11px] text-[#464555]"
            title={conflict.provider_item_id}
          >
            {conflict.provider_item_id}
          </p>
          <p className="mt-0.5 text-[10px] text-[#777587]">
            {new Date(conflict.created_at).toLocaleString()}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="rounded border border-[#d7d4e8] p-1 text-[#464555] hover:bg-[#f5f2ff]"
            aria-label={expanded ? t("collapse") : t("expand")}
          >
            <span className="material-symbols-outlined text-[16px]">
              {expanded ? "expand_less" : "expand_more"}
            </span>
          </button>
          {isOpen && (
            <>
              <button
                type="button"
                disabled={resolveMutation.isPending}
                onClick={() =>
                  resolveMutation.mutate({
                    resolution: "resolved",
                    strategy: "acknowledge",
                  })
                }
                className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-bold text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("resolve")}
              </button>
              <button
                type="button"
                disabled={resolveMutation.isPending}
                onClick={() =>
                  resolveMutation.mutate({ resolution: "dismissed" })
                }
                className="rounded border border-[#d7d4e8] px-2 py-1 text-[11px] font-bold text-[#464555] hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("dismiss")}
              </button>
            </>
          )}
        </div>
      </div>

      {expanded && (
        <div className="border-t border-[#e8e5f3] bg-[#faf9fe] px-3 pt-2 pb-3">
          {Object.entries(conflict.conflict_detail).length === 0 ? (
            <p className="text-[11px] text-[#777587]">{t("noDetail")}</p>
          ) : (
            <dl className="space-y-1">
              {Object.entries(conflict.conflict_detail).map(([k, v]) => (
                <div key={k} className="flex gap-2 text-[11px]">
                  <dt className="w-32 shrink-0 font-bold text-[#5d58a8]">
                    {k.replace(/_/g, " ")}
                  </dt>
                  <dd className="font-mono break-all text-[#2a2640]">
                    {String(v)}
                  </dd>
                </div>
              ))}
              {conflict.resolution_strategy && (
                <div className="flex gap-2 text-[11px]">
                  <dt className="w-32 shrink-0 font-bold text-[#5d58a8]">
                    strategy
                  </dt>
                  <dd className="font-mono text-[#2a2640]">
                    {conflict.resolution_strategy}
                  </dd>
                </div>
              )}
            </dl>
          )}
          {conflict.resolved_at && (
            <p className="mt-2 text-[10px] text-[#777587]">
              {t("resolvedAt", {
                date: new Date(conflict.resolved_at).toLocaleString(),
              })}
            </p>
          )}
        </div>
      )}

      {error && <p className="px-3 pb-2 text-[11px] text-rose-600">{error}</p>}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

type Props = { connectionId: string };

export function ConnectorConflictPanel({ connectionId }: Props) {
  const t = useTranslations("connectors.detail.conflicts");
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<SyncConflictStatus | undefined>("open");

  const conflictsQuery = useQuery({
    queryKey: queryKeys.connectorConflicts(connectionId, filter),
    queryFn: () => listSyncConflicts(connectionId, filter, 50),
  });

  const conflicts = conflictsQuery.data?.items ?? [];
  const total = conflictsQuery.data?.total ?? 0;
  const openCount =
    filter === "open"
      ? total
      : conflicts.filter((c) => c.status === "open").length;

  function invalidate() {
    queryClient.invalidateQueries({
      queryKey: queryKeys.connectorConflicts(connectionId),
    });
  }

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h4 className="text-lg font-bold text-[#2a2640]">{t("title")}</h4>
          {openCount > 0 && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
              {t("openCount", { count: openCount })}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => conflictsQuery.refetch()}
          disabled={conflictsQuery.isFetching}
          className="rounded border border-[#d7d4e8] p-1 text-[#464555] hover:bg-[#f5f2ff] disabled:opacity-40"
          aria-label={t("refresh")}
        >
          <span
            className={`material-symbols-outlined text-[18px] ${conflictsQuery.isFetching ? "animate-spin" : ""}`}
          >
            refresh
          </span>
        </button>
      </div>

      {/* Filter tabs */}
      <div className="mb-3 flex gap-1">
        {(
          [
            { value: "open", label: t("statuses.open") },
            { value: "resolved", label: t("statuses.resolved") },
            { value: "dismissed", label: t("statuses.dismissed") },
            { value: undefined, label: t("all") },
          ] as { value: SyncConflictStatus | undefined; label: string }[]
        ).map(({ value, label }) => (
          <button
            key={label}
            type="button"
            onClick={() => setFilter(value)}
            className={`rounded px-2.5 py-1 text-[11px] font-bold transition-colors ${
              filter === value
                ? "bg-[#3525cd] text-white"
                : "text-[#464555] hover:bg-[#f0ecf9]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      {conflictsQuery.isLoading ? (
        <p className="py-4 text-center text-sm text-[#68647b]">
          {t("loading")}
        </p>
      ) : conflictsQuery.isError ? (
        <p className="py-4 text-center text-sm text-rose-600">
          {t("loadError")}
        </p>
      ) : conflicts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-full border border-emerald-200 bg-emerald-100 text-emerald-600">
            <span className="material-symbols-outlined text-[28px]">
              check_circle
            </span>
          </div>
          <p className="font-bold text-[#2a2640]">
            {filter === "open" ? t("noOpen") : t("none")}
          </p>
          <p className="mt-1 text-sm text-[#777587]">
            {filter === "open" ? t("clean") : t("nothingForFilter")}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {conflicts.map((conflict) => (
            <ConflictRow
              key={conflict.id}
              conflict={conflict}
              connectionId={connectionId}
              onResolved={invalidate}
            />
          ))}
          {total > conflicts.length && (
            <p className="pt-1 text-center text-[11px] text-[#777587]">
              {t("showing", { shown: conflicts.length, total })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
