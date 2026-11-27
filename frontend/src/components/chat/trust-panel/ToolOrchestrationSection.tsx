import {
  SectionHeader,
  StatRow,
} from "@/components/chat/trust-panel/TrustPrimitives";
import type {
  ChatToolCallRecord,
  ToolOrchestrationRecord,
} from "@/lib/api/trust_metadata";

const DENIAL_REASON_LABEL: Record<string, string> = {
  org_policy_disabled: "Disabled by policy",
  feature_unavailable: "Feature unavailable",
  insufficient_role: "Insufficient role",
  insufficient_permission: "Insufficient permission",
  source_scope_mismatch: "Scope mismatch",
};

export function ToolOrchestrationSection({
  toolOrchestration,
}: {
  toolOrchestration: ToolOrchestrationRecord | null;
}) {
  if (toolOrchestration === null || !toolOrchestration.enabled) {
    return null;
  }

  const deniedCalls = toolOrchestration.tool_calls.filter((t) => !t.authorized);

  return (
    <div className="space-y-2">
      <SectionHeader icon="build" label="Tool Orchestration" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
        <StatRow label="Tools evaluated" value={toolOrchestration.tool_count} />
        <StatRow
          label="Authorized"
          value={toolOrchestration.authorized_count}
        />
        {toolOrchestration.denied_count > 0 ? (
          <StatRow
            label="Denied"
            value={
              <span className="font-semibold text-[#d97706]">
                {toolOrchestration.denied_count}
              </span>
            }
          />
        ) : null}
      </div>
      {deniedCalls.length > 0 ? (
        <div className="mt-1 space-y-1">
          {deniedCalls.map((call: ChatToolCallRecord) => (
            <div
              key={call.tool_name}
              className="flex items-start gap-1.5 rounded border border-amber-100 bg-amber-50 px-2 py-1 text-[11px] text-amber-900"
            >
              <span className="font-medium">{call.tool_name}</span>
              <span className="text-amber-600">—</span>
              <span>
                {DENIAL_REASON_LABEL[call.denial_reason ?? ""] ??
                  call.denial_reason ??
                  "Denied"}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
