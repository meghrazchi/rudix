"use client";

import { ToggleSwitch, MCP_ROLES } from "@/components/admin/mcp/mcpShared";
import {
  TagListEditor,
  NullableNumberInput,
} from "@/components/admin/mcp/McpInputs";

export function MCPTrustControlsSection({
  allowedResources,
  allowedPrompts,
  allowedCollections,
  allowedRoles,
  redactDocumentText,
  maxChunkChars,
  maxRequestBytes,
  maxResponseBytes,
  onChangeAllowedResources,
  onChangeAllowedPrompts,
  onChangeAllowedCollections,
  onChangeAllowedRoles,
  onChangeRedactDocumentText,
  onChangeMaxChunkChars,
  onChangeMaxRequestBytes,
  onChangeMaxResponseBytes,
}: {
  allowedResources: string[] | null;
  allowedPrompts: string[] | null;
  allowedCollections: string[] | null;
  allowedRoles: string[] | null;
  redactDocumentText: boolean;
  maxChunkChars: number | null;
  maxRequestBytes: number | null;
  maxResponseBytes: number | null;
  onChangeAllowedResources: (v: string[] | null) => void;
  onChangeAllowedPrompts: (v: string[] | null) => void;
  onChangeAllowedCollections: (v: string[] | null) => void;
  onChangeAllowedRoles: (v: string[] | null) => void;
  onChangeRedactDocumentText: (v: boolean) => void;
  onChangeMaxChunkChars: (v: number | null) => void;
  onChangeMaxRequestBytes: (v: number | null) => void;
  onChangeMaxResponseBytes: (v: number | null) => void;
}) {
  function toggleRole(role: string, checked: boolean) {
    if (allowedRoles === null) {
      onChangeAllowedRoles(
        checked ? MCP_ROLES.filter((r) => r !== role) : [role],
      );
      return;
    }
    const next = checked
      ? [...allowedRoles, role]
      : allowedRoles.filter((r) => r !== role);
    onChangeAllowedRoles(next);
  }

  const rolesAreRestricted = allowedRoles !== null;

  return (
    <section className="rounded-xl border border-[#d7d4e8] bg-white p-5">
      <h2 className="mb-1 text-base font-semibold text-[#2a2640]">
        Trust and exposure controls
      </h2>
      <p className="mb-5 text-sm text-[#68647b]">
        Restrict which MCP surfaces can be accessed and how much raw document
        content is allowed to flow through MCP responses.
      </p>

      <div className="space-y-6">
        {/* Document redaction */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-[#2a2640]">
              Redact document text
            </p>
            <p className="text-xs text-[#68647b]">
              When enabled, raw document content is replaced with a placeholder
              or truncated to the chunk char limit. Disable only for trusted
              internal clients.
            </p>
          </div>
          <ToggleSwitch
            id="mcp-redact-doc"
            checked={redactDocumentText}
            onChange={onChangeRedactDocumentText}
            ariaLabel="Redact document text"
          />
        </div>

        {!redactDocumentText && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
            Raw document text may be returned in MCP responses. Ensure this is
            intentional and clients are fully trusted.
          </div>
        )}

        {/* Allowed roles */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-[#2a2640]">
                Allowed roles
              </p>
              <p className="text-xs text-[#68647b]">
                Restrict MCP access to specific org roles. Leave unrestricted to
                allow all roles.
              </p>
            </div>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-[#68647b]">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-[#3525cd]"
                checked={!rolesAreRestricted}
                onChange={(e) =>
                  onChangeAllowedRoles(e.target.checked ? null : [...MCP_ROLES])
                }
              />
              Allow all roles
            </label>
          </div>
          {rolesAreRestricted && (
            <div className="flex flex-wrap gap-3">
              {MCP_ROLES.map((role) => {
                const checked = allowedRoles!.includes(role);
                return (
                  <label
                    key={role}
                    className="flex cursor-pointer items-center gap-1.5 text-sm text-[#2a2640]"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-[#3525cd]"
                      checked={checked}
                      onChange={(e) => toggleRole(role, e.target.checked)}
                    />
                    <span className="capitalize">{role}</span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        {/* Resource / prompt / collection allowlists */}
        <TagListEditor
          label="Allowed resources"
          description="URI patterns for MCP resources clients may read. Use '*' suffix for prefix matching (e.g. rag://documents/*)."
          value={allowedResources}
          onChange={onChangeAllowedResources}
          placeholder="e.g. rag://documents/*"
        />

        <TagListEditor
          label="Allowed prompts"
          description="MCP prompt names clients are permitted to invoke. Null means all prompts are allowed."
          value={allowedPrompts}
          onChange={onChangeAllowedPrompts}
          placeholder="e.g. summarize"
        />

        <TagListEditor
          label="Allowed collections"
          description="Collection IDs or slugs accessible via MCP. Null means all collections are accessible."
          value={allowedCollections}
          onChange={onChangeAllowedCollections}
          placeholder="e.g. col-abc123"
        />

        {/* Size limits */}
        <NullableNumberInput
          label="Max chunk chars"
          description="Maximum characters returned per document chunk in MCP responses."
          value={maxChunkChars}
          onChange={onChangeMaxChunkChars}
          min={100}
          unit="characters"
        />

        <NullableNumberInput
          label="Max request bytes"
          description="Maximum MCP request payload size in bytes."
          value={maxRequestBytes}
          onChange={onChangeMaxRequestBytes}
          min={256}
          unit="bytes"
        />

        <NullableNumberInput
          label="Max response bytes"
          description="Maximum MCP response payload size in bytes."
          value={maxResponseBytes}
          onChange={onChangeMaxResponseBytes}
          min={256}
          unit="bytes"
        />
      </div>
    </section>
  );
}
