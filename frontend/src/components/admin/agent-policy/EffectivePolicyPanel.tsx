"use client";

import { useQuery } from "@tanstack/react-query";

import {
  getEffectivePolicyForRun,
  type EffectivePolicyResponse,
} from "@/lib/api/admin-agent-policy";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";

export function EffectivePolicyPanel({ runId }: { runId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.admin.agentPolicyEffective(runId),
    queryFn: () => getEffectivePolicyForRun(runId),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="rounded-xl border border-[#d7d4e8] bg-white p-4 text-sm text-[#6a6780]">
        Loading policy…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        {error ? getApiErrorMessage(error) : "Policy not available"}
      </div>
    );
  }

  return <EffectivePolicyView data={data} />;
}

function EffectivePolicyView({ data }: { data: EffectivePolicyResponse }) {
  const budget = data.org_budget;

  return (
    <section className="rounded-xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <h3 className="text-sm font-bold text-[#2a2640]">Effective policy at run time</h3>
      {data.snapshot_recorded_at && (
        <p className="mt-0.5 text-xs text-[#6a6780]">
          Captured at {new Date(data.snapshot_recorded_at).toLocaleString()}
        </p>
      )}

      {budget && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
            Org budget limits
          </p>
          <div className="mt-1.5 grid gap-1.5 text-xs sm:grid-cols-2 xl:grid-cols-4">
            <BudgetRow label="Max steps" value={budget.max_steps} />
            <BudgetRow label="Max tool calls" value={budget.max_tool_calls_per_run} />
            <BudgetRow label="Max total tokens" value={budget.max_total_tokens} />
            <BudgetRow label="Max cost (USD)" value={budget.max_total_cost_usd} />
          </div>
        </div>
      )}

      {data.resolved_tools.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
            Tool policies
          </p>
          <div className="mt-1.5 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#e9e6f5] text-[10px] uppercase tracking-wide text-[#6a6780]">
                  <th className="py-1.5 text-left">Tool</th>
                  <th className="py-1.5 text-left">Enabled</th>
                  <th className="py-1.5 text-left">Approval</th>
                  <th className="py-1.5 text-left">Roles</th>
                  <th className="py-1.5 text-left">Max calls</th>
                </tr>
              </thead>
              <tbody>
                {data.resolved_tools.map((tool) => (
                  <tr key={tool.tool_name} className="border-b border-[#f0edf8] last:border-0">
                    <td className="py-1.5 pr-3 font-mono text-[#2a2640]">{tool.tool_name}</td>
                    <td className="py-1.5 pr-3">
                      <span
                        className={`inline-block h-2 w-2 rounded-full ${
                          tool.enabled ? "bg-emerald-500" : "bg-rose-400"
                        }`}
                      />
                    </td>
                    <td className="py-1.5 pr-3 text-[#6a6780]">
                      {tool.approval_required ? "Yes" : "No"}
                    </td>
                    <td className="py-1.5 pr-3 text-[#6a6780]">
                      {tool.required_roles.join(", ")}
                    </td>
                    <td className="py-1.5 text-[#6a6780]">{tool.max_calls_per_run}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

function BudgetRow({
  label,
  value,
}: {
  label: string;
  value: number | null | undefined;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-[#ece9f5] px-2.5 py-1.5">
      <span className="text-[#6a6780]">{label}</span>
      <span className="font-semibold text-[#2a2640]">
        {value != null ? value : <span className="text-[#b0a8c8]">unlimited</span>}
      </span>
    </div>
  );
}
