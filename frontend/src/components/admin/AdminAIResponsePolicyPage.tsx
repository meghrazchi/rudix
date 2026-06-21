"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activateAiResponsePolicy,
  createAiResponsePolicy,
  deactivateAiResponsePolicy,
  deleteAiResponsePolicy,
  listAiResponsePolicies,
  listPolicyEvaluationLogs,
  previewAiResponsePolicy,
  updateAiResponsePolicy,
  type AiResponsePolicyResponse,
  type CitationMode,
  type CreateAiResponsePolicyRequest,
  type DisclaimerPosition,
  type NoAnswerBehavior,
  type PolicyOutcome,
  type StaleSourceBehavior,
} from "@/lib/api/ai-response-policy";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tab = "policies" | "logs";

type FormState = {
  policy_name: string;
  description: string;
  citation_mode: CitationMode;
  min_confidence_threshold: string;
  no_answer_behavior: NoAnswerBehavior;
  stale_source_behavior: StaleSourceBehavior;
  blocked_topics: string;
  allowed_topics: string;
  min_sources_required: string;
  disclaimer_text: string;
  disclaimer_position: DisclaimerPosition;
  refusal_message: string;
};

type PanelState =
  | { kind: "idle" }
  | { kind: "create" }
  | { kind: "edit"; policy: AiResponsePolicyResponse }
  | { kind: "preview"; policy: AiResponsePolicyResponse };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CITATION_MODE_LABELS: Record<CitationMode, string> = {
  required: "Required",
  recommended: "Recommended",
  disabled: "Disabled",
};

const NO_ANSWER_LABELS: Record<NoAnswerBehavior, string> = {
  refuse: "Refuse (safe refusal)",
  warn: "Warn (allow with warning)",
  allow: "Allow (no restriction)",
};

const STALE_LABELS: Record<StaleSourceBehavior, string> = {
  warn: "Warn",
  refuse: "Refuse",
  ignore: "Ignore",
};

const OUTCOME_COLORS: Record<PolicyOutcome, string> = {
  allowed: "bg-green-100 text-green-800",
  blocked: "bg-red-100 text-red-800",
  warned: "bg-yellow-100 text-yellow-800",
};

function topicsFromRaw(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

function topicsToRaw(topics: string[] | null | undefined): string {
  return (topics ?? []).join(", ");
}

function emptyForm(): FormState {
  return {
    policy_name: "",
    description: "",
    citation_mode: "recommended",
    min_confidence_threshold: "",
    no_answer_behavior: "warn",
    stale_source_behavior: "warn",
    blocked_topics: "",
    allowed_topics: "",
    min_sources_required: "",
    disclaimer_text: "",
    disclaimer_position: "prepend",
    refusal_message: "",
  };
}

function policyToForm(policy: AiResponsePolicyResponse): FormState {
  return {
    policy_name: policy.policy_name,
    description: policy.description ?? "",
    citation_mode: policy.citation_mode,
    min_confidence_threshold:
      policy.min_confidence_threshold !== null
        ? String(policy.min_confidence_threshold)
        : "",
    no_answer_behavior: policy.no_answer_behavior,
    stale_source_behavior: policy.stale_source_behavior,
    blocked_topics: topicsToRaw(policy.blocked_topics),
    allowed_topics: topicsToRaw(policy.allowed_topics),
    min_sources_required:
      policy.min_sources_required !== null
        ? String(policy.min_sources_required)
        : "",
    disclaimer_text: policy.disclaimer_text ?? "",
    disclaimer_position: policy.disclaimer_position,
    refusal_message: policy.refusal_message ?? "",
  };
}

function formToRequest(form: FormState): CreateAiResponsePolicyRequest {
  return {
    policy_name: form.policy_name.trim(),
    description: form.description.trim() || null,
    citation_mode: form.citation_mode,
    min_confidence_threshold: form.min_confidence_threshold
      ? parseFloat(form.min_confidence_threshold)
      : null,
    no_answer_behavior: form.no_answer_behavior,
    stale_source_behavior: form.stale_source_behavior,
    blocked_topics: topicsFromRaw(form.blocked_topics),
    allowed_topics: form.allowed_topics.trim()
      ? topicsFromRaw(form.allowed_topics)
      : null,
    min_sources_required: form.min_sources_required
      ? parseInt(form.min_sources_required, 10)
      : null,
    disclaimer_text: form.disclaimer_text.trim() || null,
    disclaimer_position: form.disclaimer_position,
    refusal_message: form.refusal_message.trim() || null,
  };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function OutcomeChip({ outcome }: { outcome: PolicyOutcome }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${OUTCOME_COLORS[outcome]}`}
    >
      {outcome.charAt(0).toUpperCase() + outcome.slice(1)}
    </span>
  );
}

function PolicyStatusBadge({ isActive }: { isActive: boolean }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${
        isActive
          ? "bg-green-100 text-green-800"
          : "bg-gray-100 text-gray-600"
      }`}
    >
      {isActive ? "Active" : "Inactive"}
    </span>
  );
}

function PolicyForm({
  initial,
  onSubmit,
  onCancel,
  isPending,
  error,
}: {
  initial: FormState;
  onSubmit: (values: FormState) => void;
  onCancel: () => void;
  isPending: boolean;
  error: string | null;
}) {
  const [form, setForm] = useState<FormState>(initial);

  function handleChange(
    e: React.ChangeEvent<
      HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
    >,
  ) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit(form);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Policy Name *
        </label>
        <input
          name="policy_name"
          value={form.policy_name}
          onChange={handleChange}
          required
          maxLength={128}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="e.g. Enterprise Safety Policy"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Description
        </label>
        <textarea
          name="description"
          value={form.description}
          onChange={handleChange}
          rows={2}
          maxLength={1024}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="Optional description"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Citation Mode
          </label>
          <select
            name="citation_mode"
            value={form.citation_mode}
            onChange={handleChange}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {(["required", "recommended", "disabled"] as CitationMode[]).map(
              (m) => (
                <option key={m} value={m}>
                  {CITATION_MODE_LABELS[m]}
                </option>
              ),
            )}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Low-confidence Behavior
          </label>
          <select
            name="no_answer_behavior"
            value={form.no_answer_behavior}
            onChange={handleChange}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {(["refuse", "warn", "allow"] as NoAnswerBehavior[]).map((b) => (
              <option key={b} value={b}>
                {NO_ANSWER_LABELS[b]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Min. Confidence Threshold (0–1)
          </label>
          <input
            name="min_confidence_threshold"
            value={form.min_confidence_threshold}
            onChange={handleChange}
            type="number"
            step="0.01"
            min="0"
            max="1"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="e.g. 0.4 (leave blank to skip)"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Stale Source Behavior
          </label>
          <select
            name="stale_source_behavior"
            value={form.stale_source_behavior}
            onChange={handleChange}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {(["warn", "refuse", "ignore"] as StaleSourceBehavior[]).map(
              (b) => (
                <option key={b} value={b}>
                  {STALE_LABELS[b]}
                </option>
              ),
            )}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Min. Sources Required
          </label>
          <input
            name="min_sources_required"
            value={form.min_sources_required}
            onChange={handleChange}
            type="number"
            min="0"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="e.g. 1 (leave blank to skip)"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Disclaimer Position
          </label>
          <select
            name="disclaimer_position"
            value={form.disclaimer_position}
            onChange={handleChange}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="prepend">Before answer</option>
            <option value="append">After answer</option>
          </select>
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Blocked Topics{" "}
          <span className="font-normal text-gray-500">(comma-separated)</span>
        </label>
        <input
          name="blocked_topics"
          value={form.blocked_topics}
          onChange={handleChange}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="e.g. politics, gambling, medical advice"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Allowed Topics{" "}
          <span className="font-normal text-gray-500">
            (comma-separated, leave blank to allow all)
          </span>
        </label>
        <input
          name="allowed_topics"
          value={form.allowed_topics}
          onChange={handleChange}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="e.g. product support, billing"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Disclaimer Text
        </label>
        <textarea
          name="disclaimer_text"
          value={form.disclaimer_text}
          onChange={handleChange}
          rows={2}
          maxLength={2048}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="Text shown before or after every answer"
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Refusal Message
        </label>
        <textarea
          name="refusal_message"
          value={form.refusal_message}
          onChange={handleChange}
          rows={2}
          maxLength={1024}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="Message shown when a policy rule blocks an answer"
        />
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-gray-300 px-4 py-2 text-sm font-medium hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isPending}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}

function PolicyPreviewPanel({ policy }: { policy: AiResponsePolicyResponse }) {
  const [question, setQuestion] = useState("");
  const [confidenceScore, setConfidenceScore] = useState("0.8");
  const [citationCount, setCitationCount] = useState("1");
  const [staleCount, setStaleCount] = useState("0");
  const [error, setError] = useState<string | null>(null);

  const previewMutation = useMutation({
    mutationFn: () =>
      previewAiResponsePolicy({
        question,
        confidence_score: parseFloat(confidenceScore),
        citation_count: parseInt(citationCount, 10),
        stale_source_count: parseInt(staleCount, 10),
        policy_id: policy.policy_id,
      }),
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    previewMutation.mutate();
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        Simulate how <strong>{policy.policy_name}</strong> evaluates a
        hypothetical chat scenario — no live data is affected.
      </p>
      <form onSubmit={handleSubmit} className="space-y-3">
        {error && (
          <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Question *
          </label>
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            required
            maxLength={1024}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="e.g. What are the payment options?"
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">
              Confidence (0–1)
            </label>
            <input
              value={confidenceScore}
              onChange={(e) => setConfidenceScore(e.target.value)}
              type="number"
              step="0.01"
              min="0"
              max="1"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">
              Citations
            </label>
            <input
              value={citationCount}
              onChange={(e) => setCitationCount(e.target.value)}
              type="number"
              min="0"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">
              Stale sources
            </label>
            <input
              value={staleCount}
              onChange={(e) => setStaleCount(e.target.value)}
              type="number"
              min="0"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={previewMutation.isPending}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {previewMutation.isPending ? "Simulating…" : "Run Preview"}
        </button>
      </form>

      {previewMutation.data && (
        <div className="mt-4 space-y-2 rounded border border-gray-200 bg-gray-50 p-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-700">Outcome:</span>
            <OutcomeChip outcome={previewMutation.data.outcome} />
            <span className="text-xs text-gray-500">
              via {previewMutation.data.policy_source}
            </span>
          </div>
          {previewMutation.data.violated_rules.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600">
                Violated rules:
              </p>
              <ul className="mt-1 space-y-0.5">
                {previewMutation.data.violated_rules.map((r) => (
                  <li key={r} className="text-xs text-red-700">
                    • {r}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {previewMutation.data.warning_flags.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600">Warnings:</p>
              <ul className="mt-1 space-y-0.5">
                {previewMutation.data.warning_flags.map((f) => (
                  <li key={f} className="text-xs text-yellow-700">
                    • {f}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {previewMutation.data.refusal_message && (
            <p className="text-xs text-gray-700">
              <span className="font-medium">Refusal message:</span>{" "}
              {previewMutation.data.refusal_message}
            </p>
          )}
          {previewMutation.data.disclaimer_text && (
            <p className="text-xs text-gray-700">
              <span className="font-medium">Disclaimer:</span>{" "}
              {previewMutation.data.disclaimer_text}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function AdminAIResponsePolicyPage() {
  const { state } = useAuthSession();
  const session = state.status === "authenticated" ? state.session : null;
  const role = session?.role ?? null;
  const isAdmin = role === "owner" || role === "admin";

  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<Tab>("policies");
  const [panel, setPanel] = useState<PanelState>({ kind: "idle" });
  const [formError, setFormError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Queries
  // ---------------------------------------------------------------------------

  const {
    data: policiesData,
    isLoading: isPoliciesLoading,
    error: policiesError,
  } = useQuery({
    queryKey: queryKeys.aiResponsePolicy.list(),
    queryFn: () => listAiResponsePolicies({ limit: 50, offset: 0 }),
    enabled: isAdmin,
  });

  const {
    data: logsData,
    isLoading: isLogsLoading,
    error: logsError,
  } = useQuery({
    queryKey: queryKeys.aiResponsePolicy.logs(),
    queryFn: () => listPolicyEvaluationLogs({ limit: 50, offset: 0 }),
    enabled: isAdmin && activeTab === "logs",
  });

  // ---------------------------------------------------------------------------
  // Mutations
  // ---------------------------------------------------------------------------

  const createMutation = useMutation({
    mutationFn: createAiResponsePolicy,
    onSuccess: async () => {
      await invalidateAfterMutation(queryClient, "ai-response-policy.create");
      setPanel({ kind: "idle" });
      setFormError(null);
    },
    onError: (err) => setFormError(getApiErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      policyId,
      payload,
    }: {
      policyId: string;
      payload: Parameters<typeof updateAiResponsePolicy>[1];
    }) => updateAiResponsePolicy(policyId, payload),
    onSuccess: async () => {
      await invalidateAfterMutation(queryClient, "ai-response-policy.update");
      setPanel({ kind: "idle" });
      setFormError(null);
    },
    onError: (err) => setFormError(getApiErrorMessage(err)),
  });

  const activateMutation = useMutation({
    mutationFn: activateAiResponsePolicy,
    onSuccess: async () => {
      await invalidateAfterMutation(queryClient, "ai-response-policy.activate");
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: deactivateAiResponsePolicy,
    onSuccess: async () => {
      await invalidateAfterMutation(
        queryClient,
        "ai-response-policy.deactivate",
      );
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAiResponsePolicy,
    onSuccess: async () => {
      await invalidateAfterMutation(queryClient, "ai-response-policy.delete");
      setDeletingId(null);
    },
    onError: () => setDeletingId(null),
  });

  // ---------------------------------------------------------------------------
  // Guards
  // ---------------------------------------------------------------------------

  if (!isAdmin) return <ForbiddenState />;

  if (isPoliciesLoading) return <LoadingState />;

  if (policiesError) {
    if (isForbiddenError(policiesError)) return <ForbiddenState />;
    return <ErrorState message={getApiErrorMessage(policiesError)} />;
  }

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  function handleCreateSubmit(form: FormState) {
    setFormError(null);
    createMutation.mutate(formToRequest(form));
  }

  function handleEditSubmit(policyId: string, form: FormState) {
    setFormError(null);
    updateMutation.mutate({ policyId, payload: formToRequest(form) });
  }

  function handleToggleActive(policy: AiResponsePolicyResponse) {
    if (policy.is_active) {
      deactivateMutation.mutate(policy.policy_id);
    } else {
      activateMutation.mutate(policy.policy_id);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const policies = policiesData?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">
            AI Response Policy
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Control citation requirements, confidence thresholds, topic
            blocking, and mandatory disclaimers for AI-generated answers.
          </p>
        </div>
        <button
          onClick={() => {
            setPanel({ kind: "create" });
            setFormError(null);
          }}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          New Policy
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-4 border-b border-gray-200">
        {(["policies", "logs"] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`pb-2 text-sm font-medium capitalize ${
              activeTab === tab
                ? "border-b-2 border-indigo-600 text-indigo-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab === "policies"
              ? `Policies (${policies.length})`
              : "Decision Logs"}
          </button>
        ))}
      </div>

      {/* Inline panel */}
      {(panel.kind === "create" ||
        panel.kind === "edit" ||
        panel.kind === "preview") && (
        <div className="rounded border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-base font-semibold text-gray-900">
            {panel.kind === "create"
              ? "Create Policy"
              : panel.kind === "edit"
                ? `Edit: ${panel.policy.policy_name}`
                : `Test: ${panel.policy.policy_name}`}
          </h2>
          {panel.kind === "create" && (
            <PolicyForm
              initial={emptyForm()}
              onSubmit={handleCreateSubmit}
              onCancel={() => setPanel({ kind: "idle" })}
              isPending={createMutation.isPending}
              error={formError}
            />
          )}
          {panel.kind === "edit" && (
            <PolicyForm
              initial={policyToForm(panel.policy)}
              onSubmit={(form) => handleEditSubmit(panel.policy.policy_id, form)}
              onCancel={() => setPanel({ kind: "idle" })}
              isPending={updateMutation.isPending}
              error={formError}
            />
          )}
          {panel.kind === "preview" && (
            <PolicyPreviewPanel policy={panel.policy} />
          )}
          {panel.kind === "preview" && (
            <div className="mt-4 border-t pt-4">
              <button
                onClick={() => setPanel({ kind: "idle" })}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Close
              </button>
            </div>
          )}
        </div>
      )}

      {/* Policies tab */}
      {activeTab === "policies" && (
        <div>
          {policies.length === 0 ? (
            <EmptyState
              title="No policies yet"
              description="Create an AI response policy to control how answers are generated and delivered."
            />
          ) : (
            <div className="overflow-x-auto rounded border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      Name
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      Citation Mode
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      Min. Confidence
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      Blocked Topics
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {policies.map((policy) => (
                    <tr key={policy.policy_id}>
                      <td className="px-4 py-3 font-medium text-gray-900">
                        {policy.policy_name}
                        {policy.description && (
                          <p className="text-xs font-normal text-gray-500">
                            {policy.description}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <PolicyStatusBadge isActive={policy.is_active} />
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {CITATION_MODE_LABELS[policy.citation_mode]}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {policy.min_confidence_threshold !== null
                          ? `≥ ${policy.min_confidence_threshold}`
                          : "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {policy.blocked_topics.length > 0
                          ? policy.blocked_topics.slice(0, 3).join(", ") +
                            (policy.blocked_topics.length > 3
                              ? ` +${policy.blocked_topics.length - 3}`
                              : "")
                          : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() =>
                              setPanel({ kind: "preview", policy })
                            }
                            className="text-xs text-indigo-600 hover:underline"
                          >
                            Test
                          </button>
                          <button
                            onClick={() => {
                              setPanel({ kind: "edit", policy });
                              setFormError(null);
                            }}
                            className="text-xs text-gray-600 hover:underline"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleToggleActive(policy)}
                            disabled={
                              activateMutation.isPending ||
                              deactivateMutation.isPending
                            }
                            className={`text-xs font-medium ${
                              policy.is_active
                                ? "text-yellow-700 hover:underline"
                                : "text-green-700 hover:underline"
                            } disabled:opacity-50`}
                          >
                            {policy.is_active ? "Deactivate" : "Activate"}
                          </button>
                          {!policy.is_active && (
                            <>
                              {deletingId === policy.policy_id ? (
                                <span className="text-xs text-red-700">
                                  Deleting…
                                </span>
                              ) : (
                                <button
                                  onClick={() => {
                                    setDeletingId(policy.policy_id);
                                    deleteMutation.mutate(policy.policy_id);
                                  }}
                                  className="text-xs text-red-600 hover:underline"
                                >
                                  Delete
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Logs tab */}
      {activeTab === "logs" && (
        <div>
          {isLogsLoading && <LoadingState />}
          {logsError && (
            <ErrorState message={getApiErrorMessage(logsError)} />
          )}
          {!isLogsLoading && !logsError && (
            <>
              {(logsData?.items ?? []).length === 0 ? (
                <EmptyState
                  title="No policy decisions logged"
                  description="Policy decision records appear here after a policy is activated and chat requests are evaluated against it."
                />
              ) : (
                <div className="overflow-x-auto rounded border border-gray-200">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">
                          Time
                        </th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">
                          Outcome
                        </th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">
                          Question Preview
                        </th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">
                          Confidence
                        </th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">
                          Citations
                        </th>
                        <th className="px-4 py-3 text-left font-medium text-gray-600">
                          Rules
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 bg-white">
                      {logsData!.items.map((log) => (
                        <tr key={log.log_id}>
                          <td className="whitespace-nowrap px-4 py-3 text-gray-500">
                            {new Date(log.created_at).toLocaleString()}
                          </td>
                          <td className="px-4 py-3">
                            <OutcomeChip outcome={log.outcome} />
                          </td>
                          <td className="max-w-xs truncate px-4 py-3 text-gray-700">
                            {log.question_preview ?? "—"}
                          </td>
                          <td className="px-4 py-3 text-gray-600">
                            {log.confidence_score !== null
                              ? log.confidence_score.toFixed(2)
                              : "—"}
                          </td>
                          <td className="px-4 py-3 text-gray-600">
                            {log.citation_count ?? "—"}
                          </td>
                          <td className="px-4 py-3 text-gray-600">
                            {log.violated_rules.length > 0
                              ? log.violated_rules.join(", ")
                              : log.warning_flags.length > 0
                                ? log.warning_flags.join(", ")
                                : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
