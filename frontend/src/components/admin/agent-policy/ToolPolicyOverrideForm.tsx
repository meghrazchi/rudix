"use client";

import { useState } from "react";

import type {
  OrgToolPolicyOverride,
  ToolPolicyOverrideState,
} from "@/lib/api/admin-agent-policy";

export function ToolPolicyOverrideForm({
  toolName,
  existing,
  resolved,
  onSave,
  onDelete,
  onCancel,
  isSaving,
}: {
  toolName: string;
  existing: OrgToolPolicyOverride | null;
  resolved: ToolPolicyOverrideState;
  onSave: (draft: Partial<OrgToolPolicyOverride>) => void;
  onDelete: () => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const [enabled, setEnabled] = useState(existing?.enabled ?? true);
  const [approvalRequired, setApprovalRequired] = useState<string>(
    existing?.approval_required != null ? String(existing.approval_required) : "",
  );
  const [requiredRoles, setRequiredRoles] = useState(
    existing?.required_roles?.join(", ") ?? "",
  );
  const [maxCalls, setMaxCalls] = useState(
    existing?.max_calls_per_run != null ? String(existing.max_calls_per_run) : "",
  );
  const [maxInput, setMaxInput] = useState(
    existing?.max_input_bytes != null ? String(existing.max_input_bytes) : "",
  );
  const [maxOutput, setMaxOutput] = useState(
    existing?.max_output_bytes != null ? String(existing.max_output_bytes) : "",
  );
  const [timeoutMs, setTimeoutMs] = useState(
    existing?.timeout_ms != null ? String(existing.timeout_ms) : "",
  );
  const [maxRetry, setMaxRetry] = useState(
    existing?.max_retry_attempts != null ? String(existing.max_retry_attempts) : "",
  );

  function parseOptionalInt(value: string): number | null {
    if (!value.trim()) return null;
    const n = Number.parseInt(value, 10);
    return Number.isFinite(n) ? n : null;
  }

  function parseOptionalBool(value: string): boolean | null {
    if (value === "true") return true;
    if (value === "false") return false;
    return null;
  }

  function parseRoles(value: string): string[] | null {
    const parts = value
      .split(",")
      .map((r) => r.trim().toLowerCase())
      .filter((r) => r.length > 0);
    return parts.length > 0 ? parts : null;
  }

  function handleSave() {
    onSave({
      tool_name: toolName,
      enabled,
      approval_required: parseOptionalBool(approvalRequired) ?? undefined,
      required_roles: parseRoles(requiredRoles) ?? undefined,
      max_calls_per_run: parseOptionalInt(maxCalls) ?? undefined,
      max_input_bytes: parseOptionalInt(maxInput) ?? undefined,
      max_output_bytes: parseOptionalInt(maxOutput) ?? undefined,
      timeout_ms: parseOptionalInt(timeoutMs) ?? undefined,
      max_retry_attempts: parseOptionalInt(maxRetry) ?? undefined,
    });
  }

  return (
    <div className="rounded-xl border border-[#d7d4e8] bg-[#faf9ff] p-4">
      <p className="mb-3 font-mono text-xs font-semibold text-[#2a2640]">{toolName}</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex items-center gap-2 text-xs font-semibold text-[#6a6780]">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="h-4 w-4 rounded"
          />
          Enabled
        </label>
        <FieldInput
          label={`Approval required (default: ${resolved.approval_required})`}
          placeholder="true / false / (inherit)"
          value={approvalRequired}
          onChange={setApprovalRequired}
        />
        <FieldInput
          label={`Required roles (default: ${resolved.required_roles.join(", ")})`}
          placeholder="owner, admin"
          value={requiredRoles}
          onChange={setRequiredRoles}
        />
        <FieldInput
          label={`Max calls/run (default: ${resolved.max_calls_per_run})`}
          placeholder="inherit"
          value={maxCalls}
          onChange={setMaxCalls}
        />
        <FieldInput
          label={`Max input bytes (default: ${resolved.max_input_bytes})`}
          placeholder="inherit"
          value={maxInput}
          onChange={setMaxInput}
        />
        <FieldInput
          label={`Max output bytes (default: ${resolved.max_output_bytes})`}
          placeholder="inherit"
          value={maxOutput}
          onChange={setMaxOutput}
        />
        <FieldInput
          label={`Timeout ms (default: ${resolved.timeout_ms})`}
          placeholder="inherit"
          value={timeoutMs}
          onChange={setTimeoutMs}
        />
        <FieldInput
          label={`Max retry attempts (default: ${resolved.max_retry_attempts})`}
          placeholder="inherit"
          value={maxRetry}
          onChange={setMaxRetry}
        />
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="rounded-lg bg-[#6c63e0] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#5750c8] disabled:opacity-50"
        >
          {isSaving ? "Saving…" : "Save override"}
        </button>
        {existing && (
          <button
            onClick={onDelete}
            disabled={isSaving}
            className="rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-600 hover:bg-rose-50 disabled:opacity-50"
          >
            Remove override
          </button>
        )}
        <button
          onClick={onCancel}
          className="rounded-lg px-3 py-1.5 text-xs font-semibold text-[#6a6780] hover:bg-[#f0edf8]"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function FieldInput({
  label,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
      {label}
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640] placeholder-[#c0bcd6]"
      />
    </label>
  );
}
