"use client";

import { useState } from "react";
import { type ServiceAccount } from "@/lib/api/service-accounts";

export const SCOPE_LABELS: Record<string, string> = {
  "documents:read": "Documents — read",
  "documents:write": "Documents — write",
  "chat:write": "Chat — write",
  "evaluations:run": "Evaluations — run",
  "webhooks:manage": "Webhooks — manage",
  "connectors:manage": "Connectors — manage",
};

export const ENV_LABELS: Record<string, string> = {
  production: "Production",
  staging: "Staging",
  ci: "CI",
  development: "Development",
};

export type PanelState =
  | { kind: "idle" }
  | { kind: "create_account" }
  | { kind: "edit_account"; account: ServiceAccount }
  | { kind: "view_tokens"; account: ServiceAccount }
  | { kind: "create_token"; account: ServiceAccount };

export function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="rounded bg-[#3525cd] px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-[#2b1fa8]"
    >
      {copied ? "Copied!" : "Copy token"}
    </button>
  );
}
