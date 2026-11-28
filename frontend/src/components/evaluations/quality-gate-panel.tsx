"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  createQualityGate,
  deleteQualityGate,
  getQualityGateReport,
  listQualityGateRuns,
  listQualityGates,
  overrideQualityGateRun,
  triggerQualityGateRun,
  type CreateQualityGateRequest,
  type GateCheckResult,
  type QualityGateResponse,
  type QualityGateRunResponse,
  type QualityGateThresholds,
} from "@/lib/api/quality-gates";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const qgKeys = {
  gates: ["quality-gates"] as const,
  runs: (gateId: string) => ["quality-gates", "runs", gateId] as const,
  report: (runId: string) => ["quality-gates", "report", runId] as const,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const KNOWN_VERDICTS = new Set(["passed", "failed", "overridden"]);

function VerdictBadge({ verdict }: { verdict: string }): React.ReactNode {
  const t = useTranslations("evaluations.qualityGate");
  const cls =
    verdict === "passed"
      ? "bg-green-100 text-green-800"
      : verdict === "overridden"
        ? "bg-yellow-100 text-yellow-800"
        : "bg-red-100 text-red-800";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {(KNOWN_VERDICTS.has(verdict)
        ? t(`verdict.${verdict}`)
        : verdict
      ).toUpperCase()}
    </span>
  );
}

const THRESHOLD_KEYS = new Set([
  "retrieval_hit_rate_min",
  "citation_accuracy_score_min",
  "faithfulness_score_min",
  "answer_relevance_score_min",
  "not_found_rate_max",
  "safety_pass_rate_min",
  "latency_ms_p95_max",
  "cost_usd_per_question_max",
]);

function formatMetric(value: number | null, metric: string): string {
  if (value == null) return "—";
  if (metric === "latency_ms_p95_max") return `${Math.round(value)} ms`;
  if (metric === "cost_usd_per_question_max") return `$${value.toFixed(4)}`;
  if (value <= 1) return `${(value * 100).toFixed(1)}%`;
  return value.toFixed(2);
}

function CheckList({
  checks,
  variant,
}: {
  checks: GateCheckResult[];
  variant: "passed" | "failed";
}): React.ReactNode {
  const t = useTranslations("evaluations.qualityGate");
  if (!checks.length) return null;
  return (
    <ul className="mt-1 space-y-0.5 text-xs">
      {checks.map((c) => (
        <li key={c.metric} className="flex items-start gap-1">
          <span
            className={variant === "passed" ? "text-green-600" : "text-red-600"}
          >
            {variant === "passed" ? "✓" : "✗"}
          </span>
          <span className="text-gray-700">
            {t("checkLine", {
              label: c.label,
              actual: formatMetric(c.actual, c.metric),
              threshold: formatMetric(c.threshold, c.metric),
            })}
            {c.detail ? ` — ${c.detail}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Gate run card
// ---------------------------------------------------------------------------

function GateRunCard({
  run,
  gateId,
}: {
  run: QualityGateRunResponse;
  gateId: string;
}): React.ReactNode {
  const t = useTranslations("evaluations.qualityGate");
  const qc = useQueryClient();
  const [overrideReason, setOverrideReason] = useState("");
  const [showOverride, setShowOverride] = useState(false);

  const { data: report } = useQuery({
    queryKey: qgKeys.report(run.gate_run_id),
    queryFn: () => getQualityGateReport(run.gate_run_id),
    enabled: run.verdict === "failed",
  });

  const overrideMutation = useMutation({
    mutationFn: () =>
      overrideQualityGateRun(run.gate_run_id, { reason: overrideReason }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qgKeys.runs(gateId) });
      qc.invalidateQueries({ queryKey: qgKeys.report(run.gate_run_id) });
      setShowOverride(false);
      setOverrideReason("");
    },
  });

  const createdAt = new Date(run.created_at).toLocaleString();

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <VerdictBadge verdict={run.verdict} />
          <span className="text-xs text-gray-500">{createdAt}</span>
        </div>
        <div className="flex gap-2 text-xs text-gray-500">
          <span>{t("failedCount", { count: run.failed_checks.length })}</span>
          <span>/</span>
          <span>{t("passedCount", { count: run.passed_checks.length })}</span>
        </div>
      </div>

      {run.failed_checks.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-medium text-red-700">
            {t("failingChecks")}
          </p>
          <CheckList checks={run.failed_checks} variant="failed" />
        </div>
      )}

      {run.passed_checks.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-medium text-green-700">
            {t("passingChecks")}
          </p>
          <CheckList checks={run.passed_checks} variant="passed" />
        </div>
      )}

      {run.override_reason && (
        <p className="mt-2 text-xs text-yellow-700 italic">
          {t("override", { reason: run.override_reason })}
        </p>
      )}

      {report && (
        <div className="mt-3 border-t border-gray-100 pt-2">
          <a
            href={`/api/v1/quality-gates/runs/${run.gate_run_id}/report/download`}
            download
            className="text-xs text-blue-600 hover:underline"
          >
            {t("downloadReport")}
          </a>
        </div>
      )}

      {run.verdict === "failed" && (
        <div className="mt-3 border-t border-gray-100 pt-3">
          {!showOverride ? (
            <button
              type="button"
              onClick={() => setShowOverride(true)}
              className="rounded bg-yellow-50 px-3 py-1.5 text-xs font-medium text-yellow-800 ring-1 ring-yellow-200 hover:bg-yellow-100"
            >
              {t("overrideButton")}
            </button>
          ) : (
            <div className="space-y-2">
              <textarea
                className="w-full rounded border border-gray-300 p-2 text-xs focus:ring-1 focus:ring-blue-400 focus:outline-none"
                rows={3}
                placeholder={t("overridePlaceholder")}
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={
                    overrideReason.trim().length < 10 ||
                    overrideMutation.isPending
                  }
                  onClick={() => overrideMutation.mutate()}
                  className="rounded bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700 disabled:opacity-50"
                >
                  {overrideMutation.isPending
                    ? t("applying")
                    : t("applyOverride")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowOverride(false);
                    setOverrideReason("");
                  }}
                  className="rounded px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100"
                >
                  {t("cancel")}
                </button>
              </div>
              {overrideMutation.isError && (
                <ErrorState
                  compact
                  error={overrideMutation.error}
                  onRetry={() => overrideMutation.mutate()}
                />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gate detail section
// ---------------------------------------------------------------------------

function GateDetail({ gate }: { gate: QualityGateResponse }): React.ReactNode {
  const t = useTranslations("evaluations.qualityGate");
  const qc = useQueryClient();
  const [evalRunId, setEvalRunId] = useState("");
  const [safetyRunId, setSafetyRunId] = useState("");

  const { data: runsData, isLoading: runsLoading } = useQuery({
    queryKey: qgKeys.runs(gate.quality_gate_id),
    queryFn: () => listQualityGateRuns(gate.quality_gate_id),
  });

  const triggerMutation = useMutation({
    mutationFn: () =>
      triggerQualityGateRun(gate.quality_gate_id, {
        evaluation_run_id: evalRunId || null,
        safety_eval_run_id: safetyRunId || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qgKeys.runs(gate.quality_gate_id) });
      setEvalRunId("");
      setSafetyRunId("");
    },
  });

  const thresholds = gate.thresholds as QualityGateThresholds;
  const thresholdEntries = Object.entries(thresholds).filter(
    ([, v]) => v != null,
  );

  return (
    <div className="space-y-4">
      {thresholdEntries.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold tracking-wide text-gray-500 uppercase">
            {t("configuredThresholds")}
          </h4>
          <ul className="space-y-0.5">
            {thresholdEntries.map(([key, value]) => (
              <li key={key} className="text-xs text-gray-700">
                <span className="font-medium">
                  {THRESHOLD_KEYS.has(key)
                    ? t(`thresholds.${key}`)
                    : key.replace(/_/g, " ")}
                  :
                </span>{" "}
                {formatMetric(value as number, key)}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h4 className="mb-1 text-xs font-semibold tracking-wide text-gray-500 uppercase">
          {t("triggerRun")}
        </h4>
        <div className="flex flex-col gap-2">
          <input
            type="text"
            placeholder={t("evalRunPlaceholder")}
            value={evalRunId}
            onChange={(e) => setEvalRunId(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1.5 text-xs focus:ring-1 focus:ring-blue-400 focus:outline-none"
          />
          <input
            type="text"
            placeholder={t("safetyRunPlaceholder")}
            value={safetyRunId}
            onChange={(e) => setSafetyRunId(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1.5 text-xs focus:ring-1 focus:ring-blue-400 focus:outline-none"
          />
          <button
            type="button"
            disabled={(!evalRunId && !safetyRunId) || triggerMutation.isPending}
            onClick={() => triggerMutation.mutate()}
            className="self-start rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {triggerMutation.isPending ? t("running") : t("runGate")}
          </button>
          {triggerMutation.isError && (
            <ErrorState
              compact
              error={triggerMutation.error}
              onRetry={() => triggerMutation.mutate()}
            />
          )}
          {triggerMutation.isSuccess && (
            <p className="text-xs text-green-600">{t("runCompleted")}</p>
          )}
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-xs font-semibold tracking-wide text-gray-500 uppercase">
          {t("runHistory")}
        </h4>
        {runsLoading ? (
          <LoadingState compact title={t("loadingRuns")} />
        ) : !runsData?.items.length ? (
          <EmptyState
            compact
            title={t("noRuns")}
            description={t("noRunsHint")}
          />
        ) : (
          <div className="space-y-3">
            {runsData.items.map((run) => (
              <GateRunCard
                key={run.gate_run_id}
                run={run}
                gateId={gate.quality_gate_id}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create gate form
// ---------------------------------------------------------------------------

function CreateGateForm({
  onCreated,
}: {
  onCreated: () => void;
}): React.ReactNode {
  const t = useTranslations("evaluations.qualityGate");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [thresholdFields, setThresholdFields] = useState<
    Record<string, string>
  >({});
  const qc = useQueryClient();

  const THRESHOLD_FIELDS: [keyof QualityGateThresholds, string][] = [
    ["retrieval_hit_rate_min", "range"],
    ["citation_accuracy_score_min", "range"],
    ["faithfulness_score_min", "range"],
    ["answer_relevance_score_min", "range"],
    ["not_found_rate_max", "range"],
    ["safety_pass_rate_min", "range"],
    ["latency_ms_p95_max", "ms"],
    ["cost_usd_per_question_max", "usd"],
  ];

  const createMutation = useMutation({
    mutationFn: () => {
      const thresholds: QualityGateThresholds = {};
      for (const [key, raw] of Object.entries(thresholdFields)) {
        const parsed = parseFloat(raw);
        if (!isNaN(parsed)) {
          (thresholds as Record<string, number>)[key] = parsed;
        }
      }
      const payload: CreateQualityGateRequest = {
        name,
        description: description || null,
        thresholds,
      };
      return createQualityGate(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qgKeys.gates });
      setName("");
      setDescription("");
      setThresholdFields({});
      onCreated();
    },
  });

  return (
    <div className="space-y-3">
      <input
        type="text"
        placeholder={t("gateNamePlaceholder")}
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:ring-1 focus:ring-blue-400 focus:outline-none"
      />
      <input
        type="text"
        placeholder={t("descriptionPlaceholder")}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:ring-1 focus:ring-blue-400 focus:outline-none"
      />
      <div className="grid grid-cols-2 gap-2">
        {THRESHOLD_FIELDS.map(([key, hint]) => (
          <div key={key} className="flex flex-col gap-0.5">
            <label className="text-xs text-gray-600">
              {t(`thresholds.${key}`)}{" "}
              <span className="text-gray-400">({t(`hint.${hint}`)})</span>
            </label>
            <input
              type="number"
              step="0.01"
              min="0"
              max={
                key.endsWith("_min") || key.endsWith("_max") ? "1" : undefined
              }
              placeholder={t("blankToSkip")}
              value={thresholdFields[key] ?? ""}
              onChange={(e) =>
                setThresholdFields((prev) => ({
                  ...prev,
                  [key]: e.target.value,
                }))
              }
              className="rounded border border-gray-300 px-2 py-1 text-xs focus:ring-1 focus:ring-blue-400 focus:outline-none"
            />
          </div>
        ))}
      </div>
      <button
        type="button"
        disabled={!name.trim() || createMutation.isPending}
        onClick={() => createMutation.mutate()}
        className="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {createMutation.isPending ? t("creating") : t("createGate")}
      </button>
      {createMutation.isError && (
        <ErrorState compact error={createMutation.error} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function QualityGatePanel(): React.ReactNode {
  const t = useTranslations("evaluations.qualityGate");
  const qc = useQueryClient();
  const [selectedGateId, setSelectedGateId] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);

  const {
    data: gatesData,
    isLoading,
    error,
  } = useQuery({
    queryKey: qgKeys.gates,
    queryFn: () => listQualityGates(),
  });

  const deleteMutation = useMutation({
    mutationFn: (gateId: string) => deleteQualityGate(gateId),
    onSuccess: (_, gateId) => {
      if (selectedGateId === gateId) setSelectedGateId(null);
      qc.invalidateQueries({ queryKey: qgKeys.gates });
    },
  });

  if (isLoading) {
    return <LoadingState title={t("loadingGates")} />;
  }

  if (error) {
    return (
      <ErrorState
        error={error}
        onRetry={() => void qc.invalidateQueries({ queryKey: qgKeys.gates })}
      />
    );
  }

  const gates = gatesData?.items ?? [];
  const selectedGate =
    gates.find((g) => g.quality_gate_id === selectedGateId) ?? null;

  return (
    <div className="flex h-full gap-4">
      {/* Gate list */}
      <div className="flex w-64 flex-shrink-0 flex-col gap-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">{t("title")}</h3>
          <button
            type="button"
            onClick={() => setShowCreateForm((v) => !v)}
            className="rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50"
          >
            {showCreateForm ? t("cancel") : t("newGate")}
          </button>
        </div>

        {showCreateForm && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
            <CreateGateForm onCreated={() => setShowCreateForm(false)} />
          </div>
        )}

        {gates.length === 0 && !showCreateForm ? (
          <EmptyState
            compact
            title={t("noGates")}
            description={t("noGatesHint")}
          />
        ) : (
          <ul className="space-y-1">
            {gates.map((gate) => (
              <li key={gate.quality_gate_id}>
                <button
                  type="button"
                  onClick={() =>
                    setSelectedGateId(
                      gate.quality_gate_id === selectedGateId
                        ? null
                        : gate.quality_gate_id,
                    )
                  }
                  className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                    selectedGateId === gate.quality_gate_id
                      ? "bg-blue-100 text-blue-900"
                      : "text-gray-700 hover:bg-gray-100"
                  }`}
                >
                  <p className="truncate font-medium">{gate.name}</p>
                  {gate.description && (
                    <p className="truncate text-xs text-gray-400">
                      {gate.description}
                    </p>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Gate detail */}
      <div className="flex-1 overflow-y-auto">
        {selectedGate ? (
          <div className="space-y-4">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-base font-semibold text-gray-900">
                  {selectedGate.name}
                </h3>
                {selectedGate.description && (
                  <p className="mt-0.5 text-sm text-gray-500">
                    {selectedGate.description}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => {
                  if (
                    window.confirm(
                      t("confirmDelete", { name: selectedGate.name }),
                    )
                  ) {
                    deleteMutation.mutate(selectedGate.quality_gate_id);
                  }
                }}
                className="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50"
              >
                {t("delete")}
              </button>
            </div>
            <GateDetail gate={selectedGate} />
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-gray-400">
            {t("select")}
          </div>
        )}
      </div>
    </div>
  );
}
