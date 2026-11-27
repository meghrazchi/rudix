"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  updateMCPPolicy,
  type OrgMCPPolicy,
  type UpdateMCPPolicyRequest,
} from "@/lib/api/mcp";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { ToggleSwitch } from "@/components/admin/mcp/mcpShared";
import { CapabilitiesEditor } from "@/components/admin/mcp/CapabilitiesEditor";
import { MCPTrustControlsSection } from "@/components/admin/mcp/MCPTrustControlsSection";

export function PolicyForm({
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
  // F176 trust controls
  const [allowedResources, setAllowedResources] = useState<string[] | null>(
    policy.allowed_resources,
  );
  const [allowedPrompts, setAllowedPrompts] = useState<string[] | null>(
    policy.allowed_prompts,
  );
  const [allowedCollections, setAllowedCollections] = useState<string[] | null>(
    policy.allowed_collections,
  );
  const [allowedRoles, setAllowedRoles] = useState<string[] | null>(
    policy.allowed_roles,
  );
  const [redactDocumentText, setRedactDocumentText] = useState(
    policy.redact_document_text,
  );
  const [maxChunkChars, setMaxChunkChars] = useState<number | null>(
    policy.max_chunk_chars,
  );
  const [maxRequestBytes, setMaxRequestBytes] = useState<number | null>(
    policy.max_request_bytes,
  );
  const [maxResponseBytes, setMaxResponseBytes] = useState<number | null>(
    policy.max_response_bytes,
  );
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const saveMutation = useMutation({
    mutationFn: () => {
      const req: UpdateMCPPolicyRequest = {
        enabled,
        read_only: readOnly,
        rate_limit_enabled: rateLimitEnabled,
        rate_limit_requests: rateLimitRequests,
        rate_limit_window_seconds: rateLimitWindow,
        capabilities_owner: capsOwner,
        capabilities_admin: capsAdmin,
        capabilities_member: capsMember,
        capabilities_viewer: capsViewer,
        allowed_resources: allowedResources,
        allowed_prompts: allowedPrompts,
        allowed_collections: allowedCollections,
        allowed_roles: allowedRoles,
        redact_document_text: redactDocumentText,
        max_chunk_chars: maxChunkChars,
        max_request_bytes: maxRequestBytes,
        max_response_bytes: maxResponseBytes,
      };
      return updateMCPPolicy(req);
    },
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
                  onChange={(e) => setRateLimitRequests(Number(e.target.value))}
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
          Define which MCP capabilities each role may use. &quot;Use server
          default&quot; applies the value from the server environment variables.
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

      {/* Trust and exposure controls */}
      <MCPTrustControlsSection
        allowedResources={allowedResources}
        allowedPrompts={allowedPrompts}
        allowedCollections={allowedCollections}
        allowedRoles={allowedRoles}
        redactDocumentText={redactDocumentText}
        maxChunkChars={maxChunkChars}
        maxRequestBytes={maxRequestBytes}
        maxResponseBytes={maxResponseBytes}
        onChangeAllowedResources={setAllowedResources}
        onChangeAllowedPrompts={setAllowedPrompts}
        onChangeAllowedCollections={setAllowedCollections}
        onChangeAllowedRoles={setAllowedRoles}
        onChangeRedactDocumentText={setRedactDocumentText}
        onChangeMaxChunkChars={setMaxChunkChars}
        onChangeMaxRequestBytes={setMaxRequestBytes}
        onChangeMaxResponseBytes={setMaxResponseBytes}
      />

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
