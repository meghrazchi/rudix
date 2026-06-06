"use client";

import { useMemo, useState } from "react";

import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { ConnectorWizard } from "@/components/connectors/wizard/ConnectorWizard";
import type { ConnectorWizardConfig } from "@/components/connectors/wizard/types";
import type { WizardStepProps } from "@/components/connectors/wizard/types";
import { ProviderCapabilityBadges } from "@/components/connectors/ProviderCapabilityBadges";
import { getApiErrorMessage, type ApiClientError } from "@/lib/api/errors";
import {
  beginConnectorOAuthConnect,
  createConnectorConnection,
} from "@/lib/api/connectors";
import {
  getProvider,
  type ProviderConfigSchemaField,
  type ProviderSummary,
} from "@/lib/api/connector-providers";
import { queryKeys } from "@/lib/api/query";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

type ConnectorSetupState = {
  display_name: string;
  external_account_id: string;
  config_values: Record<string, string | boolean>;
};

type Props = {
  providerKey: string;
};

function buildConfigFieldState(
  schema: ProviderSummary["config_schema"],
  existingValues?: Record<string, unknown>,
): Record<string, string | boolean> {
  const fields = schema.properties ?? {};
  const next: Record<string, string | boolean> = {};

  for (const [name, field] of Object.entries(fields)) {
    const current = existingValues?.[name];
    next[name] = normalizeFieldValue(field, current);
  }

  return next;
}

function normalizeFieldValue(
  field: ProviderConfigSchemaField,
  value: unknown,
): string | boolean {
  if (field.type === "boolean") {
    return Boolean(value);
  }
  if (field.type === "array") {
    if (Array.isArray(value)) {
      return value
        .map((item) => String(item).trim())
        .filter(Boolean)
        .join(", ");
    }
    return typeof value === "string" ? value : "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function toStringArray(value: string | boolean, uppercase = false): string[] {
  if (typeof value === "boolean") {
    return value ? ["true"] : [];
  }
  return value
    .split(",")
    .map((item) => item.trim())
    .map((item) => (uppercase ? item.toUpperCase() : item))
    .filter((item) => item.length > 0);
}

function fieldLabel(name: string, field: ProviderConfigSchemaField): string {
  return field.title ?? name.replace(/_/g, " ");
}

function fieldPlaceholder(
  name: string,
  field: ProviderConfigSchemaField,
): string {
  if (field.format === "uri") {
    return "https://example.atlassian.net";
  }
  if (field.type === "array") {
    return `${name.replace(/_/g, " ")} separated by commas`;
  }
  if (field.type === "boolean") {
    return "true";
  }
  return name.replace(/_/g, " ");
}

function validateConfigField(
  field: ProviderConfigSchemaField,
  rawValue: string | boolean,
  required: boolean,
): string | null {
  if (field.type === "boolean") {
    return null;
  }

  const value = typeof rawValue === "string" ? rawValue.trim() : "";
  if (!value && required) {
    return "This field is required.";
  }
  if (!value) {
    return null;
  }
  if (field.format === "uri" && !/^https?:\/\/.+/i.test(value)) {
    return "Use an absolute http(s) URL.";
  }
  return null;
}

function parseConfigValue(
  name: string,
  field: ProviderConfigSchemaField,
  value: string | boolean,
): unknown {
  if (field.type === "boolean") {
    return Boolean(value);
  }
  if (field.type === "array") {
    return toStringArray(value, ["project_keys", "space_keys"].includes(name));
  }
  if (field.type === "integer") {
    const parsed = Number.parseInt(String(value).trim(), 10);
    return Number.isFinite(parsed) ? parsed : null;
  }
  if (field.type === "number") {
    const parsed = Number.parseFloat(String(value).trim());
    return Number.isFinite(parsed) ? parsed : null;
  }
  return String(value).trim();
}

function buildProviderConfig(
  schema: ProviderSummary["config_schema"],
  values: Record<string, string | boolean>,
): Record<string, unknown> {
  const fields = schema.properties ?? {};
  const payload: Record<string, unknown> = {};

  for (const [name, field] of Object.entries(fields)) {
    const value = values[name];
    if (value === undefined) {
      continue;
    }
    payload[name] = parseConfigValue(name, field, value);
  }

  return payload;
}

function configSummary(
  provider: ProviderSummary,
  values: Record<string, string | boolean>,
): string[] {
  const fields = provider.config_schema.properties ?? {};
  const selected: string[] = [];

  for (const [name, field] of Object.entries(fields)) {
    const value = values[name];
    const label = fieldLabel(name, field);
    if (field.type === "boolean") {
      if (Boolean(value)) {
        selected.push(`${label}: enabled`);
      }
      continue;
    }
    if (field.type === "array") {
      const items =
        typeof value === "string" ? toStringArray(value) : ([] as string[]);
      if (items.length > 0) {
        selected.push(`${label}: ${items.join(", ")}`);
      }
      continue;
    }
    const text = typeof value === "string" ? value.trim() : "";
    if (text) {
      selected.push(`${label}: ${text}`);
    }
  }

  if (provider.capabilities.capabilities.includes("acls")) {
    selected.push("ACL metadata will be captured for trust-aware citations.");
  }
  return selected;
}

function BasicStep({
  state,
  onChange,
  provider,
}: WizardStepProps<ConnectorSetupState> & { provider: ProviderSummary }) {
  return (
    <div className="grid gap-5 lg:grid-cols-[1.3fr,0.9fr]">
      <div className="space-y-5">
        <div>
          <label
            className="block text-sm font-semibold text-[#2a2640]"
            htmlFor="connector-display-name"
          >
            Connection name
          </label>
          <input
            id="connector-display-name"
            type="text"
            value={state.display_name}
            onChange={(event) => onChange({ display_name: event.target.value })}
            className="mt-1.5 w-full rounded-xl border border-[#d7d4e8] bg-white px-3 py-2.5 text-sm text-[#2a2640] shadow-sm focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/20 focus:outline-none"
            placeholder={`${provider.display_name} for Engineering`}
          />
        </div>

        <div>
          <label
            className="block text-sm font-semibold text-[#2a2640]"
            htmlFor="connector-external-account-id"
          >
            External account ID
          </label>
          <p className="mt-1 text-xs text-[#6a6780]">
            Optional metadata used to distinguish multiple accounts from the
            same provider.
          </p>
          <input
            id="connector-external-account-id"
            type="text"
            value={state.external_account_id}
            onChange={(event) =>
              onChange({ external_account_id: event.target.value })
            }
            className="mt-1.5 w-full rounded-xl border border-[#d7d4e8] bg-white px-3 py-2.5 text-sm text-[#2a2640] shadow-sm focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/20 focus:outline-none"
            placeholder="jira-site-1"
          />
        </div>
      </div>

      <aside className="rounded-2xl border border-[#d7d4e8] bg-[#faf9fe] p-4">
        <h3 className="text-sm font-semibold text-[#2a2640]">
          Provider overview
        </h3>
        <p className="mt-1 text-sm text-[#68647b]">
          {provider.capabilities.notes ??
            "This provider is managed through the shared connector wizard."}
        </p>
        <div className="mt-3">
          <ProviderCapabilityBadges provider={provider} />
        </div>
        <div className="mt-4 rounded-xl bg-white p-3 text-sm text-[#4b4860]">
          <div className="font-semibold text-[#2a2640]">Auth model</div>
          <div className="mt-1 capitalize">
            {provider.capabilities.auth_type.replace(/_/g, " ")}
          </div>
        </div>
      </aside>
    </div>
  );
}

function ScopeStep({
  state,
  onChange,
  provider,
}: WizardStepProps<ConnectorSetupState> & { provider: ProviderSummary }) {
  const fields = provider.config_schema.properties ?? {};
  const required = new Set(provider.config_schema.required ?? []);

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr,0.9fr]">
      <div className="space-y-4">
        {Object.keys(fields).length === 0 && (
          <div className="rounded-2xl border border-dashed border-[#d7d4e8] bg-white p-4 text-sm text-[#6a6780]">
            This provider does not require additional setup fields.
          </div>
        )}

        {Object.entries(fields).map(([name, field]) => {
          const value = state.config_values[name];
          const error = validateConfigField(
            field,
            value ?? "",
            required.has(name),
          );
          const isBoolean = field.type === "boolean";
          const isArray = field.type === "array";
          const isTextArea = name === "jql_filter" || name === "cql_filter";

          return (
            <div key={name}>
              <label
                className="block text-sm font-semibold text-[#2a2640]"
                htmlFor={`connector-config-${name}`}
              >
                {fieldLabel(name, field)}
                {required.has(name) && (
                  <span className="ml-1 text-[#c2410c]">*</span>
                )}
              </label>
              {field.description && (
                <p className="mt-1 text-xs text-[#6a6780]">
                  {field.description}
                </p>
              )}
              {isBoolean ? (
                <label className="mt-2 inline-flex items-center gap-3 rounded-xl border border-[#d7d4e8] bg-white px-3 py-2.5">
                  <input
                    id={`connector-config-${name}`}
                    type="checkbox"
                    checked={Boolean(value)}
                    onChange={(event) =>
                      onChange({
                        config_values: {
                          ...state.config_values,
                          [name]: event.target.checked,
                        },
                      })
                    }
                    className="h-4 w-4 rounded border-[#bfb9d8] text-[#3525cd] focus:ring-[#3525cd]"
                  />
                  <span className="text-sm text-[#2a2640]">
                    {field.description ?? `Enable ${fieldLabel(name, field)}`}
                  </span>
                </label>
              ) : (
                <textarea
                  id={`connector-config-${name}`}
                  rows={isTextArea ? 4 : isArray ? 2 : 1}
                  value={typeof value === "string" ? value : ""}
                  onChange={(event) =>
                    onChange({
                      config_values: {
                        ...state.config_values,
                        [name]: event.target.value,
                      },
                    })
                  }
                  placeholder={fieldPlaceholder(name, field)}
                  className="mt-1.5 w-full rounded-xl border border-[#d7d4e8] bg-white px-3 py-2.5 text-sm text-[#2a2640] shadow-sm focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/20 focus:outline-none"
                />
              )}
              {isArray &&
                typeof value === "string" &&
                value.trim().length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {toStringArray(value).map((item) => (
                      <span
                        key={item}
                        className="rounded-full bg-[#ece8ff] px-2.5 py-1 text-xs font-semibold text-[#3525cd]"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                )}
              {error && <p className="mt-1 text-xs text-[#b42318]">{error}</p>}
            </div>
          );
        })}
      </div>

      <aside className="space-y-4 rounded-2xl border border-[#d7d4e8] bg-[#faf9fe] p-4">
        <h3 className="text-sm font-semibold text-[#2a2640]">
          Selected sync scope
        </h3>
        <div className="space-y-2">
          {configSummary(provider, state.config_values).length === 0 && (
            <p className="text-sm text-[#68647b]">
              No explicit source scope selected.
            </p>
          )}
          {configSummary(provider, state.config_values).map((item) => (
            <div
              key={item}
              className="rounded-xl bg-white px-3 py-2 text-sm text-[#4b4860]"
            >
              {item}
            </div>
          ))}
        </div>
        <div className="rounded-xl border border-[#ece8ff] bg-white p-3 text-sm text-[#4b4860]">
          Source selection is saved as connector metadata and reused by sync
          jobs.
        </div>
      </aside>
    </div>
  );
}

function ReviewStep({
  state,
  provider,
}: WizardStepProps<ConnectorSetupState> & { provider: ProviderSummary }) {
  const scope = configSummary(provider, state.config_values);

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr,0.9fr]">
      <div className="space-y-4">
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
            Connection name
          </div>
          <div className="mt-1 text-lg font-bold text-[#2a2640]">
            {state.display_name || "Untitled connection"}
          </div>
        </div>

        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="text-xs font-semibold tracking-[0.18em] text-[#6a6780] uppercase">
            Source scope
          </div>
          {scope.length === 0 ? (
            <div className="mt-2 text-sm text-[#68647b]">
              No explicit source filter selected.
            </div>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              {scope.map((item) => (
                <span
                  key={item}
                  className="rounded-full bg-[#ece8ff] px-3 py-1.5 text-xs font-semibold text-[#3525cd]"
                >
                  {item}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <aside className="rounded-2xl border border-[#d7d4e8] bg-[#faf9fe] p-4">
        <h3 className="text-sm font-semibold text-[#2a2640]">
          What happens next
        </h3>
        <p className="mt-1 text-sm text-[#68647b]">
          {provider.capabilities.auth_type === "oauth2"
            ? "We’ll start OAuth, then save the connection once the provider redirects back."
            : "We’ll save the connection directly using the configured provider fields."}
        </p>
        <div className="mt-4 rounded-xl bg-white p-3 text-sm text-[#4b4860]">
          Selected auth model:{" "}
          <span className="font-semibold capitalize">
            {provider.capabilities.auth_type.replace(/_/g, " ")}
          </span>
        </div>
      </aside>
    </div>
  );
}

type OAuthScope = { scope: string; required: boolean; description: string };

const JIRA_SCOPES: OAuthScope[] = [
  {
    scope: "read:jira-work",
    required: true,
    description: "Read issues, comments, and attachments",
  },
  {
    scope: "read:jira-user",
    required: false,
    description: "Read user and group information",
  },
  {
    scope: "offline_access",
    required: false,
    description: "Refresh access tokens without re-authentication",
  },
];

const CONFLUENCE_SCOPES: OAuthScope[] = [
  {
    scope: "read:confluence-content.all",
    required: true,
    description: "Read pages, blog posts, and attachments",
  },
  {
    scope: "read:confluence-space.summary",
    required: false,
    description: "List accessible spaces",
  },
  {
    scope: "offline_access",
    required: false,
    description: "Refresh access tokens without re-authentication",
  },
];

function ConfluenceSetupGuide() {
  const [open, setOpen] = useState(true);
  let callbackUrl = "{API_BASE_URL}/connectors/oauth/callback";
  try {
    const apiUrl = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
    callbackUrl = `${apiUrl}/connectors/oauth/callback`;
  } catch {
    // runtime config unavailable during SSR
  }

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 overflow-hidden">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-amber-100/60 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-amber-700 text-[20px]">build_circle</span>
          <div>
            <div className="text-sm font-semibold text-amber-900">
              Atlassian app setup required
            </div>
            <div className="text-xs text-amber-700">
              One-time prerequisite — create an OAuth app before connecting
            </div>
          </div>
        </div>
        <span
          className={`material-symbols-outlined text-amber-600 text-[20px] transition-transform duration-200 shrink-0 ${open ? "rotate-180" : ""}`}
        >
          expand_more
        </span>
      </button>

      {open && (
        <div className="border-t border-amber-200 px-5 pb-5 pt-4 space-y-5">
          <p className="text-sm text-amber-800 leading-relaxed">
            Rudix connects to Confluence via an OAuth 2.0 (3LO) app you own on the Atlassian
            Developer Console. Follow these steps once, then come back here to connect.
          </p>

          <ol className="space-y-4">
            {/* Step 1 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                1
              </span>
              <div className="text-sm text-amber-900">
                <span className="font-semibold">Create an app</span> — open{" "}
                <a
                  href="https://developer.atlassian.com/console/myapps/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 hover:text-amber-700"
                >
                  developer.atlassian.com/console/myapps
                </a>
                , click <strong>Create</strong> → <strong>OAuth 2.0 integration</strong> and give
                it a name (e.g. <em>Rudix</em>).
              </div>
            </li>

            {/* Step 2 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                2
              </span>
              <div className="text-sm text-amber-900">
                <span className="font-semibold">Enable Confluence API</span> — under{" "}
                <strong>APIs and features</strong>, click <strong>Add</strong> next to{" "}
                <strong>Confluence API</strong>.
              </div>
            </li>

            {/* Step 3 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                3
              </span>
              <div className="flex-1 space-y-2 text-sm text-amber-900">
                <div>
                  <span className="font-semibold">Add the callback URL</span> — under{" "}
                  <strong>Authorization</strong>, paste this exact URL:
                </div>
                <div className="flex items-center gap-2 rounded-xl border border-amber-300 bg-white px-3 py-2">
                  <span className="flex-1 break-all font-mono text-xs text-[#2a2640]">
                    {callbackUrl}
                  </span>
                  <button
                    type="button"
                    title="Copy callback URL"
                    onClick={() => navigator.clipboard.writeText(callbackUrl)}
                    className="shrink-0 rounded-lg p-1.5 text-amber-600 hover:bg-amber-100 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[16px]">content_copy</span>
                  </button>
                </div>
              </div>
            </li>

            {/* Step 4 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                4
              </span>
              <div className="flex-1 space-y-2 text-sm text-amber-900">
                <div>
                  <span className="font-semibold">Grant permissions</span> — under{" "}
                  <strong>Confluence API → Permissions</strong>, add these OAuth scopes:
                </div>
                <div className="rounded-xl border border-amber-300 bg-white divide-y divide-amber-100 overflow-hidden">
                  {CONFLUENCE_SCOPES.map(({ scope, required, description }) => (
                    <div key={scope} className="flex items-center gap-3 px-3 py-2.5">
                      <span className="font-mono text-xs text-[#2a2640] flex-1">{scope}</span>
                      <span className="text-xs text-[#6a6780] hidden sm:block">{description}</span>
                      {required ? (
                        <span className="shrink-0 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold text-rose-700 uppercase tracking-wide">
                          Required
                        </span>
                      ) : (
                        <span className="shrink-0 rounded-full bg-[#ece8ff] px-2 py-0.5 text-[10px] font-bold text-[#3525cd] uppercase tracking-wide">
                          Recommended
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </li>

            {/* Step 5 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                5
              </span>
              <div className="flex-1 space-y-2 text-sm text-amber-900">
                <div>
                  <span className="font-semibold">Add credentials to your deployment</span> — copy
                  the <strong>Client ID</strong> and <strong>Client Secret</strong> from the app
                  settings page, then set the backend environment variable:
                </div>
                <div className="rounded-xl border border-amber-300 bg-white px-3 py-2.5 font-mono text-xs text-[#2a2640] leading-relaxed">
                  <div>CONNECTOR_OAUTH_CLIENTS=</div>
                  <div className="pl-2 text-[#464555]">
                    {'[{"provider_key":"confluence",'}
                  </div>
                  <div className="pl-4 text-[#464555]">
                    {'"client_id":"<your-client-id>",'}
                  </div>
                  <div className="pl-4 text-[#464555]">
                    {'"client_secret":"<your-client-secret>"}]'}
                  </div>
                </div>
                <p className="text-xs text-amber-700">
                  To also connect Jira, append a second entry with{" "}
                  <span className="font-mono">provider_key&nbsp;=&nbsp;&quot;jira&quot;</span>{" "}
                  to the same array. Both can point to the same Atlassian app credentials.
                </p>
              </div>
            </li>
          </ol>

          <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-white p-3 text-xs text-amber-800">
            <span className="material-symbols-outlined text-[16px] shrink-0 mt-0.5 text-amber-600">
              lock
            </span>
            <span>
              Rudix requests read-only scopes only. It cannot create, edit, or delete any Confluence
              content.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function JiraSetupGuide() {
  const [open, setOpen] = useState(true);

  let callbackUrl = "{API_BASE_URL}/connectors/oauth/callback";
  try {
    const apiUrl = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
    callbackUrl = `${apiUrl}/connectors/oauth/callback`;
  } catch {
    // runtime config unavailable during SSR
  }

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 overflow-hidden">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-amber-100/60 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-amber-700 text-[20px]">build_circle</span>
          <div>
            <div className="text-sm font-semibold text-amber-900">
              Atlassian app setup required
            </div>
            <div className="text-xs text-amber-700">
              One-time prerequisite — create an OAuth app before connecting
            </div>
          </div>
        </div>
        <span
          className={`material-symbols-outlined text-amber-600 text-[20px] transition-transform duration-200 shrink-0 ${open ? "rotate-180" : ""}`}
        >
          expand_more
        </span>
      </button>

      {open && (
        <div className="border-t border-amber-200 px-5 pb-5 pt-4 space-y-5">
          <p className="text-sm text-amber-800 leading-relaxed">
            Rudix connects to Jira via an OAuth 2.0 (3LO) app you own on the Atlassian Developer
            Console. Follow these steps once, then come back here to connect.
          </p>

          <ol className="space-y-4">
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                1
              </span>
              <div className="text-sm text-amber-900">
                <span className="font-semibold">Create an app</span> — open{" "}
                <a
                  href="https://developer.atlassian.com/console/myapps/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 hover:text-amber-700"
                >
                  developer.atlassian.com/console/myapps
                </a>
                , click <strong>Create</strong> → <strong>OAuth 2.0 integration</strong> and give
                it a name (e.g. <em>Rudix</em>).
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                2
              </span>
              <div className="text-sm text-amber-900">
                <span className="font-semibold">Enable Jira API</span> — under{" "}
                <strong>APIs and features</strong>, click <strong>Add</strong> next to{" "}
                <strong>Jira API</strong>.
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                3
              </span>
              <div className="flex-1 space-y-2 text-sm text-amber-900">
                <div>
                  <span className="font-semibold">Add the callback URL</span> — under{" "}
                  <strong>Authorization</strong>, paste this exact URL:
                </div>
                <div className="flex items-center gap-2 rounded-xl border border-amber-300 bg-white px-3 py-2">
                  <span className="flex-1 break-all font-mono text-xs text-[#2a2640]">
                    {callbackUrl}
                  </span>
                  <button
                    type="button"
                    title="Copy callback URL"
                    onClick={() => navigator.clipboard.writeText(callbackUrl)}
                    className="shrink-0 rounded-lg p-1.5 text-amber-600 hover:bg-amber-100 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[16px]">content_copy</span>
                  </button>
                </div>
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                4
              </span>
              <div className="flex-1 space-y-2 text-sm text-amber-900">
                <div>
                  <span className="font-semibold">Grant permissions</span> — under{" "}
                  <strong>Jira API → Permissions</strong>, add these OAuth scopes:
                </div>
                <div className="rounded-xl border border-amber-300 bg-white divide-y divide-amber-100 overflow-hidden">
                  {JIRA_SCOPES.map(({ scope, required, description }) => (
                    <div key={scope} className="flex items-center gap-3 px-3 py-2.5">
                      <span className="font-mono text-xs text-[#2a2640] flex-1">{scope}</span>
                      <span className="text-xs text-[#6a6780] hidden sm:block">{description}</span>
                      {required ? (
                        <span className="shrink-0 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold text-rose-700 uppercase tracking-wide">
                          Required
                        </span>
                      ) : (
                        <span className="shrink-0 rounded-full bg-[#ece8ff] px-2 py-0.5 text-[10px] font-bold text-[#3525cd] uppercase tracking-wide">
                          Recommended
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
                5
              </span>
              <div className="flex-1 space-y-2 text-sm text-amber-900">
                <div>
                  <span className="font-semibold">Add credentials to your deployment</span> — copy
                  the <strong>Client ID</strong> and <strong>Client Secret</strong> from the app
                  settings page, then set the backend environment variable:
                </div>
                <div className="rounded-xl border border-amber-300 bg-white px-3 py-2.5 font-mono text-xs text-[#2a2640] leading-relaxed">
                  <div>CONNECTOR_OAUTH_CLIENTS=</div>
                  <div className="pl-2 text-[#464555]">{'[{"provider_key":"jira",'}</div>
                  <div className="pl-4 text-[#464555]">{'"client_id":"<your-client-id>",'}</div>
                  <div className="pl-4 text-[#464555]">{'"client_secret":"<your-client-secret>"}]'}</div>
                </div>
                <p className="text-xs text-amber-700">
                  To also connect Confluence, append a second entry with{" "}
                  <span className="font-mono">provider_key&nbsp;=&nbsp;&quot;confluence&quot;</span>{" "}
                  to the same array. Both can point to the same Atlassian app credentials.
                </p>
              </div>
            </li>
          </ol>

          <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-white p-3 text-xs text-amber-800">
            <span className="material-symbols-outlined text-[16px] shrink-0 mt-0.5 text-amber-600">
              lock
            </span>
            <span>
              Rudix requests read-only scopes only. It cannot create, edit, or delete any Jira
              issues.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function WizardShell({ provider }: { provider: ProviderSummary }) {
  const router = useRouter();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const initialState = useMemo<ConnectorSetupState>(
    () => ({
      display_name: provider.display_name,
      external_account_id: "",
      config_values: buildConfigFieldState(provider.config_schema),
    }),
    [provider],
  );

  async function handleComplete(state: ConnectorSetupState): Promise<void> {
    setSubmitting(true);
    setErrorMessage(null);
    const config = buildProviderConfig(
      provider.config_schema,
      state.config_values,
    );
    try {
      if (provider.capabilities.auth_type === "oauth2") {
        const apiUrl = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
        const result = await beginConnectorOAuthConnect({
          provider_key: provider.key,
          redirect_uri: `${apiUrl}/connectors/oauth/callback`,
          display_name: state.display_name.trim() || provider.display_name,
          external_account_id: state.external_account_id.trim() || null,
          config,
        });
        window.location.assign(result.authorization_url);
        return;
      }

      const created = await createConnectorConnection({
        provider_key: provider.key,
        display_name: state.display_name.trim() || provider.display_name,
        external_account_id: state.external_account_id.trim() || null,
        config,
      });
      router.push(`/connectors/${created.id}`);
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  const steps: ConnectorWizardConfig<ConnectorSetupState>["steps"] = [
    {
      key: "basics",
      label: "Basics",
      component: (props: WizardStepProps<ConnectorSetupState>) => (
        <BasicStep {...props} provider={provider} />
      ),
      canProceed: (state: ConnectorSetupState) =>
        state.display_name.trim().length > 0,
    },
    {
      key: "scope",
      label: "Scope",
      component: (props: WizardStepProps<ConnectorSetupState>) => (
        <ScopeStep {...props} provider={provider} />
      ),
      canProceed: (state: ConnectorSetupState) =>
        Object.entries(provider.config_schema.properties ?? {}).every(
          ([name, field]) => {
            const required = (provider.config_schema.required ?? []).includes(
              name,
            );
            return !validateConfigField(
              field,
              state.config_values[name] ?? "",
              required,
            );
          },
        ),
    },
    {
      key: "review",
      label: "Review",
      component: (props: WizardStepProps<ConnectorSetupState>) => (
        <ReviewStep {...props} provider={provider} />
      ),
    },
  ];

  return (
    <div className="space-y-4">
      {errorMessage && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">
          {errorMessage}
        </div>
      )}
      <ConnectorWizard
        config={{
          providerKey: provider.key,
          displayName: provider.display_name,
          initialState,
          steps,
          onComplete: handleComplete,
          onCancel: () => router.push("/connectors"),
        }}
      />
      {submitting && (
        <div className="text-sm text-[#6a6780]">
          Submitting connection details…
        </div>
      )}
    </div>
  );
}

function ProviderLoader({ providerKey }: Props) {
  const router = useRouter();
  const providerQuery = useQuery({
    queryKey: queryKeys.connectorProvider(providerKey),
    queryFn: () => getProvider(providerKey),
  });

  if (providerQuery.isLoading) {
    return (
      <div className="rounded-2xl border border-dashed border-[#d7d4e8] bg-white p-6 text-sm text-[#68647b]">
        Loading provider metadata…
      </div>
    );
  }

  if (providerQuery.isError || !providerQuery.data) {
    const error = providerQuery.error as ApiClientError | null;
    return (
      <div className="space-y-4">
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-900">
          <div className="font-semibold">Unable to load provider</div>
          <p className="mt-1">
            {error
              ? getApiErrorMessage(error)
              : "Provider metadata is unavailable."}
          </p>
        </div>
        <button
          type="button"
          onClick={() => router.push("/connectors")}
          className="rounded-xl border border-[#d7d4e8] px-4 py-2 text-sm font-semibold text-[#3525cd]"
        >
          Back to connectors
        </button>
      </div>
    );
  }

  const provider = providerQuery.data;
  const authLabel = provider.capabilities.auth_type.replace(/_/g, " ");
  const description =
    provider.capabilities.notes ??
    "Use the guided setup to connect the provider and capture source scope metadata.";

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          Connector setup wizard
        </p>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              Connect {provider.display_name}
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">{description}</p>
          </div>
          <div className="rounded-xl bg-[#faf9fe] px-4 py-3 text-sm text-[#4b4860]">
            <div className="font-semibold text-[#2a2640]">Auth type</div>
            <div className="capitalize">{authLabel}</div>
          </div>
        </div>
        <div className="mt-4">
          <ProviderCapabilityBadges provider={provider} />
        </div>
      </header>

      {provider.key === "jira" && <JiraSetupGuide />}
      {provider.key === "confluence" && <ConfluenceSetupGuide />}

      <WizardShell provider={provider} />
    </section>
  );
}

export function ConnectorSetupPage({ providerKey }: Props) {
  const client = useMemo(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false } },
      }),
    [],
  );

  return (
    <QueryClientProvider client={client}>
      <ProviderLoader providerKey={providerKey} />
    </QueryClientProvider>
  );
}
