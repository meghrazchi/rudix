"use client";

import { useQuery } from "@tanstack/react-query";

import { getChatToolsAvailability } from "@/lib/api/admin-chat-tools";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

function StatusBadge({ available }: { available: boolean }) {
  if (available) {
    return (
      <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
        Available
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-700">
      Unavailable
    </span>
  );
}

export function AdminChatToolsPage() {
  const { state } = useAuthSession();
  const session = state.status === "authenticated" ? state.session : null;
  const role = session?.role ?? null;
  const canView = canViewAdminUsage(role);

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.admin.chatToolsAvailability,
    queryFn: getChatToolsAvailability,
    enabled: canView,
    staleTime: 30_000,
  });

  if (!canView) {
    return <ForbiddenState />;
  }

  if (isLoading) {
    return <LoadingState />;
  }

  if (error) {
    if (isForbiddenError(error)) return <ForbiddenState />;
    return <ErrorState description="Failed to load chat tool availability." />;
  }

  if (!data) {
    return <EmptyState description="No tool availability data." />;
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">
            Chat Tool Availability
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Permission-aware tools the chat pipeline can use. Disable tools per
            organisation via{" "}
            <span className="font-mono text-xs">
              PUT /admin/agent-policy/tools/&#123;name&#125;
            </span>
            .
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 rounded border border-gray-200 bg-gray-50 px-3 py-1.5">
          <span className="text-xs text-gray-500">Orchestration</span>
          {data.feature_enabled ? (
            <span className="inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-bold text-emerald-800">
              ON
            </span>
          ) : (
            <span className="inline-flex rounded-full bg-gray-200 px-2 py-0.5 text-[11px] font-bold text-gray-600">
              OFF
            </span>
          )}
        </div>
      </div>

      {!data.feature_enabled ? (
        <div className="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Adaptive tool orchestration is disabled (
          <code className="text-[11px]">
            FEATURE_ENABLE_CHAT_TOOL_ORCHESTRATION=false
          </code>
          ). Enable it to activate permission-aware tool selection in the chat
          pipeline.
        </div>
      ) : null}

      <div className="overflow-x-auto rounded border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr className="text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              <th className="px-4 py-3 pr-4">Tool</th>
              <th className="px-4 py-3 pr-4">Required permission</th>
              <th className="px-4 py-3 pr-4">Required roles</th>
              <th className="px-4 py-3 pr-4">Feature flag</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 px-4">
            {data.tools.map((tool) => (
              <tr key={tool.name} className="hover:bg-gray-50">
                <td className="px-4 py-3 align-top">
                  <div className="font-mono text-xs text-gray-900">
                    {tool.name}
                  </div>
                  <div className="mt-0.5 text-[11px] text-gray-500">
                    {tool.purpose}
                  </div>
                </td>
                <td className="px-4 py-3 align-top">
                  <code className="rounded bg-gray-50 px-1 py-0.5 text-[11px] text-gray-700">
                    {tool.required_permission}
                  </code>
                </td>
                <td className="px-4 py-3 align-top">
                  <div className="flex flex-wrap gap-1">
                    {tool.required_roles.map((r) => (
                      <span
                        key={r}
                        className="inline-flex rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600"
                      >
                        {r}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 align-top text-[11px] text-gray-600">
                  {tool.feature_flag ?? (
                    <span className="text-gray-400 italic">none</span>
                  )}
                </td>
                <td className="px-4 py-3 align-top">
                  <div className="flex flex-col items-start gap-1">
                    <StatusBadge available={tool.available} />
                    {!tool.feature_available ? (
                      <span className="text-[10px] text-rose-600">
                        Feature disabled
                      </span>
                    ) : !tool.org_policy_enabled ? (
                      <span className="text-[10px] text-rose-600">
                        Disabled by policy
                      </span>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
