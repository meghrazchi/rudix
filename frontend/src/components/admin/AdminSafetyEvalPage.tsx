"use client";

import React, { useCallback, useMemo, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getSafetyEvalRunDetail,
  listSafetyEvalCases,
  listSafetyEvalRuns,
  triggerSafetyEvalRun,
  type SafetyEvalRunResponse,
  type SafetyEvalResultResponse,
} from "@/lib/api/safety-evals";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isForbiddenError, extractRequestIdFromError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

const PAGE_LIMIT = 20;

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return value;
  return new Date(ts).toLocaleString();
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function runStatusClass(s: string): string {
  switch (s) {
    case "completed":
      return "bg-emerald-100 text-emerald-800";
    case "running":
      return "bg-blue-100 text-blue-800";
    case "queued":
      return "bg-slate-100 text-slate-700";
    case "failed":
      return "bg-rose-100 text-rose-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function passFailClass(passed: boolean): string {
  return passed
    ? "bg-emerald-100 text-emerald-800"
    : "bg-rose-100 text-rose-800";
}

function severityClass(s: string): string {
  switch (s) {
    case "critical":
      return "bg-red-200 text-red-900";
    case "high":
      return "bg-rose-100 text-rose-800";
    case "medium":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

function passRateBadge(passRate: number | null): React.ReactNode {
  if (passRate == null) return <span className="text-[#777587]">—</span>;
  const pct = Math.round(passRate * 100);
  const color =
    pct >= 90
      ? "text-emerald-700"
      : pct >= 70
        ? "text-amber-700"
        : "text-rose-700";
  return <span className={`font-mono font-semibold ${color}`}>{pct}%</span>;
}

type RunDetailPanelProps = {
  runId: string;
  onClose: () => void;
};

function RunDetailPanel({ runId, onClose }: RunDetailPanelProps) {
  const panelRef = useRef<HTMLElement | null>(null);
  useOverlayFocus({
    isOpen: true,
    containerRef: panelRef,
    onClose,
    lockBodyScroll: false,
  });

  const detailQuery = useQuery({
    queryKey: ["safety-evals", "runs", runId, "detail"],
    queryFn: () => getSafetyEvalRunDetail(runId, { limit: 100, offset: 0 }),
  });

  const run = detailQuery.data;
  const results: SafetyEvalResultResponse[] = run?.results?.items ?? [];

  return (
    <aside
      ref={panelRef as React.RefObject<HTMLElement>}
      role="dialog"
      aria-modal="true"
      aria-labelledby="safety-run-detail-title"
      className="absolute top-3 right-0 z-20 max-h-[min(90vh,820px)] w-full max-w-[520px] overflow-y-auto rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-2xl"
    >
      <div className="mb-4 flex items-start justify-between gap-3 border-b border-[#e4e1ee] pb-3">
        <div>
          <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
            Run detail
          </p>
          <h3
            id="safety-run-detail-title"
            className="mt-1 text-base font-semibold text-[#1b1b24]"
          >
            Safety eval results
          </h3>
        </div>
        <button
          type="button"
          data-overlay-autofocus="true"
          onClick={onClose}
          className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#38485d] hover:bg-[#f5f2ff]"
        >
          Close
        </button>
      </div>

      {detailQuery.isLoading ? (
        <LoadingState compact title="Loading run results..." />
      ) : null}

      {detailQuery.isError ? (
        <ErrorState
          compact
          error={detailQuery.error}
          description={getApiErrorMessage(detailQuery.error)}
        />
      ) : null}

      {run ? (
        <section className="space-y-4">
          <dl className="grid grid-cols-2 gap-2 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3 text-xs">
            <div>
              <dt className="font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Status
              </dt>
              <dd className="mt-0.5">
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${runStatusClass(run.status)}`}
                >
                  {run.status}
                </span>
              </dd>
            </div>
            <div>
              <dt className="font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Pass rate
              </dt>
              <dd className="mt-0.5">{passRateBadge(run.pass_rate)}</dd>
            </div>
            <div>
              <dt className="font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Pass / Fail
              </dt>
              <dd className="mt-0.5 font-mono text-[#302f39]">
                {run.pass_count ?? "—"} / {run.fail_count ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Suite
              </dt>
              <dd className="mt-0.5 text-[#302f39]">
                {run.suite_name ?? "All"}
              </dd>
            </div>
            {run.completed_at ? (
              <div className="col-span-2">
                <dt className="font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  Completed
                </dt>
                <dd className="mt-0.5 font-mono text-[#302f39]">
                  {formatTimestamp(run.completed_at)}
                </dd>
              </div>
            ) : null}
          </dl>

          {results.length > 0 ? (
            <div>
              <h4 className="mb-2 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Case results ({results.length})
              </h4>
              <div className="space-y-2">
                {results.map((r) => (
                  <article
                    key={r.result_id}
                    className="rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-[#1b1b24]">
                          {r.case_name}
                        </p>
                        <p className="text-[10px] text-[#777587]">
                          {r.violation_type} · {r.suite_name}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${severityClass(r.severity)}`}
                        >
                          {r.severity}
                        </span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${passFailClass(r.passed)}`}
                        >
                          {r.passed ? "PASS" : "FAIL"}
                        </span>
                      </div>
                    </div>
                    {!r.passed && r.details?.outcome ? (
                      <p className="mt-1.5 text-xs text-rose-700">
                        {String(r.details.outcome)} —{" "}
                        {String(r.details.expected ?? "")}
                      </p>
                    ) : null}
                    <p className="mt-1 text-right text-[10px] text-[#777587]">
                      {formatDuration(r.latency_ms)}
                    </p>
                  </article>
                ))}
              </div>
            </div>
          ) : null}

          {run.status === "completed" && results.length === 0 ? (
            <EmptyState compact title="No cases were scored in this run." />
          ) : null}
        </section>
      ) : null}
    </aside>
  );
}

export function AdminSafetyEvalPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const queryClient = useQueryClient();

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [suiteNameFilter, setSuiteNameFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const tableHostRef = useRef<HTMLDivElement | null>(null);

  const closePanel = useCallback(() => setSelectedRunId(null), []);

  const queryParams = useMemo(
    () => ({
      suite_name: suiteNameFilter.trim() || undefined,
      limit: PAGE_LIMIT,
      offset,
    }),
    [suiteNameFilter, offset],
  );

  const runsQuery = useQuery({
    queryKey: ["safety-evals", "runs", "list", queryParams],
    queryFn: () => listSafetyEvalRuns(queryParams),
    enabled: isAdminUser,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const hasRunning = items.some(
        (r) => r.status === "running" || r.status === "queued",
      );
      return hasRunning ? 5000 : false;
    },
  });

  const casesQuery = useQuery({
    queryKey: [
      "safety-evals",
      "cases",
      "list",
      { suite_name: queryParams.suite_name },
    ],
    queryFn: () =>
      listSafetyEvalCases({ suite_name: queryParams.suite_name, limit: 1 }),
    enabled: isAdminUser,
  });

  const triggerMutation = useMutation({
    mutationFn: triggerSafetyEvalRun,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["safety-evals", "runs"],
      });
    },
  });

  const forbiddenError =
    runsQuery.isError && isForbiddenError(runsQuery.error)
      ? runsQuery.error
      : null;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Safety evaluation restricted"
          description="Only owner and admin roles can access safety evaluations."
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Safety evaluation unavailable"
          description="Your role no longer has access to this page."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  const runs: SafetyEvalRunResponse[] = runsQuery.data?.items ?? [];
  const pageTotal = runsQuery.data?.total ?? 0;
  const pageStart = pageTotal === 0 ? 0 : offset + 1;
  const pageEnd =
    pageTotal === 0 ? 0 : Math.min(offset + PAGE_LIMIT, pageTotal);
  const hasPreviousPage = offset > 0;
  const hasNextPage = offset + PAGE_LIMIT < pageTotal;
  const totalCases = casesQuery.data?.total ?? 0;

  const latestRun = runs[0];
  const passedRuns = runs.filter(
    (r) => r.status === "completed" && (r.pass_rate ?? 0) >= 1.0,
  ).length;
  const failedRuns = runs.filter(
    (r) => r.status === "completed" && (r.pass_rate ?? 1.0) < 1.0,
  ).length;

  return (
    <section className="space-y-5 bg-[#fcf8ff] px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-semibold tracking-[0.16em] text-[#3525cd] uppercase">
              AI Safety
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-[#1b1b24]">
              Safety eval suite
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-[#464555]">
              Red-team evaluation covering prompt injection, cross-tenant
              leakage, unsupported claims, malicious document instructions, and
              unsafe output transformations.
            </p>
          </div>
          <button
            type="button"
            disabled={triggerMutation.isPending}
            onClick={() =>
              triggerMutation.mutate({
                suite_name: suiteNameFilter.trim() || undefined,
              })
            }
            className="h-10 rounded-lg bg-[#3525cd] px-4 text-xs font-semibold tracking-wide text-white uppercase hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {triggerMutation.isPending ? "Queuing..." : "Run safety eval"}
          </button>
        </div>
        {triggerMutation.isError ? (
          <p className="mt-3 text-sm text-rose-700">
            {getApiErrorMessage(triggerMutation.error)}
          </p>
        ) : null}
        {triggerMutation.isSuccess ? (
          <p className="mt-3 text-sm text-emerald-700">
            Run queued — {triggerMutation.data.message}
          </p>
        ) : null}
      </header>

      <section className="grid gap-4 md:grid-cols-3">
        <article className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
            Total cases
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-[#1b1b24]">
            {totalCases}
          </p>
        </article>
        <article className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-emerald-700 uppercase">
            All-pass runs (page)
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-emerald-700">
            {passedRuns}
          </p>
        </article>
        <article className="rounded-xl border border-rose-200 bg-rose-50/50 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-rose-700 uppercase">
            Regressions (page)
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-rose-700">
            {failedRuns}
          </p>
        </article>
      </section>

      {latestRun?.status === "completed" && latestRun.pass_rate != null ? (
        <section className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-[#1b1b24]">
            Latest run summary
          </h2>
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Pass rate
              </p>
              <p className="mt-1 font-mono text-2xl font-semibold">
                {passRateBadge(latestRun.pass_rate)}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Pass / Fail / Total
              </p>
              <p className="mt-1 font-mono text-lg font-semibold text-[#302f39]">
                {latestRun.pass_count} / {latestRun.fail_count} /{" "}
                {latestRun.total_count}
              </p>
            </div>
            {latestRun.suite_name ? (
              <div>
                <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  Suite
                </p>
                <p className="mt-1 text-sm font-semibold text-[#302f39]">
                  {latestRun.suite_name}
                </p>
              </div>
            ) : null}
            <div>
              <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Completed
              </p>
              <p className="mt-1 font-mono text-sm text-[#464555]">
                {formatTimestamp(latestRun.completed_at)}
              </p>
            </div>
          </div>
        </section>
      ) : null}

      <section className="rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[200px] flex-1 space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Filter by suite
            </span>
            <input
              value={suiteNameFilter}
              onChange={(e) => {
                setSuiteNameFilter(e.target.value);
                setOffset(0);
              }}
              placeholder="e.g. prompt_injection"
              className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            />
          </label>
          {suiteNameFilter ? (
            <button
              type="button"
              onClick={() => {
                setSuiteNameFilter("");
                setOffset(0);
              }}
              className="h-10 px-2 text-xs font-semibold text-[#3525cd] uppercase hover:underline"
            >
              Clear
            </button>
          ) : null}
        </div>
      </section>

      <div ref={tableHostRef} className="relative">
        <section className="overflow-hidden rounded-xl border border-[#c7c4d8] bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e4e1ee] bg-[#f5f2ff] px-4 py-3">
            <h2 className="text-lg font-semibold text-[#1b1b24]">
              Eval run history
            </h2>
            {runsQuery.isSuccess ? (
              <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Showing {pageStart}–{pageEnd} of {pageTotal}
              </p>
            ) : null}
          </div>

          {runsQuery.isLoading ? (
            <LoadingState
              compact
              className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2"
              title="Loading safety eval runs..."
            />
          ) : null}

          {runsQuery.isError && !forbiddenError ? (
            <div className="m-4">
              <ErrorState
                compact
                error={runsQuery.error}
                description={getApiErrorMessage(runsQuery.error)}
                onRetry={() => {
                  void runsQuery.refetch();
                }}
              />
            </div>
          ) : null}

          {runsQuery.isSuccess && runs.length === 0 ? (
            <EmptyState
              compact
              className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2"
              title="No safety eval runs yet. Click 'Run safety eval' to start."
            />
          ) : null}

          {runsQuery.isSuccess && runs.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead className="border-b border-[#e4e1ee] bg-[#fcf8ff]">
                    <tr className="text-left text-[11px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      <th className="px-4 py-3">Started</th>
                      <th className="px-4 py-3">Suite</th>
                      <th className="px-4 py-3 text-center">Status</th>
                      <th className="px-4 py-3 text-center">Pass rate</th>
                      <th className="px-4 py-3">Pass / Fail / Total</th>
                      <th className="px-4 py-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#ece9f5]">
                    {runs.map((run) => {
                      const isSelected = selectedRunId === run.run_id;
                      return (
                        <tr
                          key={run.run_id}
                          onClick={() => setSelectedRunId(run.run_id)}
                          className={`cursor-pointer transition-colors ${
                            isSelected ? "bg-[#ebe8ff]" : "hover:bg-[#f5f2ff]"
                          }`}
                        >
                          <td className="px-4 py-3 font-mono text-xs text-[#464555]">
                            {formatTimestamp(run.started_at ?? run.created_at)}
                          </td>
                          <td className="px-4 py-3 text-sm text-[#302f39]">
                            {run.suite_name ?? (
                              <span className="text-[#777587]">All suites</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span
                              className={`rounded-full px-2 py-1 text-[10px] font-semibold tracking-wide uppercase ${runStatusClass(run.status)}`}
                            >
                              {run.status}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-center">
                            {passRateBadge(run.pass_rate)}
                          </td>
                          <td className="px-4 py-3 font-mono text-xs text-[#464555]">
                            {run.pass_count ?? "—"} / {run.fail_count ?? "—"} /{" "}
                            {run.total_count ?? "—"}
                          </td>
                          <td className="px-4 py-3">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedRunId(run.run_id);
                              }}
                              className="rounded-lg border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f2ff]"
                            >
                              View
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between gap-3 border-t border-[#e4e1ee] px-4 py-3">
                <p className="text-sm text-[#464555]">
                  Showing {pageStart} to {pageEnd} of {pageTotal} runs
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      setOffset((p) => Math.max(0, p - PAGE_LIMIT))
                    }
                    disabled={!hasPreviousPage || runsQuery.isFetching}
                    className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    onClick={() => setOffset((p) => p + PAGE_LIMIT)}
                    disabled={!hasNextPage || runsQuery.isFetching}
                    className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </section>

        {selectedRunId ? (
          <>
            <button
              type="button"
              aria-label="Close run detail"
              onClick={closePanel}
              className="absolute inset-0 z-10 bg-[#17172a]/15 xl:bg-transparent"
            />
            <RunDetailPanel runId={selectedRunId} onClose={closePanel} />
          </>
        ) : null}
      </div>
    </section>
  );
}
