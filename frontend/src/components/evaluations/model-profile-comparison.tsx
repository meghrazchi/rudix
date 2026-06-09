"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  getModelProfileComparisonReport,
  listBenchmarkSuites,
  triggerBenchmarkRun,
  type ModelProfileComparisonReport,
  type ProviderProfileSummary,
  type ReleaseGateRecommendation,
  type BenchmarkSuite,
} from "@/lib/api/evaluations";
import { getApiErrorMessage } from "@/lib/api/errors";

const PROFILE_LABELS: Record<string, string> = {
  cloud_baseline: "Cloud Baseline",
  local_profile: "Local Profile",
  fallback_profile: "Fallback Profile",
};

const PROFILE_COLORS: Record<
  string,
  { bg: string; text: string; border: string }
> = {
  cloud_baseline: {
    bg: "bg-blue-50",
    text: "text-blue-700",
    border: "border-blue-200",
  },
  local_profile: {
    bg: "bg-violet-50",
    text: "text-[#5b21b6]",
    border: "border-[#cbc6dd]",
  },
  fallback_profile: {
    bg: "bg-amber-50",
    text: "text-amber-700",
    border: "border-amber-200",
  },
};

function fmt(value: number | null | undefined, asPercent = false): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const v = asPercent ? value * 100 : value;
  return asPercent ? `${v.toFixed(1)}%` : v.toFixed(3);
}

function MetricRow({
  label,
  profiles,
  metricKey,
  asPercent = false,
  higherIsBetter = true,
}: {
  label: string;
  profiles: ProviderProfileSummary[];
  metricKey: keyof ProviderProfileSummary;
  asPercent?: boolean;
  higherIsBetter?: boolean;
}) {
  const values = profiles.map((p) => {
    const raw = p[metricKey];
    return typeof raw === "number" ? raw : null;
  });

  const defined = values.filter((v): v is number => v != null);
  const best = defined.length > 1 ? (higherIsBetter ? Math.max(...defined) : Math.min(...defined)) : null;

  return (
    <tr className="border-b border-gray-100 last:border-0">
      <td className="py-2 pr-4 text-sm text-gray-600">{label}</td>
      {profiles.map((p, i) => {
        const v = values[i];
        const isBest = best != null && v != null && v === best;
        return (
          <td
            key={p.provider_profile}
            className={`py-2 text-center text-sm font-medium tabular-nums ${
              isBest ? "text-green-700" : "text-gray-800"
            }`}
          >
            {fmt(v, asPercent)}
          </td>
        );
      })}
    </tr>
  );
}

function LocalMetricsRow({
  label,
  profiles,
  localKey,
  asPercent = true,
  higherIsBetter = false,
}: {
  label: string;
  profiles: ProviderProfileSummary[];
  localKey:
    | "invalid_json_rate"
    | "timeout_rate"
    | "fallback_frequency"
    | "estimated_compute_latency_ms"
    | "tokens_per_second";
  asPercent?: boolean;
  higherIsBetter?: boolean;
}) {
  const values = profiles.map((p) => p.local_model_metrics?.[localKey] ?? null);
  const defined = values.filter((v): v is number => v != null);
  const best =
    defined.length > 1
      ? higherIsBetter
        ? Math.max(...defined)
        : Math.min(...defined)
      : null;

  return (
    <tr className="border-b border-gray-100 last:border-0">
      <td className="py-2 pr-4 text-sm text-gray-500 italic">{label}</td>
      {profiles.map((p, i) => {
        const v = values[i];
        const isBest = best != null && v != null && v === best;
        return (
          <td
            key={p.provider_profile}
            className={`py-2 text-center text-sm tabular-nums ${
              v == null
                ? "text-gray-300"
                : isBest
                  ? "text-green-700 font-medium"
                  : "text-gray-700"
            }`}
          >
            {fmt(v, asPercent)}
          </td>
        );
      })}
    </tr>
  );
}

function GateBadge({ recommendation }: { recommendation: ReleaseGateRecommendation }) {
  const label = PROFILE_LABELS[recommendation.provider_profile] ?? recommendation.provider_profile;
  return (
    <div
      className={`rounded-lg border p-3 ${
        recommendation.is_ready
          ? "border-green-200 bg-green-50"
          : "border-red-200 bg-red-50"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`text-base font-bold ${
            recommendation.is_ready ? "text-green-700" : "text-red-600"
          }`}
        >
          {recommendation.is_ready ? "✓" : "✗"}
        </span>
        <span className="text-sm font-semibold text-gray-800">{label}</span>
        <span
          className={`ml-auto rounded px-2 py-0.5 text-xs font-semibold ${
            recommendation.is_ready
              ? "bg-green-100 text-green-700"
              : "bg-red-100 text-red-600"
          }`}
        >
          {recommendation.is_ready ? "Ready" : "Not ready"}
        </span>
      </div>
      <p className="mt-1.5 text-xs text-gray-600">{recommendation.recommendation}</p>
      {recommendation.failing_checks.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {recommendation.failing_checks.map((check) => (
            <li key={check} className="flex items-center gap-1.5 text-xs text-red-600">
              <span>✗</span>
              <span>{check}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BenchmarkTriggerSection({
  suites,
  isSuitesLoading,
  suitesError,
  onTriggered,
}: {
  suites: BenchmarkSuite[];
  isSuitesLoading: boolean;
  suitesError: Error | null;
  onTriggered: () => void;
}) {
  const [selectedSuite, setSelectedSuite] = useState("");
  const [selectedProfile, setSelectedProfile] = useState<
    "cloud_baseline" | "local_profile" | "fallback_profile"
  >("local_profile");
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [triggerSuccess, setTriggerSuccess] = useState<string | null>(null);

  const triggerMutation = useMutation({
    mutationFn: () =>
      triggerBenchmarkRun(selectedSuite || suites[0]?.suite_id, {
        suite_id: selectedSuite || suites[0]?.suite_id,
        provider_profile: selectedProfile,
      }),
    onSuccess: (result) => {
      setTriggerError(null);
      setTriggerSuccess(
        `Run queued: ${result.evaluation_run_id.slice(0, 8)}… (${result.provider_profile})`,
      );
      onTriggered();
    },
    onError: (error) => setTriggerError(getApiErrorMessage(error)),
  });

  if (isSuitesLoading) {
    return <p className="text-sm text-gray-400">Loading benchmark suites…</p>;
  }
  if (suitesError) {
    return <p className="text-sm text-red-500">{getApiErrorMessage(suitesError)}</p>;
  }
  if (suites.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-[#ddd8ec] bg-[#f9f8fd] p-3">
      <p className="mb-2 text-sm font-medium text-[#292442]">Run a benchmark suite</p>
      <div className="flex flex-wrap gap-2">
        <select
          value={selectedSuite}
          onChange={(e) => setSelectedSuite(e.target.value)}
          className="rounded border border-[#cbc6dd] px-2 py-1 text-sm text-[#403b5f] focus:outline-none focus:ring-1 focus:ring-[#8b5cf6]"
        >
          {suites.map((s) => (
            <option key={s.suite_id} value={s.suite_id}>
              {s.name} ({s.case_count} cases)
            </option>
          ))}
        </select>
        <select
          value={selectedProfile}
          onChange={(e) =>
            setSelectedProfile(
              e.target.value as "cloud_baseline" | "local_profile" | "fallback_profile",
            )
          }
          className="rounded border border-[#cbc6dd] px-2 py-1 text-sm text-[#403b5f] focus:outline-none focus:ring-1 focus:ring-[#8b5cf6]"
        >
          <option value="cloud_baseline">Cloud Baseline</option>
          <option value="local_profile">Local Profile</option>
          <option value="fallback_profile">Fallback Profile</option>
        </select>
        <button
          type="button"
          disabled={triggerMutation.isPending}
          onClick={() => {
            setTriggerError(null);
            setTriggerSuccess(null);
            triggerMutation.mutate();
          }}
          className="rounded bg-[#8b5cf6] px-3 py-1 text-sm font-semibold text-white hover:bg-[#7c3aed] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {triggerMutation.isPending ? "Triggering…" : "Run benchmark"}
        </button>
      </div>
      {triggerError && (
        <p className="mt-2 text-xs text-red-600">{triggerError}</p>
      )}
      {triggerSuccess && (
        <p className="mt-2 text-xs text-green-700">{triggerSuccess}</p>
      )}
    </div>
  );
}

type ModelProfileComparisonPanelProps = {
  evaluationSetId?: string | null;
  canAdmin?: boolean;
};

export function ModelProfileComparisonPanel({
  evaluationSetId = null,
  canAdmin = false,
}: ModelProfileComparisonPanelProps) {
  const [refreshKey, setRefreshKey] = useState(0);

  const reportQuery = useQuery({
    queryKey: ["evaluations", "model-profile-report", evaluationSetId, refreshKey],
    queryFn: () => getModelProfileComparisonReport(evaluationSetId),
  });

  const suitesQuery = useQuery({
    queryKey: ["evaluations", "benchmark-suites"],
    queryFn: listBenchmarkSuites,
    staleTime: 300_000,
    enabled: canAdmin,
  });

  const report: ModelProfileComparisonReport | undefined = reportQuery.data;

  return (
    <section className="space-y-4 rounded-xl border border-[#ddd8ec] bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[#292442]">
            Model profile comparison
          </h2>
          <p className="mt-0.5 text-xs text-[#67627f]">
            Cloud baseline vs local profile vs fallback — quality metrics and
            release-gate recommendations.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setRefreshKey((k) => k + 1)}
          disabled={reportQuery.isFetching}
          className="rounded border border-[#cbc6dd] px-2 py-1 text-xs font-semibold text-[#403b5f] hover:bg-gray-50 disabled:opacity-60"
        >
          {reportQuery.isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {canAdmin && (
        <BenchmarkTriggerSection
          suites={suitesQuery.data?.items ?? []}
          isSuitesLoading={suitesQuery.isLoading}
          suitesError={suitesQuery.error as Error | null}
          onTriggered={() => {
            setTimeout(() => setRefreshKey((k) => k + 1), 3000);
          }}
        />
      )}

      {reportQuery.isLoading ? (
        <LoadingState message="Loading comparison report…" />
      ) : reportQuery.isError ? (
        <ErrorState
          compact
          error={reportQuery.error}
          description={getApiErrorMessage(reportQuery.error)}
          onRetry={() => void reportQuery.refetch()}
        />
      ) : report == null || report.profiles.length === 0 ? (
        <p className="rounded-lg border border-[#ddd8ec] bg-[#f9f8fd] p-4 text-sm text-[#67627f]">
          No completed evaluation runs with provider profile labels found. Trigger
          a benchmark run above to populate this report.
        </p>
      ) : (
        <div className="space-y-4">
          {/* Metrics table */}
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="pb-2 pr-4 text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Metric
                  </th>
                  {report.profiles.map((p) => {
                    const colors = PROFILE_COLORS[p.provider_profile] ?? {
                      bg: "bg-gray-50",
                      text: "text-gray-700",
                      border: "border-gray-200",
                    };
                    return (
                      <th
                        key={p.provider_profile}
                        className="pb-2 text-center text-xs font-semibold"
                      >
                        <span
                          className={`inline-block rounded px-2 py-0.5 ${colors.bg} ${colors.text} border ${colors.border}`}
                        >
                          {PROFILE_LABELS[p.provider_profile] ?? p.provider_profile}
                        </span>
                        {p.run_count > 0 && (
                          <span className="ml-1 text-xs font-normal text-gray-400">
                            ({p.run_count} run{p.run_count !== 1 ? "s" : ""})
                          </span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                <MetricRow
                  label="Retrieval Hit Rate"
                  profiles={report.profiles}
                  metricKey="retrieval_hit_rate"
                  asPercent
                />
                <MetricRow
                  label="Citation Accuracy"
                  profiles={report.profiles}
                  metricKey="citation_accuracy_score"
                  asPercent
                />
                <MetricRow
                  label="Faithfulness"
                  profiles={report.profiles}
                  metricKey="faithfulness_score"
                  asPercent
                />
                <MetricRow
                  label="Answer Relevance"
                  profiles={report.profiles}
                  metricKey="answer_relevance_score"
                  asPercent
                />
                <MetricRow
                  label="Not-Found Rate"
                  profiles={report.profiles}
                  metricKey="not_found_rate"
                  asPercent
                  higherIsBetter={false}
                />
                <MetricRow
                  label="Avg Latency (ms)"
                  profiles={report.profiles}
                  metricKey="latency_ms_average"
                  higherIsBetter={false}
                />
                <MetricRow
                  label="Total Cost (USD)"
                  profiles={report.profiles}
                  metricKey="cost_usd_total"
                  higherIsBetter={false}
                />
                {/* Local-specific metrics */}
                <LocalMetricsRow
                  label="Invalid JSON Rate"
                  profiles={report.profiles}
                  localKey="invalid_json_rate"
                  higherIsBetter={false}
                />
                <LocalMetricsRow
                  label="Timeout Rate"
                  profiles={report.profiles}
                  localKey="timeout_rate"
                  higherIsBetter={false}
                />
                <LocalMetricsRow
                  label="Fallback Frequency"
                  profiles={report.profiles}
                  localKey="fallback_frequency"
                  higherIsBetter={false}
                />
                <LocalMetricsRow
                  label="Est. Compute Latency (ms)"
                  profiles={report.profiles}
                  localKey="estimated_compute_latency_ms"
                  asPercent={false}
                  higherIsBetter={false}
                />
                <LocalMetricsRow
                  label="Tokens / Second"
                  profiles={report.profiles}
                  localKey="tokens_per_second"
                  asPercent={false}
                  higherIsBetter
                />
              </tbody>
            </table>
          </div>

          {/* Provider info row */}
          <div className="flex flex-wrap gap-3">
            {report.profiles.map((p) => (
              <div
                key={p.provider_profile}
                className="rounded border border-[#ddd8ec] bg-[#f9f8fd] px-3 py-1.5 text-xs text-gray-600"
              >
                <span className="font-medium">
                  {PROFILE_LABELS[p.provider_profile] ?? p.provider_profile}
                </span>
                {p.provider_type && (
                  <span className="ml-1 text-gray-400">({p.provider_type})</span>
                )}
              </div>
            ))}
          </div>

          {/* Release gate recommendations */}
          {report.release_gate_recommendations.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-[#292442]">
                Release gate
              </h3>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {report.release_gate_recommendations.map((rec) => (
                  <GateBadge key={rec.provider_profile} recommendation={rec} />
                ))}
              </div>
              <p className="text-xs text-gray-400">
                Thresholds:{" "}
                {Object.entries(report.default_thresholds)
                  .map(([k, v]) => `${k}=${typeof v === "number" && v < 1 ? `${(v * 100).toFixed(0)}%` : v}`)
                  .join(" · ")}
              </p>
            </div>
          )}

          <p className="text-right text-xs text-gray-400">
            Report generated{" "}
            {new Date(report.generated_at).toLocaleString(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            })}
          </p>
        </div>
      )}
    </section>
  );
}
