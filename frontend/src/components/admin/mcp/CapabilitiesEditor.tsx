"use client";

import { useState } from "react";
import { MCP_DOC_CAPABILITIES } from "@/components/admin/mcp/mcpShared";

export function CapabilitiesEditor({
  role,
  value,
  onChange,
}: {
  role: string;
  value: string[] | null;
  onChange: (v: string[] | null) => void;
}) {
  const [useDefault, setUseDefault] = useState(value === null);
  const [caps, setCaps] = useState<string[]>(
    value ?? MCP_DOC_CAPABILITIES.slice(0, 5),
  );
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
              onKeyDown={(e) =>
                e.key === "Enter" && (e.preventDefault(), addCap())
              }
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
