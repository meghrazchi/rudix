"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getMCPPolicy, getMCPStatus, listMCPTools } from "@/lib/api/mcp";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { queryKeys } from "@/lib/api/query";
import { usePermissions } from "@/lib/use-permissions";
import { MCPStatusCard } from "@/components/admin/mcp/mcpShared";
import { PolicyForm } from "@/components/admin/mcp/PolicyForm";
import {
  MCPToolsCard,
  AuditEventsPanel,
  SetupInstructions,
} from "@/components/admin/mcp/McpPanels";

export function AdminMCPPage() {
  const { hasPermission } = usePermissions();
  const canManage = hasPermission("mcp:manage");
  const [saved, setSaved] = useState(false);

  const policyQuery = useQuery({
    queryKey: queryKeys.admin.mcpPolicy,
    queryFn: getMCPPolicy,
    enabled: canManage,
  });

  const statusQuery = useQuery({
    queryKey: queryKeys.admin.mcpStatus,
    queryFn: getMCPStatus,
    enabled: canManage,
  });

  const toolsQuery = useQuery({
    queryKey: queryKeys.admin.mcpTools,
    queryFn: listMCPTools,
    enabled: canManage,
  });

  if (!canManage) {
    return (
      <ForbiddenState
        title="MCP Management"
        description="You need the mcp:manage permission to access this page."
        backHref="/dashboard"
      />
    );
  }

  if (policyQuery.isLoading || statusQuery.isLoading) return <LoadingState />;

  if (policyQuery.isError) {
    if (isForbiddenError(policyQuery.error)) {
      return (
        <ForbiddenState
          title="MCP Management"
          description="You do not have access to MCP configuration."
          requestId={extractRequestIdFromError(policyQuery.error)}
          backHref="/dashboard"
        />
      );
    }
    return <ErrorState description={getApiErrorMessage(policyQuery.error)} />;
  }

  const policy = policyQuery.data!;
  const mcpStatus = statusQuery.data;
  const tools = toolsQuery.data?.items ?? [];

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <div>
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          Admin
        </p>
        <h1 className="text-2xl font-extrabold text-[#2a2640]">MCP server</h1>
        <p className="mt-1 text-sm text-[#68647b]">
          Configure MCP access, capabilities, rate limits, and monitor active
          clients. MCP exposes read-only knowledge-base tools to authenticated
          clients — raw document text is never leaked unless explicitly
          permitted.
        </p>
      </div>

      {saved && (
        <div className="rounded-lg bg-[#e8f5e9] px-4 py-3 text-sm text-[#2e7d32]">
          Policy saved.{" "}
          <button
            type="button"
            onClick={() => setSaved(false)}
            className="ml-2 font-medium underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {mcpStatus && <MCPStatusCard status={mcpStatus} />}

      <PolicyForm policy={policy} onSaved={() => setSaved(true)} />

      <MCPToolsCard tools={tools} />

      {mcpStatus && <SetupInstructions status={mcpStatus} />}

      <AuditEventsPanel />
    </div>
  );
}
