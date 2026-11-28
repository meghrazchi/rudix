"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  activateAiResponsePolicy,
  createAiResponsePolicy,
  deactivateAiResponsePolicy,
  deleteAiResponsePolicy,
  listAiResponsePolicies,
  listPolicyEvaluationLogs,
  updateAiResponsePolicy,
  type AiResponsePolicyResponse,
} from "@/lib/api/ai-response-policy";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  CITATION_MODE_LABELS,
  emptyForm,
  policyToForm,
  formToRequest,
  OutcomeChip,
  PolicyStatusBadge,
  type Tab,
  type FormState,
  type PanelState,
} from "@/components/admin/ai-response-policy/policyShared";
import { PolicyForm } from "@/components/admin/ai-response-policy/PolicyForm";
import { PolicyPreviewPanel } from "@/components/admin/ai-response-policy/PolicyPreviewPanel";

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
    return <ErrorState error={policiesError} />;
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
              onSubmit={(form) =>
                handleEditSubmit(panel.policy.policy_id, form)
              }
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
          {logsError && <ErrorState error={logsError} />}
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
                          <td className="px-4 py-3 whitespace-nowrap text-gray-500">
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
