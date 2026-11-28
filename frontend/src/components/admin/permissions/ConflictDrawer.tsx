"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import {
  getConflict,
  updateConflictStatus,
  type ConflictSeverity,
  type ConflictStatus,
} from "@/lib/api/conflicts";

// ── Severity badge ─────────────────────────────────────────────────────────────

export const SEVERITY_STYLES: Record<ConflictSeverity, string> = {
  info: "bg-sky-50 text-sky-700 border border-sky-100",
  warning: "bg-amber-50 text-amber-700 border border-amber-100",
  blocking: "bg-orange-50 text-orange-700 border border-orange-100",
  security_risk: "bg-red-50 text-red-700 border border-red-100",
};

export function SeverityBadge({ severity }: { severity: ConflictSeverity }) {
  const t = useTranslations("adminPermissions");
  const cls = SEVERITY_STYLES[severity] ?? "bg-slate-50 text-slate-700";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${cls}`}
    >
      {t(`severities.${severity}`)}
    </span>
  );
}

export function ConflictStatusBadge({ status }: { status: ConflictStatus }) {
  const t = useTranslations("adminPermissions");
  const cls =
    status === "open"
      ? "bg-red-50 text-red-700 border border-red-100"
      : status === "investigating"
        ? "bg-amber-50 text-amber-700 border border-amber-100"
        : status === "resolved"
          ? "bg-emerald-50 text-emerald-700 border border-emerald-100"
          : "bg-slate-50 text-slate-600 border border-slate-100";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${cls}`}
    >
      {t(`conflictStatuses.${status}`)}
    </span>
  );
}

// ── Conflict detail drawer ─────────────────────────────────────────────────────

export function ConflictDrawer({
  conflictId,
  onClose,
  canManage,
}: {
  conflictId: string;
  onClose: () => void;
  canManage: boolean;
}) {
  const t = useTranslations("adminPermissions");
  const queryClient = useQueryClient();
  const {
    data: conflict,
    isLoading,
    error,
  } = useQuery({
    queryKey: queryKeys.adminPermissions.conflict(conflictId),
    queryFn: () => getConflict(conflictId),
  });

  const [statusError, setStatusError] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const statusMutation = useMutation({
    mutationFn: (s: "investigating" | "resolved" | "dismissed") =>
      updateConflictStatus(conflictId, {
        status: s,
        resolution_note: note || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminPermissions.conflicts,
      });
      onClose();
    },
    onError: (err) => setStatusError(getApiErrorMessage(err)),
  });

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/30 rtl:justify-start"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="relative flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#d7d4e8] px-6 py-4">
          <h2 className="text-base font-semibold text-[#2a2640]">
            {t("conflicts.detailTitle")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-[#68647b] hover:text-[#2a2640]"
          >
            ✕
          </button>
        </div>

        {isLoading ? (
          <div className="flex-1 p-6">
            <LoadingState />
          </div>
        ) : error ? (
          <div className="p-6">
            <ErrorState description={getApiErrorMessage(error)} />
          </div>
        ) : conflict ? (
          <div className="flex-1 space-y-6 p-6">
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <p className="text-xs font-bold text-[#5d58a8] uppercase">
                  {conflict.conflict_type.replace(/_/g, " ")}
                </p>
                <p className="mt-1 text-sm text-[#2a2640]">
                  {conflict.conflict_summary ?? t("conflicts.noSummary")}
                </p>
              </div>
              <div className="flex flex-col items-end gap-1">
                <SeverityBadge severity={conflict.severity} />
                <ConflictStatusBadge status={conflict.status} />
              </div>
            </div>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-[#d7d4e8] bg-[#f9f8ff] p-4 text-xs">
              <div>
                <dt className="font-bold text-[#5d58a8] uppercase">
                  {t("columns.subject")}
                </dt>
                <dd className="mt-0.5 font-mono break-all text-[#2a2640]">
                  {conflict.subject_value}
                </dd>
              </div>
              <div>
                <dt className="font-bold text-[#5d58a8] uppercase">
                  {t("columns.resource")}
                </dt>
                <dd className="mt-0.5 font-mono break-all text-[#2a2640]">
                  {conflict.resource_type}
                  {conflict.resource_id
                    ? `/${conflict.resource_id}`
                    : ` ${t("access.allParenthetical")}`}
                </dd>
              </div>
              <div>
                <dt className="font-bold text-[#5d58a8] uppercase">
                  {t("columns.action")}
                </dt>
                <dd className="mt-0.5 text-[#2a2640]">{conflict.action}</dd>
              </div>
              <div>
                <dt className="font-bold text-[#5d58a8] uppercase">
                  {t("columns.detected")}
                </dt>
                <dd className="mt-0.5 text-[#68647b]">
                  {new Date(conflict.detected_at).toLocaleString()}
                </dd>
              </div>
              {conflict.grant_id && (
                <div>
                  <dt className="font-bold text-[#5d58a8] uppercase">
                    {t("columns.grantId")}
                  </dt>
                  <dd className="mt-0.5 font-mono break-all text-[#68647b]">
                    {conflict.grant_id}
                  </dd>
                </div>
              )}
              {conflict.deny_id && (
                <div>
                  <dt className="font-bold text-[#5d58a8] uppercase">
                    {t("columns.denyId")}
                  </dt>
                  <dd className="mt-0.5 font-mono break-all text-[#68647b]">
                    {conflict.deny_id}
                  </dd>
                </div>
              )}
            </dl>

            {conflict.remediation.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-bold text-[#5d58a8] uppercase">
                  {t("conflicts.suggestedRemediation")}
                </p>
                <ul className="space-y-1.5">
                  {conflict.remediation.map((r, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 text-sm text-[#2a2640]"
                    >
                      <span className="mt-0.5 shrink-0 text-[#3525cd]">→</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {canManage &&
              conflict.status !== "resolved" &&
              conflict.status !== "dismissed" && (
                <div className="space-y-3 rounded-xl border border-[#d7d4e8] bg-white p-4">
                  <p className="text-xs font-bold text-[#5d58a8] uppercase">
                    {t("conflicts.updateStatus")}
                  </p>
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder={t("conflicts.resolutionPlaceholder")}
                    rows={2}
                    maxLength={1024}
                    className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
                  />
                  {statusError && (
                    <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                      {statusError}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {conflict.status !== "investigating" && (
                      <button
                        type="button"
                        onClick={() => statusMutation.mutate("investigating")}
                        disabled={statusMutation.isPending}
                        className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                      >
                        {t("conflicts.markInvestigating")}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => statusMutation.mutate("resolved")}
                      disabled={statusMutation.isPending}
                      className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
                    >
                      {t("conflicts.markResolved")}
                    </button>
                    <button
                      type="button"
                      onClick={() => statusMutation.mutate("dismissed")}
                      disabled={statusMutation.isPending}
                      className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                    >
                      {t("conflicts.dismiss")}
                    </button>
                  </div>
                </div>
              )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
