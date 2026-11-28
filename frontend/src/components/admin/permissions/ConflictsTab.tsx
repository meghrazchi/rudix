"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import {
  listConflicts,
  scanForConflicts,
  type ConflictSeverity,
  type ConflictStatus,
} from "@/lib/api/conflicts";
import {
  ConflictDrawer,
  ConflictStatusBadge,
  SeverityBadge,
} from "@/components/admin/permissions/ConflictDrawer";

// ── Conflicts tab ──────────────────────────────────────────────────────────────

export function ConflictsTab({ canManage }: { canManage: boolean }) {
  const t = useTranslations("adminPermissions");
  const queryClient = useQueryClient();
  const [severityFilter, setSeverityFilter] = useState<ConflictSeverity | "">(
    "",
  );
  const [statusFilter, setStatusFilter] = useState<ConflictStatus | "">("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.adminPermissions.conflictList(
      severityFilter,
      statusFilter,
      resourceTypeFilter,
    ),
    queryFn: () =>
      listConflicts({
        severity: severityFilter || undefined,
        status: statusFilter || undefined,
        resource_type: resourceTypeFilter || undefined,
      }),
  });

  const scanMutation = useMutation({
    mutationFn: scanForConflicts,
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminPermissions.conflicts,
      }),
  });

  const items = data?.items ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={severityFilter}
          onChange={(e) =>
            setSeverityFilter(e.target.value as ConflictSeverity | "")
          }
          className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
        >
          <option value="">{t("filters.allSeverities")}</option>
          <option value="info">{t("severities.info")}</option>
          <option value="warning">{t("severities.warning")}</option>
          <option value="blocking">{t("severities.blocking")}</option>
          <option value="security_risk">{t("severities.security_risk")}</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) =>
            setStatusFilter(e.target.value as ConflictStatus | "")
          }
          className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
        >
          <option value="">{t("filters.allStatuses")}</option>
          <option value="open">{t("conflictStatuses.open")}</option>
          <option value="investigating">
            {t("conflictStatuses.investigating")}
          </option>
          <option value="resolved">{t("conflictStatuses.resolved")}</option>
          <option value="dismissed">{t("conflictStatuses.dismissed")}</option>
        </select>
        <select
          value={resourceTypeFilter}
          onChange={(e) => setResourceTypeFilter(e.target.value)}
          className="rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
        >
          <option value="">{t("filters.allResourceTypes")}</option>
          {[
            "document",
            "collection",
            "connector",
            "connector_source_item",
            "citation",
            "graph_entity",
            "graph_evidence",
            "evaluation",
            "saved_answer",
            "knowledge_card",
            "api_key",
          ].map((rt) => (
            <option key={rt} value={rt}>
              {rt}
            </option>
          ))}
        </select>
        <span className="flex-1" />
        {canManage && (
          <button
            type="button"
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="rounded-lg border border-[#d7d4e8] bg-white px-3 py-1.5 text-sm font-semibold text-[#3525cd] transition hover:border-[#3525cd] hover:bg-[#f0eeff] disabled:opacity-50"
          >
            {scanMutation.isPending
              ? t("conflicts.scanning")
              : t("conflicts.runScan")}
          </button>
        )}
      </div>

      {scanMutation.isSuccess && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
          {t("conflicts.scanComplete", {
            detected: scanMutation.data.conflicts_detected,
            created: scanMutation.data.conflicts_created,
          })}{" "}
          <span className="text-xs text-emerald-600">
            ({scanMutation.data.scan_duration_ms}ms)
          </span>
        </div>
      )}

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        isForbiddenError(error) ? (
          <ForbiddenState
            title={t("tabs.conflicts")}
            description={t("errors.securityViewRequired")}
            requestId={extractRequestIdFromError(error)}
            backHref="/admin"
          />
        ) : (
          <ErrorState description={getApiErrorMessage(error)} />
        )
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#d7d4e8] p-8 text-center text-sm text-[#68647b]">
          {t("conflicts.empty")}{" "}
          {canManage && (
            <button
              type="button"
              onClick={() => scanMutation.mutate()}
              className="text-[#3525cd] underline"
            >
              {t("conflicts.runAScan")}
            </button>
          )}{" "}
          {t("conflicts.emptySuffix")}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#d7d4e8] bg-white shadow-sm">
          <table className="w-full min-w-max text-sm">
            <thead>
              <tr className="border-b border-[#d7d4e8] bg-[#f9f8ff]">
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.type")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.subject")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.resource")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.severity")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.status")}
                </th>
                <th className="px-4 py-3 text-left text-xs font-bold text-[#5d58a8] uppercase">
                  {t("columns.detected")}
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer border-b border-[#f0eeff] hover:bg-[#fdfcff]"
                  onClick={() => setSelectedId(c.id)}
                >
                  <td className="px-4 py-3 font-mono text-xs text-[#2a2640]">
                    {c.conflict_type.replace(/_/g, " ")}
                  </td>
                  <td className="max-w-[160px] truncate px-4 py-3 font-mono text-xs text-[#68647b]">
                    {c.subject_value}
                  </td>
                  <td className="px-4 py-3 text-xs text-[#2a2640]">
                    {c.resource_type}
                    {c.resource_id && (
                      <span className="ml-1 text-[#68647b]">
                        /{c.resource_id}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <SeverityBadge severity={c.severity} />
                  </td>
                  <td className="px-4 py-3">
                    <ConflictStatusBadge status={c.status} />
                  </td>
                  <td className="px-4 py-3 text-xs text-[#68647b]">
                    {new Date(c.detected_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedId(c.id);
                      }}
                      className="text-xs font-medium text-[#3525cd] hover:underline"
                    >
                      {t("view")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-[#d7d4e8] px-4 py-2 text-xs text-[#68647b]">
            {t("showing", { count: items.length, total: data?.total ?? 0 })}
          </div>
        </div>
      )}

      {selectedId && (
        <ConflictDrawer
          conflictId={selectedId}
          onClose={() => setSelectedId(null)}
          canManage={canManage}
        />
      )}
    </div>
  );
}
