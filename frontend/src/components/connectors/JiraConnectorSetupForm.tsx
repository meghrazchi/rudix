"use client";

import { useState } from "react";

export type JiraConnectorConfig = {
  site_url: string;
  project_keys: string[];
  jql_filter: string;
};

type FieldError = {
  site_url?: string;
  project_keys?: string;
  jql_filter?: string;
};

function validate(config: JiraConnectorConfig): FieldError {
  const errors: FieldError = {};
  const siteUrl = config.site_url.trim();
  if (!siteUrl) {
    errors.site_url = "Site URL is required.";
  } else if (!/^https?:\/\/.+/.test(siteUrl)) {
    errors.site_url = "Site URL must start with https:// or http://.";
  }
  return errors;
}

function parseProjectKeys(raw: string): string[] {
  return raw
    .split(",")
    .map((k) => k.trim().toUpperCase())
    .filter(Boolean);
}

type Props = {
  initialConfig?: Partial<JiraConnectorConfig>;
  onSubmit: (config: JiraConnectorConfig) => void;
  onCancel?: () => void;
  isSubmitting?: boolean;
  submitLabel?: string;
};

export function JiraConnectorSetupForm({
  initialConfig,
  onSubmit,
  onCancel,
  isSubmitting = false,
  submitLabel = "Connect Jira",
}: Props) {
  const [siteUrl, setSiteUrl] = useState(initialConfig?.site_url ?? "");
  const [projectKeysRaw, setProjectKeysRaw] = useState(
    (initialConfig?.project_keys ?? []).join(", "),
  );
  const [jqlFilter, setJqlFilter] = useState(initialConfig?.jql_filter ?? "");
  const [errors, setErrors] = useState<FieldError>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  function handleBlur(field: keyof FieldError) {
    setTouched((prev) => ({ ...prev, [field]: true }));
    const config: JiraConnectorConfig = {
      site_url: siteUrl,
      project_keys: parseProjectKeys(projectKeysRaw),
      jql_filter: jqlFilter.trim(),
    };
    setErrors(validate(config));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const config: JiraConnectorConfig = {
      site_url: siteUrl.trim(),
      project_keys: parseProjectKeys(projectKeysRaw),
      jql_filter: jqlFilter.trim(),
    };
    const errs = validate(config);
    setErrors(errs);
    setTouched({ site_url: true, project_keys: true, jql_filter: true });
    if (Object.keys(errs).length > 0) return;
    onSubmit(config);
  }

  const showError = (field: keyof FieldError) =>
    touched[field] && errors[field];

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      <div>
        <label
          htmlFor="jira-site-url"
          className="block text-sm font-medium text-gray-900"
        >
          Jira site URL
          <span className="ml-1 text-red-500" aria-hidden="true">
            *
          </span>
        </label>
        <p className="mt-0.5 text-xs text-gray-500">
          Your Atlassian domain, e.g.{" "}
          <span className="font-mono">https://myteam.atlassian.net</span>
        </p>
        <input
          id="jira-site-url"
          type="url"
          required
          autoComplete="url"
          placeholder="https://myteam.atlassian.net"
          value={siteUrl}
          onChange={(e) => setSiteUrl(e.target.value)}
          onBlur={() => handleBlur("site_url")}
          aria-describedby={showError("site_url") ? "jira-site-url-error" : undefined}
          aria-invalid={!!showError("site_url")}
          className={`mt-1.5 block w-full rounded-md border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 ${
            showError("site_url")
              ? "border-red-400 focus:border-red-400 focus:ring-red-200"
              : "border-gray-300 focus:border-indigo-500 focus:ring-indigo-200"
          }`}
        />
        {showError("site_url") && (
          <p
            id="jira-site-url-error"
            role="alert"
            className="mt-1 text-xs text-red-600"
          >
            {errors.site_url}
          </p>
        )}
      </div>

      <div>
        <label
          htmlFor="jira-project-keys"
          className="block text-sm font-medium text-gray-900"
        >
          Project keys{" "}
          <span className="font-normal text-gray-500">(optional)</span>
        </label>
        <p className="mt-0.5 text-xs text-gray-500">
          Comma-separated project keys to sync, e.g.{" "}
          <span className="font-mono">PROJ, TEAM</span>. Leave blank to sync
          all accessible projects.
        </p>
        <input
          id="jira-project-keys"
          type="text"
          placeholder="PROJ, TEAM, WEB"
          value={projectKeysRaw}
          onChange={(e) => setProjectKeysRaw(e.target.value)}
          onBlur={() => handleBlur("project_keys")}
          className="mt-1.5 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
        />
      </div>

      <div>
        <label
          htmlFor="jira-jql-filter"
          className="block text-sm font-medium text-gray-900"
        >
          JQL filter{" "}
          <span className="font-normal text-gray-500">(optional)</span>
        </label>
        <p className="mt-0.5 text-xs text-gray-500">
          Additional JQL predicate applied to every sync, e.g.{" "}
          <span className="font-mono">status != Done AND labels = "docs"</span>
        </p>
        <input
          id="jira-jql-filter"
          type="text"
          placeholder='status != Done'
          value={jqlFilter}
          onChange={(e) => setJqlFilter(e.target.value)}
          onBlur={() => handleBlur("jql_filter")}
          className="mt-1.5 block w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
        />
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
