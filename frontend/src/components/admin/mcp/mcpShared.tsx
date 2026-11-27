"use client";

import { type MCPStatusResponse } from "@/lib/api/mcp";

export const MCP_DOC_CAPABILITIES = [
  "documents.read",
  "documents.chunks.read",
  "documents.summary.read",
  "documents.compare.read",
  "pipeline.read",
  "chat.answer",
];

export function ToggleSwitch({
  checked,
  onChange,
  disabled,
  id,
  ariaLabel,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  id: string;
  ariaLabel?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
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

export function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        ok ? "bg-[#e8f5e9] text-[#2e7d32]" : "bg-red-100 text-red-700"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-[#2e7d32]" : "bg-red-600"}`}
      />
      {label}
    </span>
  );
}

export function MCPStatusCard({ status }: { status: MCPStatusResponse }) {
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

export const MCP_ROLES = ["owner", "admin", "member", "viewer"] as const;
