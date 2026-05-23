import type {
  ExternalMcpServerPolicy,
  GovernancePolicyState,
} from "@/lib/api/admin-governance";
import { EmptyState } from "@/components/states/EmptyState";

import {
  DEFAULT_NEW_SERVER,
  formatCommaList,
  parseCommaList,
  type NewServerFormState,
} from "./utils";

export function ExternalServersSection({
  policy,
  onPolicyChange,
  newServer,
  onNewServerChange,
}: {
  policy: GovernancePolicyState;
  onPolicyChange: (next: GovernancePolicyState) => void;
  newServer: NewServerFormState;
  onNewServerChange: (next: NewServerFormState) => void;
}) {
  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-bold text-[#2a2640]">
          External MCP servers
        </h2>
        <span className="text-sm font-semibold text-[#6a6780]">
          {policy.external_mcp_servers.length} configured
        </span>
      </div>
      {policy.external_mcp_servers.length > 0 ? (
        <div className="mt-3 grid gap-3">
          {policy.external_mcp_servers.map((server) => (
            <article
              key={server.server_id}
              className="rounded-lg border border-[#e1dff0] p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-[#2a2640]">
                    {server.server_id}
                  </p>
                  <p className="text-xs text-[#6a6780]">{server.base_url}</p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    onPolicyChange({
                      ...policy,
                      external_mcp_servers: policy.external_mcp_servers.filter(
                        (item) => item.server_id !== server.server_id,
                      ),
                    })
                  }
                  className="rounded-md border border-rose-200 px-2 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-50"
                >
                  Remove
                </button>
              </div>
              <p className="mt-2 text-xs text-[#6a6780]">
                auth={server.auth_type} secret_ref=
                {server.auth_secret_ref ?? "n/a"} allow_tools=
                {formatCommaList(server.allow_tools)}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No external MCP servers"
          description="Add an approved server configuration for this organization."
          compact
        />
      )}

      <div className="mt-4 rounded-lg border border-dashed border-[#d2cee6] p-3">
        <h3 className="text-sm font-bold text-[#3d3953]">
          Add external server
        </h3>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <input
            value={newServer.server_id}
            onChange={(event) =>
              onNewServerChange({
                ...newServer,
                server_id: event.target.value,
              })
            }
            placeholder="server_id"
            className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
          />
          <input
            value={newServer.base_url}
            onChange={(event) =>
              onNewServerChange({
                ...newServer,
                base_url: event.target.value,
              })
            }
            placeholder="https://server.example.com/mcp"
            className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
          />
          <select
            value={newServer.auth_type}
            onChange={(event) =>
              onNewServerChange({
                ...newServer,
                auth_type: event.target
                  .value as ExternalMcpServerPolicy["auth_type"],
              })
            }
            className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
          >
            <option value="none">auth: none</option>
            <option value="bearer">auth: bearer</option>
            <option value="header">auth: header</option>
          </select>
          <input
            value={newServer.auth_secret_ref}
            onChange={(event) =>
              onNewServerChange({
                ...newServer,
                auth_secret_ref: event.target.value,
              })
            }
            placeholder="secret ref"
            className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
          />
          <input
            value={newServer.auth_header_name}
            onChange={(event) =>
              onNewServerChange({
                ...newServer,
                auth_header_name: event.target.value,
              })
            }
            placeholder="auth header name (optional)"
            className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
          />
          <input
            value={newServer.allow_tools}
            onChange={(event) =>
              onNewServerChange({
                ...newServer,
                allow_tools: event.target.value,
              })
            }
            placeholder="allow tools (comma list)"
            className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-3 text-xs text-[#6a6780]">
          <label className="inline-flex items-center gap-1">
            <input
              type="checkbox"
              checked={newServer.enabled}
              onChange={(event) =>
                onNewServerChange({
                  ...newServer,
                  enabled: event.target.checked,
                })
              }
            />
            Enabled
          </label>
          <label className="inline-flex items-center gap-1">
            <input
              type="checkbox"
              checked={newServer.expose_on_mcp_surface}
              onChange={(event) =>
                onNewServerChange({
                  ...newServer,
                  expose_on_mcp_surface: event.target.checked,
                })
              }
            />
            Expose on MCP surface
          </label>
          <label className="inline-flex items-center gap-1">
            <input
              type="checkbox"
              checked={newServer.approval_required_for_side_effect}
              onChange={(event) =>
                onNewServerChange({
                  ...newServer,
                  approval_required_for_side_effect: event.target.checked,
                })
              }
            />
            Require approvals for side effects
          </label>
        </div>
        <button
          type="button"
          onClick={() => {
            if (!newServer.server_id.trim() || !newServer.base_url.trim()) {
              return;
            }
            const nextServer: ExternalMcpServerPolicy = {
              server_id: newServer.server_id.trim(),
              enabled: newServer.enabled,
              transport: "streamable_http",
              base_url: newServer.base_url.trim(),
              auth_type: newServer.auth_type,
              auth_header_name: newServer.auth_header_name.trim() || null,
              auth_secret_ref: newServer.auth_secret_ref.trim() || null,
              allow_tools: parseCommaList(newServer.allow_tools),
              read_only_tools: parseCommaList(newServer.read_only_tools),
              side_effect_tools: parseCommaList(newServer.side_effect_tools),
              required_roles: parseCommaList(newServer.required_roles),
              expose_on_mcp_surface: newServer.expose_on_mcp_surface,
              approval_required_for_side_effect:
                newServer.approval_required_for_side_effect,
            };
            onPolicyChange({
              ...policy,
              external_mcp_servers: [
                ...policy.external_mcp_servers.filter(
                  (item) => item.server_id !== nextServer.server_id,
                ),
                nextServer,
              ],
            });
            onNewServerChange(DEFAULT_NEW_SERVER);
          }}
          className="mt-3 rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
        >
          Add server
        </button>
      </div>
    </section>
  );
}
