import type { GovernancePolicyState } from "@/lib/api/admin-governance";

export function PolicyTogglesSection({
  policy,
  selectedSideEffectTools,
  sideEffectAck,
  onTogglePolicyBoolean,
  onSideEffectAckChange,
}: {
  policy: GovernancePolicyState;
  selectedSideEffectTools: string[];
  sideEffectAck: boolean;
  onTogglePolicyBoolean: (
    key:
      | "agentic_mode_enabled"
      | "mcp_exposure_enabled"
      | "allow_side_effect_tools",
    value: boolean,
  ) => void;
  onSideEffectAckChange: (checked: boolean) => void;
}) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">Policy toggles</h2>
      <div className="mt-3 space-y-3">
        <label className="flex items-center justify-between rounded-lg border border-[#e1dff0] p-3">
          <span className="text-sm font-medium text-[#3d3953]">
            Enable agentic mode
          </span>
          <input
            type="checkbox"
            checked={policy.agentic_mode_enabled}
            onChange={(event) =>
              onTogglePolicyBoolean(
                "agentic_mode_enabled",
                event.target.checked,
              )
            }
          />
        </label>
        <label className="flex items-center justify-between rounded-lg border border-[#e1dff0] p-3">
          <span className="text-sm font-medium text-[#3d3953]">
            Allow MCP exposure for this organization
          </span>
          <input
            type="checkbox"
            checked={policy.mcp_exposure_enabled}
            onChange={(event) =>
              onTogglePolicyBoolean(
                "mcp_exposure_enabled",
                event.target.checked,
              )
            }
          />
        </label>
        <label className="flex items-center justify-between rounded-lg border border-[#e1dff0] p-3">
          <span className="text-sm font-medium text-[#3d3953]">
            Allow side-effect tools
          </span>
          <input
            type="checkbox"
            checked={policy.allow_side_effect_tools}
            onChange={(event) =>
              onTogglePolicyBoolean(
                "allow_side_effect_tools",
                event.target.checked,
              )
            }
          />
        </label>
        {selectedSideEffectTools.length > 0 ? (
          <label className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <input
              type="checkbox"
              checked={sideEffectAck}
              onChange={(event) => onSideEffectAckChange(event.target.checked)}
            />
            <span>
              I acknowledge side-effect tools can modify data and should be
              protected by approvals.
            </span>
          </label>
        ) : null}
      </div>
    </article>
  );
}
