"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

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

function booleanLabel(
  value: boolean | null | undefined,
  yesLabel: string,
  noLabel: string,
): string {
  if (value == null) {
    return "-";
  }
  return value ? yesLabel : noLabel;
}

export function DocumentChunkingDiagnosticsPanel({
  documentId,
  detail,
  canReindex,
  isReindexPending,
  chunkingIssueCount,
  onQueueReindex,
}: DocumentChunkingDiagnosticsPanelProps) {
  const t = useTranslations("documents.chunkingDiagnostics");
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
      ? t("systemDefault")
      : (selectedProfile?.name ?? t("systemDefault"));

  return (
    <section className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {t("title")}
          </h4>
          <p className="mt-1 text-sm text-[#4d4963]">
            {t("description")}
          </p>
        </div>
        {chunkingIssueCount > 0 ? (
          <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-bold tracking-wide text-amber-800 uppercase">
            {t("warnings", { count: chunkingIssueCount })}
          </span>
        ) : null}
      </div>

      {!diagnostics ? (
        <EmptyState
          compact
          title={t("emptyTitle")}
          description={t("emptyDesc")}
        />
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Metric label={t("appliedStrategy")} value={strategyLabel} />
            <Metric
              label={t("configuredStrategy")}
              value={diagnostics.strategy ?? "-"}
            />
            <Metric
              label={t("ocrApplied")}
              value={booleanLabel(diagnostics.ocr_applied, t("boolYes"), t("boolNo"))}
            />
            <Metric label={t("language")} value={detail.language ?? "-"} />
            <Metric
              label={t("chunkSizeOverlap")}
              value={
                diagnostics.chunk_size_tokens != null &&
                diagnostics.chunk_overlap_tokens != null
                  ? `${diagnostics.chunk_size_tokens} / ${diagnostics.chunk_overlap_tokens}`
                  : "-"
              }
            />
            <Metric
              label={t("tokenDistribution")}
              value={
                tokenDistribution
                  ? `${tokenDistribution.min_tokens} / ${tokenDistribution.avg_tokens} / ${tokenDistribution.max_tokens}`
                  : "-"
              }
            />
            <Metric
              label={t("profileSource")}
              value={diagnostics.profile_source ?? "-"}
            />
            <Metric
              label={t("profileVersion")}
              value={diagnostics.profile_version ?? "-"}
            />
          </div>

          {diagnostics.reason_codes.length > 0 ? (
            <div className="rounded-lg border border-[#ddd7f6] bg-white px-4 py-3">
              <p className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                {t("reasonCodes")}
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
                {t("adaptiveSignals")}
              </p>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Metric
                  label={t("pages")}
                  value={diagnostics.adaptive_signals.page_count}
                  compact
                />
                <Metric
                  label={t("totalTokens")}
                  value={diagnostics.adaptive_signals.total_token_count}
                  compact
                />
                <Metric
                  label={t("headingDensity")}
                  value={
                    diagnostics.adaptive_signals.heading_density != null
                      ? diagnostics.adaptive_signals.heading_density.toFixed(2)
                      : "-"
                  }
                  compact
                />
                <Metric
                  label={t("ocr")}
                  value={booleanLabel(diagnostics.adaptive_signals.ocr_applied, t("boolYes"), t("boolNo"))}
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
                {t("reindexTitle")}
              </p>
              <p className="text-xs text-[#5f5a74]">
                {t("reindexDesc")}
              </p>
            </div>
          </div>

          {strategiesQuery.isLoading ? (
            <LoadingState compact title={t("loadingStrategies")} />
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
              {t("profilesDisabled")}
            </div>
          ) : profilesQuery.isLoading ? (
            <LoadingState compact title={t("loadingProfiles")} />
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
                  {t("profileLabel")}
                </span>
                <select
                  value={resolvedSelectedProfileId}
                  onChange={(event) => setSelectedProfileId(event.target.value)}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                >
                  <option value="system">{t("systemDefault")}</option>
                  {(profilesQuery.data?.profiles ?? []).map((profile) => (
                    <option key={profile.profile_id} value={profile.profile_id}>
                      {profile.name}
                      {profile.is_default ? ` ${t("profileDefaultSuffix")}` : ""}
                    </option>
                  ))}
                </select>
              </label>

              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#ece9f8] bg-[#faf9ff] px-3 py-3">
                <p className="text-sm text-[#4d4963]">
                  {t("queueingWith", { id: documentId, profile: selectedProfileLabel })}
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
                  {isReindexPending ? t("submitting") : t("submit")}
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
