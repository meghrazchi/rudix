"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useEffectivePermissions } from "@/lib/use-permissions";
import {
  DEFAULT_REDACTION_CONFIG,
  SOURCE_TYPE_LABELS,
  exportTroubleshootingBundle,
  type BundleRedactionConfig,
  type BundleSourceType,
  type TroubleshootingBundleRequest,
} from "@/lib/api/troubleshooting-bundle";

const SOURCE_TYPES = Object.keys(SOURCE_TYPE_LABELS) as BundleSourceType[];

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function guessFilename(
  sourceType: BundleSourceType,
  includeMarkdown: boolean,
): string {
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const ext = includeMarkdown ? "md" : "json";
  return `bundle_${sourceType}_${ts}.${ext}`;
}

function RedactionToggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="group flex cursor-pointer items-start gap-3">
      <div className="relative mt-0.5 flex-shrink-0">
        <input
          type="checkbox"
          className="sr-only"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <div
          className={`h-5 w-9 rounded-full transition-colors ${
            checked ? "bg-blue-600" : "bg-gray-200"
          }`}
        />
        <div
          className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
            checked ? "translate-x-4" : ""
          }`}
        />
      </div>
      <div>
        <p className="text-sm font-medium text-gray-800">{label}</p>
        <p className="text-xs text-gray-500">{description}</p>
      </div>
    </label>
  );
}

export function AdminTroubleshootingBundlePage() {
  const { hasPermission, isLoading: permsLoading } = useEffectivePermissions();

  const [sourceType, setSourceType] =
    useState<BundleSourceType>("chat_message");
  const [sourceId, setSourceId] = useState("");
  const [includeMarkdown, setIncludeMarkdown] = useState(false);
  const [redaction, setRedaction] = useState<BundleRedactionConfig>(
    DEFAULT_REDACTION_CONFIG,
  );
  const [exportError, setExportError] = useState<string | null>(null);
  const [lastExported, setLastExported] = useState<string | null>(null);

  const { mutate: doExport, isPending } = useMutation({
    mutationFn: async (req: TroubleshootingBundleRequest) =>
      exportTroubleshootingBundle(req),
    onSuccess: (blob) => {
      const filename = guessFilename(sourceType, includeMarkdown);
      downloadBlob(blob, filename);
      setExportError(null);
      setLastExported(new Date().toLocaleString());
    },
    onError: (err) => {
      setExportError(getApiErrorMessage(err));
    },
  });

  function handleExport(e: React.FormEvent) {
    e.preventDefault();
    if (!sourceId.trim()) return;
    setExportError(null);
    doExport({
      source_type: sourceType,
      source_id: sourceId.trim(),
      include_markdown: includeMarkdown,
      redaction,
    });
  }

  function toggleRedaction(key: keyof BundleRedactionConfig, value: boolean) {
    setRedaction((prev) => ({ ...prev, [key]: value }));
  }

  if (!permsLoading && !hasPermission("security_center:view")) {
    return (
      <ForbiddenState
        title="Access Denied"
        description="You need the Security Center permission to export troubleshooting bundles."
      />
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">
          Troubleshooting Bundle Export
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Export a redacted diagnostic bundle for a chat message, document,
          connector sync, evaluation run, or failed job. Bundles never include
          secrets, credentials, or raw document content. Every export is
          recorded in the audit log.
        </p>
      </div>

      <form onSubmit={handleExport} className="space-y-6">
        {/* Source selection */}
        <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold tracking-wide text-gray-700 uppercase">
            Source
          </h2>

          <div className="space-y-1">
            <label className="block text-sm font-medium text-gray-700">
              Resource type
            </label>
            <select
              value={sourceType}
              onChange={(e) =>
                setSourceType(e.target.value as BundleSourceType)
              }
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
            >
              {SOURCE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {SOURCE_TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <label className="block text-sm font-medium text-gray-700">
              Resource ID (UUID)
            </label>
            <input
              type="text"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              placeholder="e.g. 123e4567-e89b-12d3-a456-426614174000"
              className="w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
              required
              pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
              title="Must be a valid UUID"
            />
          </div>
        </div>

        {/* Redaction rules */}
        <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-6">
          <div>
            <h2 className="text-sm font-semibold tracking-wide text-gray-700 uppercase">
              Redaction Rules
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              Bundles always strip credentials, API keys, and refresh tokens.
              The controls below let you further restrict what diagnostic data
              is included.
            </p>
          </div>

          <div className="space-y-4">
            <RedactionToggle
              label="Redact prompts"
              description="Strip LLM prompts and system instructions from pipeline logs"
              checked={redaction.redact_prompts}
              onChange={(v) => toggleRedaction("redact_prompts", v)}
            />
            <RedactionToggle
              label="Redact source snippets"
              description="Remove retrieved document chunks and citation text from logs"
              checked={redaction.redact_snippets}
              onChange={(v) => toggleRedaction("redact_snippets", v)}
            />
            <RedactionToggle
              label="Redact PII"
              description="Apply PII redaction to log fields and user-facing strings"
              checked={redaction.redact_pii}
              onChange={(v) => toggleRedaction("redact_pii", v)}
            />
            <RedactionToggle
              label="Redact source content"
              description="Omit document filenames and raw content from citations"
              checked={redaction.redact_source_content}
              onChange={(v) => toggleRedaction("redact_source_content", v)}
            />
            <RedactionToggle
              label="Include redacted logs"
              description="Include pipeline log lines (with sensitive fields stripped). Turn off to omit logs entirely"
              checked={redaction.include_redacted_logs}
              onChange={(v) => toggleRedaction("include_redacted_logs", v)}
            />
          </div>
        </div>

        {/* Output format */}
        <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-6">
          <h2 className="text-sm font-semibold tracking-wide text-gray-700 uppercase">
            Output
          </h2>
          <RedactionToggle
            label="Include Markdown summary"
            description="Download a human-readable .md summary instead of the full JSON bundle"
            checked={includeMarkdown}
            onChange={setIncludeMarkdown}
          />
        </div>

        {/* Error */}
        {exportError && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {exportError}
          </div>
        )}

        {/* Success */}
        {lastExported && !exportError && (
          <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
            Bundle exported at {lastExported}. Check your Downloads folder.
          </div>
        )}

        {/* Submit */}
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-400">
            This action is logged in the audit trail.
          </p>
          <button
            type="submit"
            disabled={isPending || !sourceId.trim()}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:outline-none disabled:bg-blue-300"
          >
            {isPending ? (
              <>
                <svg
                  className="h-4 w-4 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Generating…
              </>
            ) : (
              "Export Bundle"
            )}
          </button>
        </div>
      </form>

      {/* Help text */}
      <div className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
        <p className="font-medium">What is included in a bundle?</p>
        <ul className="list-inside list-disc space-y-0.5 text-xs">
          <li>Trace ID, request ID, and pipeline stage status</li>
          <li>Model name, provider, token counts, and latency</li>
          <li>Retrieval profile, scores, and reranker status</li>
          <li>
            Citations with document IDs (no raw text unless redaction is off)
          </li>
          <li>Redacted pipeline log lines (no secrets or credentials)</li>
          <li>Configuration fingerprint (profile keys, feature flags)</li>
          <li>Warnings and error codes</li>
        </ul>
      </div>
    </div>
  );
}
