import type { GovernancePolicyState } from "@/lib/api/admin-governance";

import { parseDecimal, parseInteger } from "./utils";

export function BudgetSection({
  policy,
  onPolicyChange,
}: {
  policy: GovernancePolicyState;
  onPolicyChange: (next: GovernancePolicyState) => void;
}) {
  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">Budgets</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <BudgetInput
          label="Max steps"
          value={String(policy.budgets.max_steps)}
          onChange={(value) =>
            onPolicyChange({
              ...policy,
              budgets: {
                ...policy.budgets,
                max_steps: parseInteger(value) ?? policy.budgets.max_steps,
              },
            })
          }
        />
        <BudgetInput
          label="Max tool calls / run"
          value={String(policy.budgets.max_tool_calls_per_run)}
          onChange={(value) =>
            onPolicyChange({
              ...policy,
              budgets: {
                ...policy.budgets,
                max_tool_calls_per_run:
                  parseInteger(value) ?? policy.budgets.max_tool_calls_per_run,
              },
            })
          }
        />
        <BudgetInput
          label="Max tool timeout (ms)"
          value={String(policy.budgets.max_tool_timeout_ms)}
          onChange={(value) =>
            onPolicyChange({
              ...policy,
              budgets: {
                ...policy.budgets,
                max_tool_timeout_ms:
                  parseInteger(value) ?? policy.budgets.max_tool_timeout_ms,
              },
            })
          }
        />
        <BudgetInput
          label="Max input bytes"
          value={String(policy.budgets.max_tool_input_bytes)}
          onChange={(value) =>
            onPolicyChange({
              ...policy,
              budgets: {
                ...policy.budgets,
                max_tool_input_bytes:
                  parseInteger(value) ?? policy.budgets.max_tool_input_bytes,
              },
            })
          }
        />
        <BudgetInput
          label="Max output bytes"
          value={String(policy.budgets.max_tool_output_bytes)}
          onChange={(value) =>
            onPolicyChange({
              ...policy,
              budgets: {
                ...policy.budgets,
                max_tool_output_bytes:
                  parseInteger(value) ?? policy.budgets.max_tool_output_bytes,
              },
            })
          }
        />
        <BudgetInput
          label="Max retry attempts"
          value={String(policy.budgets.max_tool_retry_attempts)}
          onChange={(value) =>
            onPolicyChange({
              ...policy,
              budgets: {
                ...policy.budgets,
                max_tool_retry_attempts:
                  parseInteger(value) ?? policy.budgets.max_tool_retry_attempts,
              },
            })
          }
        />
        <BudgetInput
          label="Max total tokens (optional)"
          value={String(policy.budgets.max_total_tokens ?? "")}
          onChange={(value) =>
            onPolicyChange({
              ...policy,
              budgets: {
                ...policy.budgets,
                max_total_tokens: parseInteger(value),
              },
            })
          }
        />
        <BudgetInput
          label="Max total cost USD (optional)"
          value={String(policy.budgets.max_total_cost_usd ?? "")}
          onChange={(value) =>
            onPolicyChange({
              ...policy,
              budgets: {
                ...policy.budgets,
                max_total_cost_usd: parseDecimal(value),
              },
            })
          }
        />
      </div>
    </section>
  );
}

function BudgetInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
      />
    </label>
  );
}
