"use client";

import { useState } from "react";

import type {
  OrgToolPolicyOverride,
  ToolPolicyOverrideState,
} from "@/lib/api/admin-agent-policy";
import { ToolPolicyOverrideForm } from "./ToolPolicyOverrideForm";

function EffectBadge({ policy }: { policy: ToolEffectLabel }) {
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${
        policy === "read_only"
          ? "bg-emerald-100 text-emerald-700"
          : "bg-rose-100 text-rose-700"
      }`}
    >
      {policy === "read_only" ? "Read only" : "Side effect"}
    </span>
  );
}

type ToolEffectLabel = "read_only" | "side_effect";

export function ToolPolicyTable({
  resolvedTools,
  overrideByName,
  onSave,
  onDelete,
  isSaving,
}: {
  resolvedTools: ToolPolicyOverrideState[];
  overrideByName: Record<string, OrgToolPolicyOverride>;
  onSave: (toolName: string, draft: Partial<OrgToolPolicyOverride>) => void;
  onDelete: (toolName: string) => void;
  isSaving: boolean;
}) {
  const [editing, setEditing] = useState<string | null>(null);

  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">
        Per-tool policy overrides
      </h2>
      <p className="mt-1 text-sm text-[#6a6780]">
        Override default tool settings for this organization. Blank fields
        inherit the tool spec default.
      </p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#e9e6f5] text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              <th className="py-2 text-left">Tool</th>
              <th className="py-2 text-left">Enabled</th>
              <th className="py-2 text-left">Approval required</th>
              <th className="py-2 text-left">Roles</th>
              <th className="py-2 text-left">Max calls</th>
              <th className="py-2 text-left">Overridden</th>
              <th className="py-2" />
            </tr>
          </thead>
          <tbody>
            {resolvedTools.map((tool) => {
              const isEditing = editing === tool.tool_name;
              return (
                <tr
                  key={tool.tool_name}
                  className="border-b border-[#f0edf8] last:border-0"
                >
                  {isEditing ? (
                    <td colSpan={7} className="py-3">
                      <ToolPolicyOverrideForm
                        toolName={tool.tool_name}
                        existing={overrideByName[tool.tool_name] ?? null}
                        resolved={tool}
                        onSave={(draft) => {
                          onSave(tool.tool_name, draft);
                          setEditing(null);
                        }}
                        onDelete={() => {
                          onDelete(tool.tool_name);
                          setEditing(null);
                        }}
                        onCancel={() => setEditing(null)}
                        isSaving={isSaving}
                      />
                    </td>
                  ) : (
                    <>
                      <td className="py-2 pr-4 font-mono text-xs text-[#2a2640]">
                        {tool.tool_name}
                      </td>
                      <td className="py-2 pr-4">
                        <span
                          className={`inline-block h-2.5 w-2.5 rounded-full ${
                            tool.enabled ? "bg-emerald-500" : "bg-rose-400"
                          }`}
                        />
                      </td>
                      <td className="py-2 pr-4 text-[#6a6780]">
                        {tool.approval_required ? "Yes" : "No"}
                      </td>
                      <td className="py-2 pr-4 text-[#6a6780]">
                        {tool.required_roles.join(", ")}
                      </td>
                      <td className="py-2 pr-4 text-[#6a6780]">
                        {tool.max_calls_per_run}
                      </td>
                      <td className="py-2 pr-4">
                        {tool.is_overridden ? (
                          <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-semibold text-violet-700 uppercase">
                            Custom
                          </span>
                        ) : (
                          <span className="text-xs text-[#b0a8c8]">
                            Default
                          </span>
                        )}
                      </td>
                      <td className="py-2 text-right">
                        <button
                          onClick={() => setEditing(tool.tool_name)}
                          className="rounded px-2 py-1 text-xs font-medium text-[#6c63e0] hover:bg-[#f0edf8]"
                        >
                          Edit
                        </button>
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
