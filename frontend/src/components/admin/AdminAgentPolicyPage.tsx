"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteToolPolicy,
  getAgentPolicy,
  type OrgToolPolicyOverride,
  type ToolPolicyUpsertRequest,
  upsertToolPolicy,
} from "@/lib/api/admin-agent-policy";
import { ToolPolicyTable } from "@/components/admin/agent-policy/ToolPolicyTable";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

export function AdminAgentPolicyPage() {
  const { session } = useAuthSession();
  const role = session?.role ?? null;
  const canView = canViewAdminUsage(role);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.admin.agentPolicy,
    queryFn: getAgentPolicy,
    enabled: canView,
    staleTime: 30_000,
  });

  const upsertMutation = useMutation({
    mutationFn: ({
      toolName,
      payload,
    }: {
      toolName: string;
      payload: ToolPolicyUpsertRequest;
    }) => upsertToolPolicy(toolName, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.agentPolicy });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (toolName: string) => deleteToolPolicy(toolName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.agentPolicy });
    },
  });

  if (!canView) {
    return <ForbiddenState />;
  }

  if (isLoading) {
    return <LoadingState />;
  }

  if (error) {
    if (isForbiddenError(error)) {
      return <ForbiddenState />;
    }
    return <ErrorState description={getApiErrorMessage(error)} />;
  }

  if (!data) {
    return <EmptyState description="No agent policy data available." />;
  }

  const overrideByName: Record<string, OrgToolPolicyOverride> = Object.fromEntries(
    data.tool_overrides.map((o) => [o.tool_name, o]),
  );

  const isMutating = upsertMutation.isPending || deleteMutation.isPending;

  const mutationError =
    upsertMutation.error ?? deleteMutation.error ?? null;

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-2xl font-bold text-[#2a2640]">Agent tool policy &amp; budgets</h1>
        <p className="mt-1 text-sm text-[#6a6780]">
          Control which tools agents can use, set per-tool role and approval requirements, and
          define budget limits. Org-level budget limits are managed in{" "}
          <a href="/admin/governance" className="text-[#6c63e0] underline">
            Governance settings
          </a>
          .
        </p>
      </div>

      {mutationError && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {getApiErrorMessage(mutationError)}
        </div>
      )}

      <OrgBudgetSummarySection
        maxSteps={data.org_budget.max_steps}
        maxToolCalls={data.org_budget.max_tool_calls_per_run}
        maxTotalCost={data.org_budget.max_total_cost_usd}
        maxTotalTokens={data.org_budget.max_total_tokens}
      />

      <ToolPolicyTable
        resolvedTools={data.resolved_tools}
        overrideByName={overrideByName}
        onSave={(toolName, draft) => {
          const payload: ToolPolicyUpsertRequest = {
            enabled: draft.enabled ?? true,
            approval_required: draft.approval_required ?? null,
            required_roles: draft.required_roles ?? null,
            max_calls_per_run: draft.max_calls_per_run ?? null,
            max_input_bytes: draft.max_input_bytes ?? null,
            max_output_bytes: draft.max_output_bytes ?? null,
            timeout_ms: draft.timeout_ms ?? null,
            max_retry_attempts: draft.max_retry_attempts ?? null,
          };
          upsertMutation.mutate({ toolName, payload });
        }}
        onDelete={(toolName) => deleteMutation.mutate(toolName)}
        isSaving={isMutating}
      />

      {data.policy_updated_at && (
        <p className="text-right text-xs text-[#b0a8c8]">
          Last updated {new Date(data.policy_updated_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}

function OrgBudgetSummarySection({
  maxSteps,
  maxToolCalls,
  maxTotalCost,
  maxTotalTokens,
}: {
  maxSteps?: number | null;
  maxToolCalls?: number | null;
  maxTotalCost?: number | null;
  maxTotalTokens?: number | null;
}) {
  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">Org-level budget limits</h2>
      <p className="mt-1 text-sm text-[#6a6780]">
        Active limits inherited from governance settings. Edit them in{" "}
        <a href="/admin/governance" className="text-[#6c63e0] underline">
          Governance
        </a>
        .
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <BudgetCard label="Max steps" value={maxSteps} />
        <BudgetCard label="Max tool calls / run" value={maxToolCalls} />
        <BudgetCard label="Max total tokens" value={maxTotalTokens} />
        <BudgetCard label="Max cost (USD)" value={maxTotalCost} />
      </div>
    </section>
  );
}

function BudgetCard({
  label,
  value,
}: {
  label: string;
  value: number | null | undefined;
}) {
  return (
    <div className="rounded-xl border border-[#ece9f5] p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">{label}</p>
      <p className="mt-1 text-xl font-bold text-[#2a2640]">
        {value != null ? value : <span className="text-sm font-normal text-[#b0a8c8]">unlimited</span>}
      </p>
    </div>
  );
}
