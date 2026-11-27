"use client";

import { useQuery } from "@tanstack/react-query";
import {
  listMCPAuditEvents,
  type MCPAuditEvent,
  type MCPStatusResponse,
  type MCPToolInfo,
} from "@/lib/api/mcp";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";

export function MCPToolsCard({ tools }: { tools: MCPToolInfo[] }) {
  const active = tools.filter((t) => !t.deprecated_alias);
  const deprecated = tools.filter((t) => t.deprecated_alias);

  return (
    <section className="rounded-xl border border-[#d7d4e8] bg-white p-5">
      <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
        Available tools
        <span className="ml-2 text-sm font-normal text-[#68647b]">
          ({active.length} active
          {deprecated.length > 0 ? `, ${deprecated.length} legacy` : ""})
        </span>
      </h2>
      {tools.length === 0 ? (
        <p className="text-sm text-[#68647b]">
          MCP is disabled or no tools are registered.
        </p>
      ) : (
        <div className="space-y-2">
          {active.map((tool) => (
            <div
              key={tool.public_name}
              className="rounded-lg border border-[#e8e6f0] p-3"
            >
              <div className="flex items-center gap-2">
                <code className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs font-medium text-[#3525cd]">
                  {tool.public_name}
                </code>
                <span className="rounded-full bg-[#f9f8ff] px-2 py-0.5 text-xs text-[#68647b]">
                  requires: {tool.capability}
                </span>
              </div>
              <p className="mt-1 text-xs text-[#68647b]">{tool.description}</p>
            </div>
          ))}
          {deprecated.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-[#68647b]">
                Show {deprecated.length} legacy aliases
              </summary>
              <div className="mt-2 space-y-2">
                {deprecated.map((tool) => (
                  <div
                    key={tool.public_name}
                    className="rounded-lg border border-[#e8e6f0] bg-[#fafafa] p-3 opacity-70"
                  >
                    <div className="flex items-center gap-2">
                      <code className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#68647b]">
                        {tool.public_name}
                      </code>
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                        deprecated alias
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

export function AuditEventRow({ event }: { event: MCPAuditEvent }) {
  return (
    <div className="rounded-xl border border-[#e8e6f0] bg-[#fafafa] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#4d4880]">
          {event.action}
        </code>
        {event.resource_type && (
          <span className="text-xs text-[#68647b]">{event.resource_type}</span>
        )}
        <span className="ml-auto text-xs text-[#68647b]">
          {new Date(event.created_at).toLocaleString()}
        </span>
      </div>
      {Object.keys(event.metadata).length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-[#68647b]">
            Metadata
          </summary>
          <pre className="mt-1 overflow-x-auto rounded bg-[#f0eeff] p-2 text-xs text-[#2a2640]">
            {JSON.stringify(event.metadata, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

export function AuditEventsPanel() {
  const eventsQuery = useQuery({
    queryKey: queryKeys.admin.mcpAuditEvents(),
    queryFn: () => listMCPAuditEvents({ limit: 50 }),
  });

  const events = eventsQuery.data?.items ?? [];

  return (
    <section className="rounded-xl border border-[#d7d4e8] bg-white p-5">
      <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
        Recent MCP audit events
      </h2>
      {eventsQuery.isLoading && (
        <p className="text-sm text-[#68647b]">Loading…</p>
      )}
      {eventsQuery.isError && (
        <p className="text-sm text-red-600">
          {getApiErrorMessage(eventsQuery.error)}
        </p>
      )}
      {!eventsQuery.isLoading && events.length === 0 && (
        <p className="text-sm text-[#68647b]">No MCP events recorded yet.</p>
      )}
      <div className="space-y-2">
        {events.map((event) => (
          <AuditEventRow key={event.id} event={event} />
        ))}
      </div>
    </section>
  );
}

export function SetupInstructions({ status }: { status: MCPStatusResponse }) {
  const endpoint = `http://<host>:${status.http_port}${status.http_path}`;
  return (
    <section className="rounded-xl border border-[#d7d4e8] bg-white p-5">
      <h2 className="mb-3 text-base font-semibold text-[#2a2640]">
        Setup instructions
      </h2>
      <p className="mb-3 text-sm text-[#68647b]">
        Connect an MCP client (e.g. Claude Desktop, Cursor, or any MCP SDK
        client) using the streamable HTTP transport:
      </p>
      <pre className="mb-3 overflow-x-auto rounded-lg bg-[#f5f3ff] p-4 text-xs text-[#2a2640]">
        {JSON.stringify(
          {
            mcpServers: {
              rudix: {
                url: endpoint,
                headers: {
                  Authorization: "Bearer <your-rudix-api-key>",
                },
              },
            },
          },
          null,
          2,
        )}
      </pre>
      <ul className="list-inside list-disc space-y-1 text-sm text-[#68647b]">
        <li>
          Create a Rudix API key at{" "}
          <span className="font-medium text-[#2a2640]">Admin → API keys</span>.
        </li>
        <li>
          The MCP server must be running as a separate process (
          <code className="text-xs">python -m app.mcp.main</code>).
        </li>
        <li>
          Raw document text is never exposed unless the org policy explicitly
          allows it.
        </li>
      </ul>
    </section>
  );
}
