"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import type {
  DocumentDetailResponse,
  ReindexDocumentRequest,
} from "@/lib/api/documents";
import {
  getChunkingStrategyCatalog,
  listChunkingProfiles,
} from "@/lib/api/chunking-profiles";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";

type DocumentChunkingDiagnosticsPanelProps = {
  documentId: string;
  detail: DocumentDetailResponse;
  canReindex: boolean;
  isReindexPending: boolean;
  chunkingIssueCount: number;
  onQueueReindex: (
    payload: ReindexDocumentRequest | undefined,
    label: string,
  ) => void;
};

function booleanLabel(value: boolean | null | undefined): string {
  if (value == null) {
    return "-";
  }
  return value ? "Yes" : "No";
}

export function DocumentChunkingDiagnosticsPanel({
  documentId,
  detail,
  canReindex,
  isReindexPending,
  chunkingIssueCount,
  onQueueReindex,
}: DocumentChunkingDiagnosticsPanelProps) {
  const diagnostics = detail.chunking_diagnostics ?? null;
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(
    null,
  );

  const strategiesQuery = useQuery({
    queryKey: queryKeys.admin.chunkingStrategies,
    queryFn: getChunkingStrategyCatalog,
    enabled: canReindex,
    retry: false,
  });

  const profilesQuery = useQuery({
    queryKey: queryKeys.admin.chunkingProfiles,
    queryFn: listChunkingProfiles,
    enabled:
      canReindex &&
      Boolean(strategiesQuery.data?.feature_chunking_profiles_enabled),
    retry: false,
  });

  const defaultProfileId =
    profilesQuery.data?.profiles.find((profile) => profile.is_default)
      ?.profile_id ?? "system";
  const resolvedSelectedProfileId = selectedProfileId ?? defaultProfileId;

  const selectedProfile = useMemo(
    () =>
      profilesQuery.data?.profiles.find(
        (profile) => profile.profile_id === resolvedSelectedProfileId,
      ) ?? null,
    [profilesQuery.data, resolvedSelectedProfileId],
  );

  const strategyLabel =
    diagnostics?.selected_strategy ?? diagnostics?.strategy ?? "Legacy index";
  const tokenDistribution = diagnostics?.token_distribution ?? null;
  const selectedProfileLabel =
    resolvedSelectedProfileId === "system"
      ? "system default"
      : (selectedProfile?.name ?? "selected profile");

  return (
    <section className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Chunking diagnostics
          </h4>
          <p className="mt-1 text-sm text-[#4d4963]">
            Safe chunking provenance and re-index controls for this document.
          </p>
        </div>
        {chunkingIssueCount > 0 ? (
          <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-bold tracking-wide text-amber-800 uppercase">
            {chunkingIssueCount} chunking warnings
          </span>
        ) : null}
      </div>

      {!diagnostics ? (
        <EmptyState
          compact
          title="Detailed chunking diagnostics are unavailable for this document."
          description="This can happen for documents indexed before diagnostics were recorded. Re-index to backfill the current metadata."
        />
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Metric label="Applied strategy" value={strategyLabel} />
            <Metric
              label="Configured strategy"
              value={diagnostics.strategy ?? "-"}
            />
            <Metric
              label="OCR applied"
              value={booleanLabel(diagnostics.ocr_applied)}
            />
            <Metric label="Language" value={detail.language ?? "-"} />
            <Metric
              label="Chunk size / overlap"
              value={
                diagnostics.chunk_size_tokens != null &&
                diagnostics.chunk_overlap_tokens != null
                  ? `${diagnostics.chunk_size_tokens} / ${diagnostics.chunk_overlap_tokens}`
                  : "-"
              }
            />
            <Metric
              label="Token distribution"
              value={
                tokenDistribution
                  ? `${tokenDistribution.min_tokens} / ${tokenDistribution.avg_tokens} / ${tokenDistribution.max_tokens}`
                  : "-"
              }
            />
            <Metric
              label="Profile source"
              value={diagnostics.profile_source ?? "-"}
            />
            <Metric
              label="Profile version"
              value={diagnostics.profile_version ?? "-"}
            />
          </div>

          {diagnostics.reason_codes.length > 0 ? (
            <div className="rounded-lg border border-[#ddd7f6] bg-white px-4 py-3">
              <p className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                Reason codes
              </p>
              <div className="flex flex-wrap gap-2">
                {diagnostics.reason_codes.map((reason) => (
                  <span
                    key={reason}
                    className="rounded-full bg-[#f5f2ff] px-2.5 py-1 font-mono text-[11px] text-[#4f4690]"
                  >
                    {reason}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {diagnostics.adaptive_signals ? (
            <div className="rounded-lg border border-[#ddd7f6] bg-white px-4 py-3">
              <p className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                Adaptive signals
              </p>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Metric
                  label="Pages"
                  value={diagnostics.adaptive_signals.page_count}
                  compact
                />
                <Metric
                  label="Total tokens"
                  value={diagnostics.adaptive_signals.total_token_count}
                  compact
                />
                <Metric
                  label="Heading density"
                  value={
                    diagnostics.adaptive_signals.heading_density != null
                      ? diagnostics.adaptive_signals.heading_density.toFixed(2)
                      : "-"
                  }
                  compact
                />
                <Metric
                  label="OCR"
                  value={booleanLabel(diagnostics.adaptive_signals.ocr_applied)}
                  compact
                />
              </div>
            </div>
          ) : null}
        </div>
      )}

      {canReindex ? (
        <div className="mt-4 rounded-lg border border-[#ddd7f6] bg-white px-4 py-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-[#1b1b24]">
                Re-index with selected profile
              </p>
              <p className="text-xs text-[#5f5a74]">
                Queue a re-index without leaving this page. Status updates
                continue automatically.
              </p>
            </div>
          </div>

          {strategiesQuery.isLoading ? (
            <LoadingState compact title="Loading chunking profiles..." />
          ) : strategiesQuery.isError ? (
            <ErrorState
              compact
              error={strategiesQuery.error}
              description={getApiErrorMessage(strategiesQuery.error)}
              onRetry={() => {
                void strategiesQuery.refetch();
              }}
            />
          ) : strategiesQuery.data &&
            !strategiesQuery.data.feature_chunking_profiles_enabled ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
              Organization chunking profiles are disabled for this deployment.
              You can still use the standard re-index action from this page.
            </div>
          ) : profilesQuery.isLoading ? (
            <LoadingState compact title="Loading organization profiles..." />
          ) : profilesQuery.isError ? (
            <ErrorState
              compact
              error={profilesQuery.error}
              description={getApiErrorMessage(profilesQuery.error)}
              onRetry={() => {
                void profilesQuery.refetch();
              }}
            />
          ) : (
            <div className="space-y-3">
              <label className="block space-y-1">
                <span className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                  Profile
                </span>
                <select
                  value={resolvedSelectedProfileId}
                  onChange={(event) => setSelectedProfileId(event.target.value)}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                >
                  <option value="system">System default</option>
                  {(profilesQuery.data?.profiles ?? []).map((profile) => (
                    <option key={profile.profile_id} value={profile.profile_id}>
                      {profile.name}
                      {profile.is_default ? " (Default)" : ""}
                    </option>
                  ))}
                </select>
              </label>

              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#ece9f8] bg-[#faf9ff] px-3 py-3">
                <p className="text-sm text-[#4d4963]">
                  Queueing document{" "}
                  <span className="font-mono">{documentId}</span> with{" "}
                  <span className="font-semibold">{selectedProfileLabel}</span>.
                </p>
                <button
                  type="button"
                  disabled={isReindexPending}
                  onClick={() => {
                    const confirmed = window.confirm(
                      `Re-index "${detail.filename}" with ${selectedProfileLabel}? Existing chunks will be replaced after processing completes.`,
                    );
                    if (!confirmed) {
                      return;
                    }
                    onQueueReindex(
                      resolvedSelectedProfileId === "system"
                        ? undefined
                        : {
                            chunking_profile_id: resolvedSelectedProfileId,
                          },
                      selectedProfileLabel,
                    );
                  }}
                  className="rounded-lg border border-[#cbc5e6] bg-white px-4 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isReindexPending ? "Queueing…" : "Queue re-index"}
                </button>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

function Metric({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: string | number;
  compact?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border border-[#ece9f8] bg-white ${compact ? "p-3" : "p-3.5"}`}
    >
      <p className="text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </p>
      <p className="mt-1 text-sm font-semibold break-words text-[#1b1b24]">
        {value}
      </p>
    </div>
  );
}
