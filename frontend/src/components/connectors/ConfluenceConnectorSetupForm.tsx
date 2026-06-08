"use client";

import { useState } from "react";

export type ConfluenceConnectorConfig = {
  site_url: string;
  space_keys: string[];
  cql_filter: string;
  include_comments: boolean;
};

type FieldError = {
  site_url?: string;
  space_keys?: string;
  cql_filter?: string;
};

function validate(config: ConfluenceConnectorConfig): FieldError {
  const errors: FieldError = {};
  const siteUrl = config.site_url.trim();
  if (!siteUrl) {
    errors.site_url = "Site URL is required.";
  } else if (!/^https?:\/\/.+/.test(siteUrl)) {
    errors.site_url = "Site URL must start with https:// or http://.";
  }
  return errors;
}

function parseSpaceKeys(raw: string): string[] {
  return raw
    .split(",")
    .map((k) => k.trim().toUpperCase())
    .filter(Boolean);
}

type Props = {
  initialConfig?: Partial<ConfluenceConnectorConfig>;
  onSubmit: (config: ConfluenceConnectorConfig) => void;
  onCancel?: () => void;
  isSubmitting?: boolean;
  submitLabel?: string;
};

export function ConfluenceConnectorSetupForm({
  initialConfig,
  onSubmit,
  onCancel,
  isSubmitting = false,
  submitLabel = "Connect Confluence",
}: Props) {
  const [siteUrl, setSiteUrl] = useState(initialConfig?.site_url ?? "");
  const [spaceKeysRaw, setSpaceKeysRaw] = useState(
    (initialConfig?.space_keys ?? []).join(", "),
  );
  const [cqlFilter, setCqlFilter] = useState(initialConfig?.cql_filter ?? "");
  const [includeComments, setIncludeComments] = useState(
    initialConfig?.include_comments ?? false,
  );
  const [errors, setErrors] = useState<FieldError>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  function handleBlur(field: keyof FieldError) {
    setTouched((prev) => ({ ...prev, [field]: true }));
    const config: ConfluenceConnectorConfig = {
      site_url: siteUrl,
      space_keys: parseSpaceKeys(spaceKeysRaw),
      cql_filter: cqlFilter.trim(),
      include_comments: includeComments,
    };
    setErrors(validate(config));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const config: ConfluenceConnectorConfig = {
      site_url: siteUrl.trim(),
      space_keys: parseSpaceKeys(spaceKeysRaw),
      cql_filter: cqlFilter.trim(),
      include_comments: includeComments,
    };
    const errs = validate(config);
    setErrors(errs);
    setTouched({ site_url: true, space_keys: true, cql_filter: true });
    if (Object.keys(errs).length > 0) return;
    onSubmit(config);
  }

  const showError = (field: keyof FieldError) =>
    touched[field] && errors[field];

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      <div>
        <label
          htmlFor="confluence-site-url"
          className="block text-sm font-medium text-gray-900"
        >
          Confluence site URL
          <span className="ml-1 text-red-500" aria-hidden="true">
            *
          </span>
        </label>
        <p className="mt-0.5 text-xs text-gray-500">
          Your Atlassian domain, e.g.{" "}
          <span className="font-mono">https://myteam.atlassian.net</span>
        </p>
        <input
          id="confluence-site-url"
          type="url"
          required
          autoComplete="url"
          placeholder="https://myteam.atlassian.net"
          value={siteUrl}
          onChange={(e) => setSiteUrl(e.target.value)}
          onBlur={() => handleBlur("site_url")}
          aria-describedby={
            showError("site_url") ? "confluence-site-url-error" : undefined
          }
          aria-invalid={!!showError("site_url")}
          className={`mt-1.5 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:ring-2 focus:outline-none ${
            showError("site_url")
              ? "border-red-400 focus:border-red-400 focus:ring-red-200"
              : "border-gray-300 focus:border-indigo-500 focus:ring-indigo-200"
          }`}
        />
        {showError("site_url") && (
          <p
            id="confluence-site-url-error"
            role="alert"
            className="mt-1 text-xs text-red-600"
          >
            {errors.site_url}
          </p>
        )}
      </div>

      <div>
        <label
          htmlFor="confluence-space-keys"
          className="block text-sm font-medium text-gray-900"
        >
          Space keys{" "}
          <span className="font-normal text-gray-500">(optional)</span>
        </label>
        <p className="mt-0.5 text-xs text-gray-500">
          Comma-separated space keys to sync, e.g.{" "}
          <span className="font-mono">DOCS, ENG</span>. Leave blank to sync all
          accessible spaces.
        </p>
        <input
          id="confluence-space-keys"
          type="text"
          placeholder="DOCS, ENG, TEAM"
          value={spaceKeysRaw}
          onChange={(e) => setSpaceKeysRaw(e.target.value)}
          onBlur={() => handleBlur("space_keys")}
          className="mt-1.5 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 focus:outline-none"
        />
      </div>

      <div>
        <label
          htmlFor="confluence-cql-filter"
          className="block text-sm font-medium text-gray-900"
        >
          CQL filter{" "}
          <span className="font-normal text-gray-500">(optional)</span>
        </label>
        <p className="mt-0.5 text-xs text-gray-500">
          Additional CQL predicate applied to every sync, e.g.{" "}
          <span className="font-mono">label = "docs"</span>
        </p>
        <input
          id="confluence-cql-filter"
          type="text"
          placeholder='label = "docs"'
          value={cqlFilter}
          onChange={(e) => setCqlFilter(e.target.value)}
          onBlur={() => handleBlur("cql_filter")}
          className="mt-1.5 block w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm shadow-sm focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 focus:outline-none"
        />
      </div>

      <div className="flex items-start gap-3">
        <input
          id="confluence-include-comments"
          type="checkbox"
          checked={includeComments}
          onChange={(e) => setIncludeComments(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
        />
        <div>
          <label
            htmlFor="confluence-include-comments"
            className="block text-sm font-medium text-gray-900"
          >
            Include page comments
          </label>
          <p className="text-xs text-gray-500">
            Import inline and footer comments as searchable items. This
            increases sync time.
          </p>
        </div>
      </div>

      <div className="flex items-center justify-end gap-3 border-t border-gray-100 pt-4">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
        )}
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {isSubmitting ? "Connecting…" : submitLabel}
        </button>
      </div>
    </form>
  );
}
