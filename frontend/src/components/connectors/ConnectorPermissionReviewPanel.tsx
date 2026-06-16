"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getApiErrorMessage } from "@/lib/api/errors";
import {
  confirmPermissionReview,
  getPermissionReview,
  type PermissionReview,
  type ScopeWarning,
} from "@/lib/api/connectors";
import { queryKeys } from "@/lib/api/query";

const WARNING_CODE_LABELS: Record<string, string> = {
  write_permission: "Write access",
  admin_scope: "Admin scope",
  org_wide_access: "Org-wide access",
  broad_read: "Broad read",
};

const WARNING_CODE_ICONS: Record<string, string> = {
  write_permission: "edit_off",
  admin_scope: "admin_panel_settings",
  org_wide_access: "public",
  broad_read: "visibility",
};

function WarningRow({ warning }: { warning: ScopeWarning }) {
  const label = WARNING_CODE_LABELS[warning.code] ?? warning.code;
  const icon = WARNING_CODE_ICONS[warning.code] ?? "warning";
  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3">
      <span className="material-symbols-outlined mt-0.5 shrink-0 text-[18px] text-amber-600">
        {icon}
      </span>
      <div>
        <div className="text-xs font-semibold text-amber-900">{label}</div>
        <div className="mt-0.5 text-xs text-amber-800">{warning.message}</div>
        {warning.scope && (
          <div className="mt-1 font-mono text-[11px] break-all text-amber-700">
            {warning.scope}
          </div>
        )}
      </div>
    </div>
  );
}

function ScopeTag({ scope }: { scope: string }) {
  return (
    <span className="rounded-full bg-[#ece8ff] px-2.5 py-1 font-mono text-[11px] break-all text-[#3525cd]">
      {scope}
    </span>
  );
}

function formatFilterValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(", ");
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

type PanelProps = {
  connectionId: string;
};

export function ConnectorPermissionReviewPanel({ connectionId }: PanelProps) {
  const queryClient = useQueryClient();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const reviewQuery = useQuery({
    queryKey: queryKeys.connectorPermissionReview(connectionId),
    queryFn: () => getPermissionReview(connectionId),
  });

  const confirmMutation = useMutation({
    mutationFn: () => confirmPermissionReview(connectionId),
    onSuccess: (data: PermissionReview) => {
      queryClient.setQueryData(
        queryKeys.connectorPermissionReview(connectionId),
        data,
      );
      setErrorMessage(null);
    },
    onError: (err: unknown) => {
      setErrorMessage(getApiErrorMessage(err));
    },
  });

  if (reviewQuery.isLoading) {
    return (
      <div className="rounded-2xl border border-dashed border-[#d7d4e8] p-5 text-sm text-[#68647b]">
        Loading permission review…
      </div>
    );
  }

  if (reviewQuery.isError || !reviewQuery.data) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
        Unable to load permission review.
      </div>
    );
  }

  const review = reviewQuery.data;
  const snapshot = review.permission_snapshot as {
    provider_key?: string;
    scopes_granted?: string[];
    sync_direction?: string;
    retention_policy?: string;
    collection_id?: string | null;
    source_filters?: Record<string, unknown>;
  };
  const grantedScopes: string[] = snapshot.scopes_granted ?? [];
  const sourceFilterEntries = Object.entries(
    snapshot.source_filters ?? {},
  ).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );
  const hasBroadWarning = review.is_broad_scope;

  return (
    <section
      className="overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white"
      aria-label="Permission review"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-4 border-b border-[#d7d4e8] px-5 py-4">
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-[20px] text-[#3525cd]">
            verified_user
          </span>
          <div>
            <div className="text-sm font-semibold text-[#2a2640]">
              Permission review
            </div>
            <div className="text-xs text-[#68647b]">
              Admin must confirm scope before indexing can begin
            </div>
          </div>
        </div>
        <div>
          {review.is_confirmed ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800">
              <span className="material-symbols-outlined text-[14px]">
                check_circle
              </span>
              Confirmed
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">
              <span className="material-symbols-outlined text-[14px]">
                pending
              </span>
              Pending review
            </span>
          )}
        </div>
      </div>

      <div className="space-y-5 p-5">
        {/* Broad scope banner */}
        {hasBroadWarning && !review.is_confirmed && (
          <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4">
            <span className="material-symbols-outlined mt-0.5 shrink-0 text-[22px] text-amber-600">
              warning
            </span>
            <div>
              <div className="text-sm font-semibold text-amber-900">
                Broad permission scope detected
              </div>
              <p className="mt-0.5 text-sm text-amber-800">
                One or more granted scopes provide access beyond the minimum
                required. Review the warnings below and consider narrowing the
                scope before confirming.
              </p>
            </div>
          </div>
        )}

        {/* Scope warnings */}
        {review.scope_warnings.length > 0 && (
          <div>
            <div className="mb-2 text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
              Scope warnings
            </div>
            <div className="space-y-2">
              {review.scope_warnings.map((w, i) => (
                <WarningRow key={i} warning={w} />
              ))}
            </div>
          </div>
        )}

        {/* Granted scopes */}
        {grantedScopes.length > 0 && (
          <div>
            <div className="mb-2 text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
              Granted scopes
            </div>
            <div className="flex flex-wrap gap-2">
              {grantedScopes.map((s) => (
                <ScopeTag key={s} scope={s} />
              ))}
            </div>
          </div>
        )}

        {sourceFilterEntries.length > 0 && (
          <div>
            <div className="mb-2 text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
              Selected source filters
            </div>
            <div className="space-y-2">
              {sourceFilterEntries.map(([key, value]) => (
                <div
                  key={key}
                  className="rounded-xl border border-[#d7d4e8] bg-[#faf9fe] px-3 py-2 text-xs text-[#4b4860]"
                >
                  <span className="font-semibold text-[#2a2640]">
                    {key.replace(/_/g, " ")}:
                  </span>{" "}
                  <span className="font-mono break-all">
                    {formatFilterValue(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Policy summary */}
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-[#d7d4e8] p-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-[#2a2640]">
              <span className="material-symbols-outlined text-[15px] text-[#3525cd]">
                sync_alt
              </span>
              Sync direction
            </div>
            <div className="mt-1 text-xs text-[#68647b] capitalize">
              {(snapshot.sync_direction ?? "read_only").replace(/_/g, " ")}
            </div>
          </div>
          <div className="rounded-xl border border-[#d7d4e8] p-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-[#2a2640]">
              <span className="material-symbols-outlined text-[15px] text-[#3525cd]">
                database
              </span>
              Retention
            </div>
            <div className="mt-1 text-xs text-[#68647b] capitalize">
              {(
                snapshot.retention_policy ?? "indexed_until_connector_removed"
              ).replace(/_/g, " ")}
            </div>
          </div>
          <div className="rounded-xl border border-[#d7d4e8] p-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-[#2a2640]">
              <span className="material-symbols-outlined text-[15px] text-[#3525cd]">
                group
              </span>
              Access
            </div>
            <div className="mt-1 text-xs text-[#68647b]">
              {snapshot.collection_id
                ? "Restricted to assigned collection"
                : "All organisation members"}
            </div>
          </div>
        </div>

        {/* Confirmation row */}
        {review.is_confirmed ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[16px] text-emerald-600">
                task_alt
              </span>
              <span className="font-semibold">Permissions confirmed</span>
            </div>
            <div className="mt-1 text-xs text-emerald-700">
              Confirmed {formatDate(review.reviewed_at)}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {errorMessage && (
              <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
                {errorMessage}
              </div>
            )}
            <button
              type="button"
              onClick={() => confirmMutation.mutate()}
              disabled={confirmMutation.isPending}
              data-testid="confirm-permission-review"
              className="inline-flex items-center gap-2 rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[#2a1db0] disabled:opacity-60"
            >
              <span className="material-symbols-outlined text-[16px]">
                verified_user
              </span>
              {confirmMutation.isPending
                ? "Confirming…"
                : "Confirm permissions and allow sync"}
            </button>
            <p className="text-xs text-[#6a6780]">
              Syncing is blocked until an admin explicitly confirms the
              permission scope above.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
