import type { GovernanceMcpStatus } from "@/lib/api/admin-governance";
import { EmptyState } from "@/components/states/EmptyState";

export function McpStatusSection({
  status,
}: {
  status: GovernanceMcpStatus | undefined;
}) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">MCP endpoint</h2>
      {status ? (
        <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 text-sm">
          <dt className="font-medium text-[#6a6780]">MCP feature flag</dt>
          <dd className="font-semibold text-[#2a2640]">
            {status.feature_enable_mcp ? "Enabled" : "Disabled"}
          </dd>
          <dt className="font-medium text-[#6a6780]">Transport</dt>
          <dd className="font-semibold text-[#2a2640]">
            {status.mcp_transport}
          </dd>
          <dt className="font-medium text-[#6a6780]">Endpoint</dt>
          <dd className="font-semibold text-[#2a2640]">
            {status.mcp_http_host}:{status.mcp_http_port}
            {status.mcp_http_path}
          </dd>
          <dt className="font-medium text-[#6a6780]">Auth required</dt>
          <dd className="font-semibold text-[#2a2640]">
            {status.mcp_auth_required ? "Yes" : "No"}
          </dd>
          <dt className="font-medium text-[#6a6780]">Rate limit</dt>
          <dd className="font-semibold text-[#2a2640]">
            {status.mcp_rate_limit_enabled ? "Enabled" : "Disabled"}
          </dd>
          <dt className="font-medium text-[#6a6780]">External connectors</dt>
          <dd className="font-semibold text-[#2a2640]">
            {status.feature_enable_external_mcp_connectors
              ? `Enabled (${status.configured_global_external_servers} global)`
              : "Disabled"}
          </dd>
        </dl>
      ) : (
        <EmptyState
          title="MCP status unavailable"
          description="No MCP status payload was returned by the backend."
          compact
        />
      )}
    </article>
  );
}
