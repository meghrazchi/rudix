import type {
  GovernancePolicyResponse,
  GovernancePolicyState,
} from "@/lib/api/admin-governance";

export function ToolAllowlistSection({
  policy,
  tools,
  onAllowedToolsChange,
}: {
  policy: GovernancePolicyState;
  tools: GovernancePolicyResponse["tool_catalog"];
  onAllowedToolsChange: (next: string[]) => void;
}) {
  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">Tool allowlist</h2>
      <p className="mt-1 text-sm text-[#68647b]">
        Only selected tools are available to the organization agent runtime.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {tools.map((tool) => {
          const selected = policy.allowed_tool_names.includes(tool.name);
          const isSideEffect = tool.effect_policy === "side_effect";
          return (
            <label
              key={tool.name}
              className="flex items-start gap-2 rounded-lg border border-[#e1dff0] p-3"
            >
              <input
                type="checkbox"
                checked={selected}
                onChange={(event) => {
                  const next = event.target.checked
                    ? [...policy.allowed_tool_names, tool.name]
                    : policy.allowed_tool_names.filter(
                        (name) => name !== tool.name,
                      );
                  onAllowedToolsChange([...new Set(next)]);
                }}
              />
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-[#2a2640]">
                  {tool.name}
                </span>
                <span className="block text-xs text-[#6a6780]">
                  {tool.capability}
                </span>
                <span
                  className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                    isSideEffect
                      ? "bg-rose-100 text-rose-800"
                      : "bg-emerald-100 text-emerald-800"
                  }`}
                >
                  {tool.effect_policy}
                </span>
              </span>
            </label>
          );
        })}
      </div>
    </section>
  );
}
