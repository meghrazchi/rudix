"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  getMCPPolicy,
  getMCPStatus,
  listMCPAuditEvents,
  listMCPTools,
  updateMCPPolicy,
  type MCPAuditEvent,
  type MCPStatusResponse,
  type MCPToolInfo,
  type OrgMCPPolicy,
} from "@/lib/api/mcp";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { queryKeys } from "@/lib/api/query";
import { usePermissions } from "@/lib/use-permissions";

const MCP_DOC_CAPABILITIES = [
  "documents.read",
  "documents.chunks.read",
  "documents.summary.read",
  "documents.compare.read",
  "pipeline.read",
  "chat.answer",
];

function ToggleSwitch({
  checked,
  onChange,
  disabled,
  id,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  id: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3525cd] disabled:opacity-50 ${
        checked ? "bg-[#3525cd]" : "bg-[#d7d4e8]"
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        ok
          ? "bg-[#e8f5e9] text-[#2e7d32]"
          : "bg-red-100 text-red-700"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-[#2e7d32]" : "bg-red-600"}`}
      />
      {label}
    </span>
  );
}

function MCPStatusCard({ status }: { status: MCPStatusResponse }) {
  const allOk = status.failed_dependencies.length === 0;

  return (
    <section className="rounded-xl border border-[#d7d4e8] bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-semibold text-[#2a2640]">
          Server status
        </h2>
        <StatusBadge ok={allOk} label={allOk ? "Healthy" : "Degraded"} />
      </div>

      <div className="mb-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
        <div>
          <p className="text-xs text-[#68647b]">Feature flag</p>
          <StatusBadge
            ok={status.feature_enabled}
            label={status.feature_enabled ? "Enabled" : "Disabled"}
          />
        </div>
        <div>
          <p className="text-xs text-[#68647b]">Auth required</p>
          <StatusBadge
            ok={status.auth_required}
            label={status.auth_required ? "Bearer auth" : "No auth"}
          />
        </div>
        <div>
          <p className="text-xs text-[#68647b]">Transport</p>
          <code className="rounded bg-[#f5f3ff] px-1.5 py-0.5 text-xs text-[#4d4880]">
            {status.transport}
          </code>
        </div>
        <div>
          <p className="text-xs text-[#68647b]">Server name</p>
          <p className="font-medium text-[#2a2640]">{status.server_name}</p>
        </div>
        <div>
          <p className="text-xs text-[#68647b]">Endpoint</p>
          <code className="rounded bg-[#f5f3ff] px-1.5 py-0.5 text-xs text-[#4d4880]">
            :{status.http_port}
            {status.http_path}
          </code>
        </div>
        <div>
          <p className="text-xs text-[#68647b]">Rate limit</p>
          <p className="text-[#2a2640]">
            {status.rate_limit_enabled
              ? `${status.rate_limit_requests} req / ${status.rate_limit_window_seconds}s`
              : "Disabled"}
          </p>
        </div>
      </div>

      {!status.feature_enabled && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          MCP is disabled at the server level via the{" "}
          <code className="font-mono text-xs">FEATURE_ENABLE_MCP</code>{" "}
          environment variable. Set it to{" "}
          <code className="font-mono text-xs">true</code> and restart to
          activate the MCP server.
        </div>
      )}
      {!status.auth_required && (
        <div className="mt-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          Bearer authentication is disabled. This should only be used in
          development environments.
        </div>
      )}
    </section>
  );
}

function CapabilitiesEditor({
  role,
  value,
  onChange,
}: {
  role: string;
  value: string[] | null;
  onChange: (v: string[] | null) => void;
}) {
  const [useDefault, setUseDefault] = useState(value === null);
  const [caps, setCaps] = useState<string[]>(value ?? MCP_DOC_CAPABILITIES.slice(0, 5));
  const [newCap, setNewCap] = useState("");

  function toggleDefault(toDefault: boolean) {
    setUseDefault(toDefault);
    onChange(toDefault ? null : caps);
  }

  function addCap() {
    const trimmed = newCap.trim().toLowerCase();
    if (!trimmed || caps.includes(trimmed)) return;
    const next = [...caps, trimmed];
    setCaps(next);
    onChange(next);
    setNewCap("");
  }

  function removeCap(cap: string) {
    const next = caps.filter((c) => c !== cap);
    setCaps(next);
    onChange(next);
  }

  return (
    <div className="rounded-lg border border-[#d7d4e8] p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-medium text-[#2a2640] capitalize">{role}</p>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-[#68647b]">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 accent-[#3525cd]"
            checked={useDefault}
            onChange={(e) => toggleDefault(e.target.checked)}
          />
          Use server default
        </label>
      </div>

      {!useDefault && (
        <>
          <div className="mb-2 flex flex-wrap gap-1">
            {caps.map((cap) => (
              <span
                key={cap}
                className="flex items-center gap-1 rounded-full bg-[#f5f3ff] px-2.5 py-0.5 text-xs text-[#4d4880]"
              >
                {cap}
                <button
                  type="button"
                  onClick={() => removeCap(cap)}
                  className="ml-0.5 text-[#68647b] hover:text-red-600"
                  aria-label={`Remove ${cap}`}
                >
                  ×
                </button>
              </span>
            ))}
            {caps.length === 0 && (
              <span className="text-xs text-[#68647b]">
                No capabilities — this role cannot use MCP tools.
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={newCap}
              onChange={(e) => setNewCap(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addCap())}
              placeholder="e.g. chat.answer"
              className="flex-1 rounded border border-[#d7d4e8] px-2 py-1 text-xs focus:border-[#3525cd] focus:outline-none"
            />
            <button
              type="button"
              onClick={addCap}
              className="rounded bg-[#f5f3ff] px-3 py-1 text-xs font-medium text-[#3525cd] hover:bg-[#ebe8ff]"
            >
              Add
            </button>
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {MCP_DOC_CAPABILITIES.map((cap) => (
              <button
                key={cap}
                type="button"
                onClick={() => {
                  if (!caps.includes(cap)) {
                    const next = [...caps, cap];
                    setCaps(next);
                    onChange(next);
                  }
                }}
                disabled={caps.includes(cap)}
                className="rounded bg-[#f9f8ff] px-2 py-0.5 text-xs text-[#68647b] hover:bg-[#f0eeff] disabled:opacity-40"
              >
                {cap}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function PolicyForm({
  policy,
  onSaved,
}: {
  policy: OrgMCPPolicy;
  onSaved: () => void;
}) {
  const [enabled, setEnabled] = useState(policy.enabled);
  const [readOnly, setReadOnly] = useState(policy.read_only);
  const [rateLimitEnabled, setRateLimitEnabled] = useState(
    policy.rate_limit_enabled,
  );
  const [rateLimitRequests, setRateLimitRequests] = useState(
    policy.rate_limit_requests,
  );
  const [rateLimitWindow, setRateLimitWindow] = useState(
    policy.rate_limit_window_seconds,
  );
  const [capsOwner, setCapsOwner] = useState<string[] | null>(
    policy.capabilities_owner,
  );
  const [capsAdmin, setCapsAdmin] = useState<string[] | null>(
    policy.capabilities_admin,
  );
  const [capsMember, setCapsMember] = useState<string[] | null>(
    policy.capabilities_member,
  );
  const [capsViewer, setCapsViewer] = useState<string[] | null>(
    policy.capabilities_viewer,
  );
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const saveMutation = useMutation({
    mutationFn: () =>
      updateMCPPolicy({
        enabled,
        read_only: readOnly,
        rate_limit_enabled: rateLimitEnabled,
        rate_limit_requests: rateLimitRequests,
        rate_limit_window_seconds: rateLimitWindow,
        capabilities_owner: capsOwner,
        capabilities_admin: capsAdmin,
        capabilities_member: capsMember,
        capabilities_viewer: capsViewer,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.mcpPolicy });
      onSaved();
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    saveMutation.mutate();
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Enable / read-only toggles */}
      <section className="rounded-xl border border-[#d7d4e8] bg-white p-5">
        <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
          Access control
        </h2>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <label
                htmlFor="mcp-enabled"
                className="text-sm font-medium text-[#2a2640]"
              >
                MCP enabled
              </label>
              <p className="text-xs text-[#68647b]">
                Allow authenticated API clients to connect to this MCP server.
              </p>
            </div>
            <ToggleSwitch
              id="mcp-enabled"
              checked={enabled}
              onChange={setEnabled}
            />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <label
                htmlFor="mcp-readonly"
                className="text-sm font-medium text-[#2a2640]"
              >
                Read-only mode
              </label>
              <p className="text-xs text-[#68647b]">
                Restrict MCP to read-only tools only. Prevents any write
                operations even if capability is granted.
              </p>
            </div>
            <ToggleSwitch
              id="mcp-readonly"
              checked={readOnly}
              onChange={setReadOnly}
            />
          </div>
        </div>

        {enabled && !readOnly && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
            Write operations are enabled. Ensure clients are scoped to the
            minimum required capabilities.
          </div>
        )}
      </section>

      {/* Rate limiting */}
      <section className="rounded-xl border border-[#d7d4e8] bg-white p-5">
        <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
          Rate limits
        </h2>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <label
              htmlFor="mcp-ratelimit-enabled"
              className="text-sm font-medium text-[#2a2640]"
            >
              Rate limiting enabled
            </label>
            <ToggleSwitch
              id="mcp-ratelimit-enabled"
              checked={rateLimitEnabled}
              onChange={setRateLimitEnabled}
            />
          </div>

          {rateLimitEnabled && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs text-[#68647b]">
                  Requests per window (1–10000)
                </label>
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={rateLimitRequests}
                  onChange={(e) =>
                    setRateLimitRequests(Number(e.target.value))
                  }
                  className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[#68647b]">
                  Window seconds (1–3600)
                </label>
                <input
                  type="number"
                  min={1}
                  max={3600}
                  value={rateLimitWindow}
                  onChange={(e) => setRateLimitWindow(Number(e.target.value))}
                  className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
                />
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Capabilities per role */}
      <section className="rounded-xl border border-[#d7d4e8] bg-white p-5">
        <h2 className="mb-1 text-base font-semibold text-[#2a2640]">
          Role capabilities
        </h2>
        <p className="mb-4 text-sm text-[#68647b]">
          Define which MCP capabilities each role may use. "Use server default"
          applies the value from the server environment variables.
        </p>
        <div className="space-y-3">
          <CapabilitiesEditor
            role="owner"
            value={capsOwner}
            onChange={setCapsOwner}
          />
          <CapabilitiesEditor
            role="admin"
            value={capsAdmin}
            onChange={setCapsAdmin}
          />
          <CapabilitiesEditor
            role="member"
            value={capsMember}
            onChange={setCapsMember}
          />
          <CapabilitiesEditor
            role="viewer"
            value={capsViewer}
            onChange={setCapsViewer}
          />
        </div>
      </section>

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="flex gap-3">
        <button
          type="submit"
          disabled={saveMutation.isPending}
          className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
        >
          {saveMutation.isPending ? "Saving…" : "Save policy"}
        </button>
      </div>
    </form>
  );
}

function MCPToolsCard({ tools }: { tools: MCPToolInfo[] }) {
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

function AuditEventRow({ event }: { event: MCPAuditEvent }) {
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

function AuditEventsPanel() {
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
        <p className="text-sm text-[#68647b]">
          No MCP events recorded yet.
        </p>
      )}
      <div className="space-y-2">
        {events.map((event) => (
          <AuditEventRow key={event.id} event={event} />
        ))}
      </div>
    </section>
  );
}

function SetupInstructions({ status }: { status: MCPStatusResponse }) {
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
    return <ErrorState message={getApiErrorMessage(policyQuery.error)} />;
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
        <h1 className="text-2xl font-extrabold text-[#2a2640]">
          MCP server
        </h1>
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
