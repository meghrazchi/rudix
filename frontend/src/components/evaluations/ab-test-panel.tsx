"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addVariant,
  approveVariant,
  createAbExperiment,
  deleteAbExperiment,
  finalizeExperimentRun,
  getAbExperiment,
  listAbExperiments,
  listExperimentRuns,
  rejectVariant,
  removeVariant,
  startExperimentRun,
  type AbVariantResponse,
  type CreateAbExperimentRequest,
  type CreateAbVariantRequest,
  type VariantRunSummary,
} from "@/lib/api/ab-testing";
import { getApiErrorMessage } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const abKeys = {
  experiments: ["ab-experiments"] as const,
  experiment: (id: string) => ["ab-experiments", id] as const,
  runs: (id: string) => ["ab-experiments", id, "runs"] as const,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusBadge(s: string): React.ReactNode {
  const cls =
    s === "completed"
      ? "bg-green-100 text-green-800"
      : s === "running"
        ? "bg-blue-100 text-blue-800"
        : s === "failed"
          ? "bg-red-100 text-red-800"
          : "bg-gray-100 text-gray-600";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {s.toUpperCase()}
    </span>
  );
}

function approvalBadge(s: string): React.ReactNode {
  const cls =
    s === "approved"
      ? "bg-green-100 text-green-800"
      : s === "rejected"
        ? "bg-red-100 text-red-800"
        : "bg-yellow-100 text-yellow-800";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {s.toUpperCase()}
    </span>
  );
}

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function deltaLabel(
  d: number | null | undefined,
  _improved: boolean | null | undefined,
): string {
  if (d == null) return "—";
  const sign = d > 0 ? "+" : "";
  return `${sign}${(d * 100).toFixed(2)}%`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    isRecord(value) &&
    Object.values(value).every((entry) => typeof entry === "string")
  );
}

// ---------------------------------------------------------------------------
// Comparison table
// ---------------------------------------------------------------------------

function ComparisonTable({
  summaries,
}: {
  summaries: VariantRunSummary[];
}): React.ReactNode {
  if (!summaries.length)
    return <p className="text-sm text-gray-500">No variant results yet.</p>;

  const metrics = summaries[0].deltas_vs_reference.length
    ? summaries[0].deltas_vs_reference.map((d) => ({
        key: d.metric,
        label: d.label,
      }))
    : [
        { key: "faithfulness_score", label: "Faithfulness" },
        { key: "citation_accuracy_score", label: "Citation Accuracy" },
        { key: "answer_relevance_score", label: "Answer Relevance" },
        { key: "latency_ms_p95", label: "Latency p95 (ms)" },
      ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-gray-500 uppercase">
            <th className="py-2 pr-4 font-medium">Metric</th>
            {summaries.map((s) => (
              <th key={s.variant_id} className="py-2 pr-4 font-medium">
                {s.variant_label}
                <span className="ml-1 font-normal">
                  ({statusBadge(s.status)})
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.map(({ key, label }) => (
            <tr key={key} className="border-b last:border-0">
              <td className="py-1.5 pr-4 text-gray-700">{label}</td>
              {summaries.map((s, idx) => {
                const val = s.metrics_summary[key] as number | null | undefined;
                const delta = s.deltas_vs_reference.find(
                  (d) => d.metric === key,
                );
                return (
                  <td key={s.variant_id} className="py-1.5 pr-4">
                    <span className="font-mono">
                      {key.includes("latency") || key.includes("cost")
                        ? val != null
                          ? key.includes("ms")
                            ? `${Math.round(val)} ms`
                            : `$${Number(val).toFixed(4)}`
                          : "—"
                        : pct(val)}
                    </span>
                    {idx > 0 && delta && (
                      <span
                        className={`ml-1 text-xs ${
                          delta.improved === true
                            ? "text-green-700"
                            : delta.improved === false
                              ? "text-red-700"
                              : "text-gray-400"
                        }`}
                      >
                        ({deltaLabel(delta.delta, delta.improved)})
                      </span>
                    )}
                    {idx === 0 && (
                      <span className="ml-1 text-xs text-gray-400">(ref)</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Variant card
// ---------------------------------------------------------------------------

function VariantCard({
  variant,
  experimentId: _experimentId,
  onApprove,
  onReject,
  onRemove,
}: {
  variant: AbVariantResponse;
  experimentId: string;
  onApprove: (variantId: string) => void;
  onReject: (variantId: string) => void;
  onRemove: (variantId: string) => void;
}): React.ReactNode {
  return (
    <div className="rounded border p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="font-medium text-gray-900">{variant.label}</span>
          {variant.description && (
            <p className="mt-0.5 text-xs text-gray-500">
              {variant.description}
            </p>
          )}
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
            {variant.rag_profile_id && (
              <span>RAG profile v{variant.rag_profile_version ?? "?"}</span>
            )}
            {variant.model_profile_key && (
              <span>Model: {variant.model_profile_key}</span>
            )}
            {variant.prompt_template_version_id && (
              <span>
                Prompt version: {variant.prompt_template_version_id.slice(0, 8)}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {approvalBadge(variant.approval_status)}
          {variant.approval_status === "pending" && (
            <>
              <button
                onClick={() => onApprove(variant.variant_id)}
                className="rounded bg-green-50 px-2 py-0.5 text-xs text-green-700 hover:bg-green-100"
              >
                Approve
              </button>
              <button
                onClick={() => onReject(variant.variant_id)}
                className="rounded bg-red-50 px-2 py-0.5 text-xs text-red-700 hover:bg-red-100"
              >
                Reject
              </button>
            </>
          )}
          <button
            onClick={() => onRemove(variant.variant_id)}
            className="rounded px-2 py-0.5 text-xs text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create experiment form
// ---------------------------------------------------------------------------

function CreateExperimentForm({
  onSubmit,
  onCancel,
  loading,
}: {
  onSubmit: (req: CreateAbExperimentRequest) => void;
  onCancel: () => void;
  loading: boolean;
}): React.ReactNode {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [evaluationSetId, setEvaluationSetId] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !evaluationSetId.trim()) return;
    onSubmit({
      name: name.trim(),
      description: description.trim() || null,
      evaluation_set_id: evaluationSetId.trim(),
    });
  }

  return (
    <form onSubmit={handleSubmit} className="rounded border p-4">
      <h3 className="mb-3 font-medium">New A/B Experiment</h3>
      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-700">
            Name *
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded border px-2 py-1.5 text-sm"
            placeholder="e.g. Prompt v2 vs v3 — faithfulness"
            required
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-700">
            Description
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded border px-2 py-1.5 text-sm"
            rows={2}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-700">
            Evaluation Set ID *
          </label>
          <input
            value={evaluationSetId}
            onChange={(e) => setEvaluationSetId(e.target.value)}
            className="w-full rounded border px-2 py-1.5 font-mono text-sm"
            placeholder="UUID of evaluation dataset"
            required
          />
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <button
          type="submit"
          disabled={loading}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Creating…" : "Create Experiment"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Add variant form
// ---------------------------------------------------------------------------

function AddVariantForm({
  experimentId,
  onSuccess,
  onCancel,
}: {
  experimentId: string;
  onSuccess: () => void;
  onCancel: () => void;
}): React.ReactNode {
  const qc = useQueryClient();
  const [label, setLabel] = useState("");
  const [ragProfileId, setRagProfileId] = useState("");
  const [ragProfileVersion, setRagProfileVersion] = useState("");
  const [modelProfileKey, setModelProfileKey] = useState("");
  const [promptVersionId, setPromptVersionId] = useState("");

  const mutation = useMutation({
    mutationFn: (req: CreateAbVariantRequest) => addVariant(experimentId, req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: abKeys.experiment(experimentId) });
      onSuccess();
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!label.trim()) return;
    mutation.mutate({
      label: label.trim(),
      rag_profile_id: ragProfileId.trim() || null,
      rag_profile_version: ragProfileVersion
        ? parseInt(ragProfileVersion, 10)
        : null,
      model_profile_key: modelProfileKey.trim() || null,
      prompt_template_version_id: promptVersionId.trim() || null,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 rounded border p-3">
      <h4 className="mb-2 text-sm font-medium">Add Variant</h4>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="col-span-2">
          <label className="mb-0.5 block font-medium text-gray-700">
            Label *
          </label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-full rounded border px-2 py-1 text-sm"
            placeholder="e.g. Control / Prompt-v2 / profile-A"
            required
          />
        </div>
        <div>
          <label className="mb-0.5 block font-medium text-gray-700">
            RAG Profile ID
          </label>
          <input
            value={ragProfileId}
            onChange={(e) => setRagProfileId(e.target.value)}
            className="w-full rounded border px-2 py-1 font-mono text-sm"
            placeholder="UUID"
          />
        </div>
        <div>
          <label className="mb-0.5 block font-medium text-gray-700">
            Profile Version
          </label>
          <input
            type="number"
            value={ragProfileVersion}
            onChange={(e) => setRagProfileVersion(e.target.value)}
            className="w-full rounded border px-2 py-1 text-sm"
            min={1}
          />
        </div>
        <div>
          <label className="mb-0.5 block font-medium text-gray-700">
            Model Profile Key
          </label>
          <input
            value={modelProfileKey}
            onChange={(e) => setModelProfileKey(e.target.value)}
            className="w-full rounded border px-2 py-1 text-sm"
            placeholder="e.g. cloud_baseline"
          />
        </div>
        <div>
          <label className="mb-0.5 block font-medium text-gray-700">
            Prompt Version ID
          </label>
          <input
            value={promptVersionId}
            onChange={(e) => setPromptVersionId(e.target.value)}
            className="w-full rounded border px-2 py-1 font-mono text-sm"
            placeholder="UUID"
          />
        </div>
      </div>
      {mutation.error && (
        <p className="mt-1 text-xs text-red-600">
          {getApiErrorMessage(mutation.error)}
        </p>
      )}
      <div className="mt-2 flex gap-2">
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {mutation.isPending ? "Adding…" : "Add Variant"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded px-3 py-1 text-xs text-gray-600 hover:bg-gray-100"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Experiment detail panel
// ---------------------------------------------------------------------------

function ExperimentDetail({
  experimentId,
}: {
  experimentId: string;
}): React.ReactNode {
  const qc = useQueryClient();
  const [showAddVariant, setShowAddVariant] = useState(false);

  const { data: exp, isLoading } = useQuery({
    queryKey: abKeys.experiment(experimentId),
    queryFn: () => getAbExperiment(experimentId),
  });

  const { data: runsData } = useQuery({
    queryKey: abKeys.runs(experimentId),
    queryFn: () => listExperimentRuns(experimentId),
  });

  const startRun = useMutation({
    mutationFn: () => startExperimentRun(experimentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: abKeys.runs(experimentId) });
      qc.invalidateQueries({ queryKey: abKeys.experiment(experimentId) });
    },
  });

  const finalizeRun = useMutation({
    mutationFn: (runId: string) => finalizeExperimentRun(experimentId, runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: abKeys.runs(experimentId) });
    },
  });

  const approve = useMutation({
    mutationFn: (variantId: string) =>
      approveVariant(experimentId, variantId, {
        set_as_default_profile: false,
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: abKeys.experiment(experimentId) }),
  });

  const reject = useMutation({
    mutationFn: (variantId: string) => rejectVariant(experimentId, variantId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: abKeys.experiment(experimentId) }),
  });

  const deleteVariant = useMutation({
    mutationFn: (variantId: string) => removeVariant(experimentId, variantId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: abKeys.experiment(experimentId) }),
  });

  if (isLoading || !exp) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  const latestRun = runsData?.items[0] ?? null;
  const winnerByMetric = isStringRecord(
    latestRun?.comparison_report.winner_by_metric,
  )
    ? latestRun.comparison_report.winner_by_metric
    : null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-medium text-gray-900">{exp.name}</h3>
          {exp.description && (
            <p className="text-sm text-gray-500">{exp.description}</p>
          )}
          <div className="mt-1 flex items-center gap-2 text-xs text-gray-500">
            <span>
              Dataset:{" "}
              <code className="font-mono">
                {exp.evaluation_set_id.slice(0, 8)}
              </code>
            </span>
            {statusBadge(exp.status)}
          </div>
        </div>
        <button
          onClick={() => startRun.mutate()}
          disabled={
            startRun.isPending ||
            exp.status === "running" ||
            !exp.variants.length
          }
          className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {startRun.isPending ? "Starting…" : "Run Experiment"}
        </button>
      </div>

      {/* Variants */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-sm font-medium text-gray-700">
            Variants ({exp.variants.length})
          </h4>
          <button
            onClick={() => setShowAddVariant((v) => !v)}
            className="text-xs text-blue-600 hover:underline"
          >
            {showAddVariant ? "Cancel" : "+ Add variant"}
          </button>
        </div>
        {showAddVariant && (
          <AddVariantForm
            experimentId={experimentId}
            onSuccess={() => setShowAddVariant(false)}
            onCancel={() => setShowAddVariant(false)}
          />
        )}
        {exp.variants.length === 0 ? (
          <p className="text-sm text-gray-400">
            No variants yet — add at least two to compare.
          </p>
        ) : (
          <div className="space-y-2">
            {exp.variants.map((v) => (
              <VariantCard
                key={v.variant_id}
                variant={v}
                experimentId={experimentId}
                onApprove={(id) => approve.mutate(id)}
                onReject={(id) => reject.mutate(id)}
                onRemove={(id) => {
                  if (confirm(`Remove variant "${v.label}"?`))
                    deleteVariant.mutate(id);
                }}
              />
            ))}
          </div>
        )}
      </section>

      {/* Latest run comparison */}
      {latestRun && (
        <section>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-sm font-medium text-gray-700">
              Latest Run {statusBadge(latestRun.status)}
            </h4>
            {latestRun.status === "running" && (
              <button
                onClick={() => finalizeRun.mutate(latestRun.experiment_run_id)}
                disabled={finalizeRun.isPending}
                className="text-xs text-blue-600 hover:underline disabled:opacity-50"
              >
                {finalizeRun.isPending ? "Finalizing…" : "Finalize & compare"}
              </button>
            )}
          </div>
          {latestRun.status === "completed" &&
          latestRun.variant_summaries.length > 0 ? (
            <ComparisonTable summaries={latestRun.variant_summaries} />
          ) : (
            <p className="text-sm text-gray-400">
              {latestRun.status === "running"
                ? "Variant evaluation runs in progress. Finalize when all evaluations complete."
                : "No comparison data available."}
            </p>
          )}
          {winnerByMetric && Object.keys(winnerByMetric).length > 0 && (
            <div className="mt-3 rounded bg-green-50 p-2 text-xs text-green-800">
              <strong>Winners by metric:</strong>{" "}
              {Object.entries(winnerByMetric)
                .map(([metric, label]) => `${metric}: ${label}`)
                .join("; ")}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function AbTestPanel(): React.ReactNode {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: abKeys.experiments,
    queryFn: () => listAbExperiments(),
  });

  const createMutation = useMutation({
    mutationFn: createAbExperiment,
    onSuccess: (exp) => {
      qc.invalidateQueries({ queryKey: abKeys.experiments });
      setShowCreate(false);
      setSelectedId(exp.experiment_id);
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAbExperiment,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: abKeys.experiments });
      if (selectedId) setSelectedId(null);
    },
  });

  const experiments = data?.items ?? [];

  return (
    <div className="grid grid-cols-3 gap-6">
      {/* Sidebar — experiment list */}
      <aside className="col-span-1">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-wide text-gray-700 uppercase">
            A/B Experiments
          </h2>
          <button
            onClick={() => setShowCreate((v) => !v)}
            className="rounded bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-700"
          >
            + New
          </button>
        </div>

        {showCreate && (
          <div className="mb-4">
            {error && <p className="mb-2 text-xs text-red-600">{error}</p>}
            <CreateExperimentForm
              onSubmit={(req) => createMutation.mutate(req)}
              onCancel={() => {
                setShowCreate(false);
                setError(null);
              }}
              loading={createMutation.isPending}
            />
          </div>
        )}

        {isLoading ? (
          <p className="text-sm text-gray-400">Loading…</p>
        ) : experiments.length === 0 ? (
          <p className="text-sm text-gray-400">No experiments yet.</p>
        ) : (
          <ul className="space-y-1">
            {experiments.map((exp) => (
              <li key={exp.experiment_id}>
                <button
                  onClick={() => setSelectedId(exp.experiment_id)}
                  className={`w-full rounded px-3 py-2 text-left text-sm transition-colors ${
                    selectedId === exp.experiment_id
                      ? "bg-blue-50 text-blue-700"
                      : "text-gray-700 hover:bg-gray-100"
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="truncate font-medium">{exp.name}</span>
                    {statusBadge(exp.status)}
                  </div>
                  <div className="mt-0.5 text-xs text-gray-400">
                    {exp.variants.length} variant
                    {exp.variants.length !== 1 ? "s" : ""}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* Main — experiment detail */}
      <main className="col-span-2">
        {selectedId ? (
          <>
            <div className="mb-4 flex justify-end">
              <button
                onClick={() => {
                  if (confirm("Delete this experiment and all its data?")) {
                    deleteMutation.mutate(selectedId);
                  }
                }}
                disabled={deleteMutation.isPending}
                className="text-xs text-red-500 hover:underline disabled:opacity-50"
              >
                Delete experiment
              </button>
            </div>
            <ExperimentDetail experimentId={selectedId} />
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-gray-400">
            Select an experiment to view details.
          </div>
        )}
      </main>
    </div>
  );
}
