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
  confirmed: boolean;
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
  providerKey?: string,
): string {
  if (field.format === "uri") {
    return providerKey === "microsoft-sharepoint-onedrive"
      ? "https://contoso.sharepoint.com"
      : "https://example.atlassian.net";
  }
  if (field.type === "array") {
    return `${name.replace(/_/g, " ")} separated by commas`;
  }
  if (field.type === "boolean") {
    return "true";
  }
  if (name === "external_account_id") {
    return providerKey === "microsoft-sharepoint-onedrive"
      ? "contoso.onmicrosoft.com or user@contoso.com"
      : "acme.atlassian.net";
  }
  return name.replace(/_/g, " ");
}

function externalAccountFieldLabel(providerKey: string): string {
  if (providerKey === "microsoft-sharepoint-onedrive") {
    return "Tenant / account ID";
  }
  return "External account ID";
}

function externalAccountHelperText(providerKey: string): string {
  if (providerKey === "microsoft-sharepoint-onedrive") {
    return "Optional metadata used to distinguish multiple Microsoft 365 tenants or accounts.";
  }
  return "Optional metadata used to distinguish multiple accounts from the same provider.";
}

function externalAccountPlaceholder(providerKey: string): string {
  if (providerKey === "microsoft-sharepoint-onedrive") {
    return "contoso.onmicrosoft.com or user@contoso.com";
  }
  return "acme.atlassian.net";
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
            {externalAccountFieldLabel(provider.key)}
          </label>
          <p className="mt-1 text-xs text-[#6a6780]">
            {externalAccountHelperText(provider.key)}
          </p>
          <input
            id="connector-external-account-id"
            type="text"
            value={state.external_account_id}
            onChange={(event) =>
              onChange({ external_account_id: event.target.value })
            }
            className="mt-1.5 w-full rounded-xl border border-[#d7d4e8] bg-white px-3 py-2.5 text-sm text-[#2a2640] shadow-sm focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/20 focus:outline-none"
            placeholder={externalAccountPlaceholder(provider.key)}
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

// ── Scope-risk analysis (mirrors backend logic for instant feedback) ──────────

const WRITE_SCOPE_KEYWORDS = ["write", "delete", "modify", "create", "update"];
const ADMIN_SCOPE_KEYWORDS = ["admin"];
const ORG_WIDE_SCOPE_SUFFIXES = [".all", ":all", "_all"];

const PROVIDER_ORG_WIDE_SCOPES: Record<string, string[]> = {
  google_drive: [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
  ],
  "microsoft-sharepoint-onedrive": ["Sites.Read.All", "Files.Read.All"],
};

type ScopeRisk = "write_permission" | "admin_scope" | "org_wide_access" | "broad_read";

function detectScopeRisks(
  scopes: string[],
  providerKey: string,
  configValues: Record<string, string | boolean>,
): { code: ScopeRisk; message: string; scope: string }[] {
  const warnings: { code: ScopeRisk; message: string; scope: string }[] = [];

  const hasFilter = ["folder_ids", "site_ids", "drive_ids", "space_keys", "project_keys"].some(
    (k) => {
      const v = configValues[k];
      return typeof v === "string" ? v.trim().length > 0 : Boolean(v);
    },
  );

  for (const scope of scopes) {
    const lower = scope.toLowerCase();
    if (WRITE_SCOPE_KEYWORDS.some((kw) => lower.includes(kw))) {
      warnings.push({
        code: "write_permission",
        message: `'${scope}' grants write or delete access — Rudix only needs read-only scopes.`,
        scope,
      });
      continue;
    }
    if (ADMIN_SCOPE_KEYWORDS.some((kw) => lower.includes(kw))) {
      warnings.push({
        code: "admin_scope",
        message: `'${scope}' grants admin-level access beyond what indexing requires.`,
        scope,
      });
      continue;
    }
    const providerOrgWide = PROVIDER_ORG_WIDE_SCOPES[providerKey] ?? [];
    if (providerOrgWide.includes(scope) && !hasFilter) {
      warnings.push({
        code: "org_wide_access",
        message: `'${scope}' grants access to your entire organisation with no source filter. Consider restricting to specific folders or sites.`,
        scope,
      });
      continue;
    }
    if (ORG_WIDE_SCOPE_SUFFIXES.some((sfx) => lower.endsWith(sfx))) {
      warnings.push({
        code: "broad_read",
        message: `'${scope}' appears to grant broad read access — confirm this is the minimum required scope.`,
        scope,
      });
    }
  }
  return warnings;
}

const SCOPE_RISK_ICONS: Record<ScopeRisk, string> = {
  write_permission: "edit_off",
  admin_scope: "admin_panel_settings",
  org_wide_access: "public",
  broad_read: "visibility",
};

type PermissionReviewState = { confirmed: boolean };

function PermissionReviewStep({
  state,
  onChange,
  provider,
  scopeValues,
}: WizardStepProps<ConnectorSetupState> & {
  provider: ProviderSummary;
  scopeValues: Record<string, string | boolean>;
}) {
  const requestedScopes = useMemo(() => {
    if (provider.key === "confluence") {
      return CONFLUENCE_SCOPES.map((s) => s.scope);
    }
    if (provider.key === "google_drive") {
      return GOOGLE_DRIVE_SCOPES.map((s) => s.scope);
    }
    if (provider.key === "microsoft-sharepoint-onedrive") {
      return MICROSOFT_SHAREPOINT_ONEDRIVE_SCOPES.map((s) => s.scope);
    }
    return [];
  }, [provider.key]);

  const warnings = useMemo(
    () => detectScopeRisks(requestedScopes, provider.key, scopeValues),
    [requestedScopes, provider.key, scopeValues],
  );

  const isBroad = warnings.length > 0;

  const confirmed = (state as unknown as PermissionReviewState & ConnectorSetupState).confirmed ?? false;

  return (
    <div className="space-y-5">
      {isBroad && (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <span className="material-symbols-outlined mt-0.5 shrink-0 text-[22px] text-amber-600">
            warning
          </span>
          <div>
            <div className="text-sm font-semibold text-amber-900">
              Broad permission scope detected
            </div>
            <p className="mt-0.5 text-sm text-amber-800">
              The selected configuration grants broad access. Review each warning
              below and narrow the scope where possible before confirming.
            </p>
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4 space-y-3">
        <h3 className="text-sm font-semibold text-[#2a2640]">Requested OAuth scopes</h3>
        {requestedScopes.length === 0 ? (
          <p className="text-sm text-[#68647b]">
            This provider uses API token authentication — no OAuth scopes are requested.
          </p>
        ) : (
          <div className="divide-y divide-[#f0eef9] overflow-hidden rounded-xl border border-[#d7d4e8]">
            {requestedScopes.map((scope) => {
              const warning = warnings.find((w) => w.scope === scope);
              return (
                <div
                  key={scope}
                  className={`flex items-start gap-3 px-3 py-2.5 ${warning ? "bg-amber-50/60" : "bg-white"}`}
                >
                  <span
                    className={`material-symbols-outlined mt-0.5 shrink-0 text-[18px] ${
                      warning ? "text-amber-500" : "text-emerald-500"
                    }`}
                  >
                    {warning ? SCOPE_RISK_ICONS[warning.code] : "check_circle"}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-xs break-all text-[#2a2640]">{scope}</div>
                    {warning && (
                      <div className="mt-0.5 text-xs text-amber-700">{warning.message}</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#2a2640]">
            <span className="material-symbols-outlined text-[18px] text-[#3525cd]">sync_alt</span>
            Sync direction
          </div>
          <p className="mt-1.5 text-sm text-[#68647b]">Read-only. Rudix never writes, edits, or deletes content in the connected source.</p>
        </div>
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#2a2640]">
            <span className="material-symbols-outlined text-[18px] text-[#3525cd]">database</span>
            Retention
          </div>
          <p className="mt-1.5 text-sm text-[#68647b]">Indexed content is stored until the connector is removed or a document is deleted at the source.</p>
        </div>
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#2a2640]">
            <span className="material-symbols-outlined text-[18px] text-[#3525cd]">group</span>
            Access
          </div>
          <p className="mt-1.5 text-sm text-[#68647b]">Indexed results are available to all members of your organisation via the assigned collection.</p>
        </div>
      </div>

      <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-[#d7d4e8] bg-white p-4 transition-colors hover:border-[#3525cd]/40">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) =>
            onChange({ ...(state as object), confirmed: e.target.checked } as ConnectorSetupState)
          }
          className="mt-0.5 h-4 w-4 shrink-0 rounded border-[#bfb9d8] text-[#3525cd] focus:ring-[#3525cd]"
          data-testid="permission-review-confirm"
        />
        <div>
          <div className="text-sm font-semibold text-[#2a2640]">
            I confirm I have reviewed the requested permissions
          </div>
          <p className="mt-0.5 text-xs text-[#6a6780]">
            {isBroad
              ? "I understand this connector requests broad access and accept responsibility for the scope configured above."
              : "I understand what data this connector will access and confirm it is appropriate for indexing."}
          </p>
        </div>
      </label>
    </div>
  );
}

type OAuthScope = { scope: string; required: boolean; description: string };

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
  const [open, setOpen] = useState(false);
  let callbackUrl = "{API_BASE_URL}/connectors/oauth/callback";
  try {
    const apiUrl = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
    callbackUrl = `${apiUrl}/connectors/oauth/callback`;
  } catch {
    // runtime config unavailable during SSR
  }

  return (
    <div className="w-full max-w-4xl overflow-hidden rounded-2xl border border-blue-200 bg-blue-50">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-blue-100/60"
      >
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-[20px] text-blue-700">
            build_circle
          </span>
          <div>
            <div className="text-sm font-semibold text-blue-900">
              Atlassian app setup required
            </div>
            <div className="text-xs text-blue-700">
              One-time prerequisite — create an OAuth app before connecting
            </div>
          </div>
        </div>
        <span
          className={`material-symbols-outlined shrink-0 text-[20px] text-blue-600 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          expand_more
        </span>
      </button>

      {open && (
        <div className="space-y-5 border-t border-blue-200 px-5 pt-4 pb-5">
          <p className="text-sm leading-relaxed text-blue-800">
            Rudix connects to Confluence via an OAuth 2.0 (3LO) app you own on
            the Atlassian Developer Console. Follow these steps once, then come
            back here to connect.
          </p>

          <ol className="space-y-4">
            {/* Step 1 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                1
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">Create an app</span> — open{" "}
                <a
                  href="https://developer.atlassian.com/console/myapps/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 hover:text-blue-700"
                >
                  developer.atlassian.com/console/myapps
                </a>
                , click <strong>Create</strong> →{" "}
                <strong>OAuth 2.0 integration</strong> and give it a name (e.g.{" "}
                <em>Rudix</em>).
              </div>
            </li>

            {/* Step 2 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                2
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">Enable Confluence API</span> —
                under <strong>APIs and features</strong>, click{" "}
                <strong>Add</strong> next to <strong>Confluence API</strong>.
              </div>
            </li>

            {/* Step 3 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                3
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">Add the callback URL</span> —
                  under <strong>Authorization</strong>, paste this exact URL:
                </div>
                <div className="flex items-center gap-2 rounded-xl border border-blue-300 bg-white px-3 py-2">
                  <span className="flex-1 font-mono text-xs break-all text-[#2a2640]">
                    {callbackUrl}
                  </span>
                  <button
                    type="button"
                    title="Copy callback URL"
                    onClick={() => navigator.clipboard.writeText(callbackUrl)}
                    className="shrink-0 rounded-lg p-1.5 text-blue-600 transition-colors hover:bg-blue-100"
                  >
                    <span className="material-symbols-outlined text-[16px]">
                      content_copy
                    </span>
                  </button>
                </div>
              </div>
            </li>

            {/* Step 4 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                4
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">Grant permissions</span> —
                  under <strong>Confluence API → Permissions</strong>, add these
                  OAuth scopes:
                </div>
                <div className="divide-y divide-blue-100 overflow-hidden rounded-xl border border-blue-300 bg-white">
                  {CONFLUENCE_SCOPES.map(({ scope, required, description }) => (
                    <div
                      key={scope}
                      className="flex items-center gap-3 px-3 py-2.5"
                    >
                      <span className="flex-1 font-mono text-xs text-[#2a2640]">
                        {scope}
                      </span>
                      <span className="hidden text-xs text-[#6a6780] sm:block">
                        {description}
                      </span>
                      {required ? (
                        <span className="shrink-0 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold tracking-wide text-rose-700 uppercase">
                          Required
                        </span>
                      ) : (
                        <span className="shrink-0 rounded-full bg-[#ece8ff] px-2 py-0.5 text-[10px] font-bold tracking-wide text-[#3525cd] uppercase">
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
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                5
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">
                    Add credentials to your deployment
                  </span>{" "}
                  — copy the <strong>Client ID</strong> and{" "}
                  <strong>Client Secret</strong> from the app settings page,
                  then set the backend environment variable:
                </div>
                <div className="rounded-xl border border-blue-300 bg-white px-3 py-2.5 font-mono text-xs leading-relaxed text-[#2a2640]">
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
                <p className="text-xs text-blue-700">
                  The same Atlassian app credentials can be reused for other
                  compatible providers by adding another entry to the array.
                </p>
              </div>
            </li>
          </ol>

          <div className="flex items-start gap-2 rounded-xl border border-blue-200 bg-white p-3 text-xs text-blue-800">
            <span className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-blue-600">
              lock
            </span>
            <span>
              Rudix requests read-only scopes only. It cannot create, edit, or
              delete any Confluence content.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

const GOOGLE_DRIVE_SCOPES: OAuthScope[] = [
  {
    scope: "https://www.googleapis.com/auth/drive.readonly",
    required: true,
    description: "Read files, folders, and metadata",
  },
  {
    scope: "https://www.googleapis.com/auth/drive.metadata.readonly",
    required: false,
    description: "Read file metadata without downloading content",
  },
];

const MICROSOFT_SHAREPOINT_ONEDRIVE_SCOPES: OAuthScope[] = [
  {
    scope: "offline_access",
    required: true,
    description: "Refresh access without reauthorizing the app",
  },
  {
    scope: "Files.Read.All",
    required: true,
    description: "Read OneDrive files and document library content",
  },
  {
    scope: "Sites.Read.All",
    required: true,
    description: "Discover SharePoint sites and libraries",
  },
  {
    scope: "User.Read",
    required: false,
    description: "Validate the signed-in Microsoft account",
  },
];

function GoogleDriveSetupGuide() {
  const [open, setOpen] = useState(false);
  let callbackUrl = "{API_BASE_URL}/connectors/oauth/callback";
  try {
    const apiUrl = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
    callbackUrl = `${apiUrl}/connectors/oauth/callback`;
  } catch {
    // runtime config unavailable during SSR
  }

  return (
    <div className="w-full max-w-4xl overflow-hidden rounded-2xl border border-blue-200 bg-blue-50">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-blue-100/60"
      >
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-[20px] text-blue-700">
            build_circle
          </span>
          <div>
            <div className="text-sm font-semibold text-blue-900">
              Google Cloud project setup required
            </div>
            <div className="text-xs text-blue-700">
              One-time prerequisite — create an OAuth app before connecting
            </div>
          </div>
        </div>
        <span
          className={`material-symbols-outlined shrink-0 text-[20px] text-blue-600 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          expand_more
        </span>
      </button>

      {open && (
        <div className="space-y-5 border-t border-blue-200 px-5 pt-4 pb-5">
          <p className="text-sm leading-relaxed text-blue-800">
            Rudix connects to Google Drive via an OAuth 2.0 app you own in the
            Google Cloud Console. Follow these steps once, then come back here
            to connect.
          </p>

          <ol className="space-y-4">
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                1
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">Create a project</span> — open{" "}
                <a
                  href="https://console.cloud.google.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 hover:text-blue-700"
                >
                  console.cloud.google.com
                </a>
                , click the project selector at the top and choose{" "}
                <strong>New Project</strong>.
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                2
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">
                  Enable the Google Drive API
                </span>{" "}
                — navigate to <strong>APIs &amp; Services → Library</strong>,
                search for <strong>Google Drive API</strong>, and click{" "}
                <strong>Enable</strong>.
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                3
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">
                  Configure the OAuth consent screen
                </span>{" "}
                — under{" "}
                <strong>APIs &amp; Services → OAuth consent screen</strong>,
                select <strong>Internal</strong> (for a Workspace org) or{" "}
                <strong>External</strong>, fill in the app name and support
                email, then save.
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                4
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">
                    Create OAuth credentials
                  </span>{" "}
                  — under <strong>APIs &amp; Services → Credentials</strong>,
                  click <strong>Create Credentials → OAuth client ID</strong>.
                  Choose <strong>Web application</strong> and add this as an{" "}
                  <strong>Authorized redirect URI</strong>:
                </div>
                <div className="flex items-center gap-2 rounded-xl border border-blue-300 bg-white px-3 py-2">
                  <span className="flex-1 font-mono text-xs break-all text-[#2a2640]">
                    {callbackUrl}
                  </span>
                  <button
                    type="button"
                    title="Copy callback URL"
                    onClick={() => navigator.clipboard.writeText(callbackUrl)}
                    className="shrink-0 rounded-lg p-1.5 text-blue-600 transition-colors hover:bg-blue-100"
                  >
                    <span className="material-symbols-outlined text-[16px]">
                      content_copy
                    </span>
                  </button>
                </div>
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                5
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">
                    Add required OAuth scopes
                  </span>{" "}
                  — on the OAuth consent screen, click{" "}
                  <strong>Add or remove scopes</strong> and add:
                </div>
                <div className="divide-y divide-blue-100 overflow-hidden rounded-xl border border-blue-300 bg-white">
                  {GOOGLE_DRIVE_SCOPES.map(
                    ({ scope, required, description }) => (
                      <div
                        key={scope}
                        className="flex items-center gap-3 px-3 py-2.5"
                      >
                        <span className="flex-1 font-mono text-xs break-all text-[#2a2640]">
                          {scope}
                        </span>
                        <span className="hidden shrink-0 text-xs text-[#6a6780] sm:block">
                          {description}
                        </span>
                        {required ? (
                          <span className="shrink-0 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold tracking-wide text-rose-700 uppercase">
                            Required
                          </span>
                        ) : (
                          <span className="shrink-0 rounded-full bg-[#ece8ff] px-2 py-0.5 text-[10px] font-bold tracking-wide text-[#3525cd] uppercase">
                            Recommended
                          </span>
                        )}
                      </div>
                    ),
                  )}
                </div>
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                6
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">
                    Add credentials to your deployment
                  </span>{" "}
                  — copy the <strong>Client ID</strong> and{" "}
                  <strong>Client Secret</strong> from the credentials page, then
                  set the backend environment variable:
                </div>
                <div className="rounded-xl border border-blue-300 bg-white px-3 py-2.5 font-mono text-xs leading-relaxed text-[#2a2640]">
                  <div>CONNECTOR_OAUTH_CLIENTS=</div>
                  <div className="pl-2 text-[#464555]">
                    {'[{"provider_key":"google_drive",'}
                  </div>
                  <div className="pl-4 text-[#464555]">
                    {'"client_id":"<your-client-id>",'}
                  </div>
                  <div className="pl-4 text-[#464555]">
                    {'"client_secret":"<your-client-secret>"}]'}
                  </div>
                </div>
              </div>
            </li>
          </ol>

          <div className="flex items-start gap-2 rounded-xl border border-blue-200 bg-white p-3 text-xs text-blue-800">
            <span className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-blue-600">
              lock
            </span>
            <span>
              Rudix requests read-only scopes only. It cannot create, edit, or
              delete any Drive files.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function NotionSetupGuide() {
  const [open, setOpen] = useState(false);
  let callbackUrl = "{API_BASE_URL}/connectors/oauth/callback";
  try {
    const apiUrl = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
    callbackUrl = `${apiUrl}/connectors/oauth/callback`;
  } catch {
    // runtime config unavailable during SSR
  }

  return (
    <div className="w-full max-w-4xl overflow-hidden rounded-2xl border border-blue-200 bg-blue-50">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-blue-100/60"
      >
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-[20px] text-blue-700">
            build_circle
          </span>
          <div>
            <div className="text-sm font-semibold text-blue-900">
              Notion integration setup required
            </div>
            <div className="text-xs text-blue-700">
              One-time prerequisite — create a public OAuth integration before
              connecting
            </div>
          </div>
        </div>
        <span
          className={`material-symbols-outlined shrink-0 text-[20px] text-blue-600 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          expand_more
        </span>
      </button>

      {open && (
        <div className="space-y-5 border-t border-blue-200 px-5 pt-4 pb-5">
          <p className="text-sm leading-relaxed text-blue-800">
            Rudix connects to Notion via a public OAuth 2.0 integration you own
            on the Notion developer portal. Follow these steps once, then come
            back here to connect.
          </p>

          <ol className="space-y-4">
            {/* Step 1 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                1
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">Create an integration</span> —
                open{" "}
                <a
                  href="https://www.notion.so/my-integrations"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 hover:text-blue-700"
                >
                  notion.so/my-integrations
                </a>
                , click <strong>+ New integration</strong>, give it a name (e.g.{" "}
                <em>Rudix</em>), select your workspace, and set the{" "}
                <strong>Integration type</strong> to <strong>Public</strong>.
              </div>
            </li>

            {/* Step 2 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                2
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">Add the redirect URI</span> —
                  under <strong>OAuth Domain &amp; URIs</strong>, add this exact
                  URL to <strong>Redirect URIs</strong>:
                </div>
                <div className="flex items-center gap-2 rounded-xl border border-blue-300 bg-white px-3 py-2">
                  <span className="flex-1 font-mono text-xs break-all text-[#2a2640]">
                    {callbackUrl}
                  </span>
                  <button
                    type="button"
                    title="Copy callback URL"
                    onClick={() => navigator.clipboard.writeText(callbackUrl)}
                    className="shrink-0 rounded-lg p-1.5 text-blue-600 transition-colors hover:bg-blue-100"
                  >
                    <span className="material-symbols-outlined text-[16px]">
                      content_copy
                    </span>
                  </button>
                </div>
              </div>
            </li>

            {/* Step 3 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                3
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">
                    Add credentials to your deployment
                  </span>{" "}
                  — copy the <strong>OAuth client ID</strong> and{" "}
                  <strong>OAuth client secret</strong> from the integration
                  settings, then set the backend environment variable:
                </div>
                <div className="rounded-xl border border-blue-300 bg-white px-3 py-2.5 font-mono text-xs leading-relaxed text-[#2a2640]">
                  <div>CONNECTOR_OAUTH_CLIENTS=</div>
                  <div className="pl-2 text-[#464555]">
                    {'[{"provider_key":"notion",'}
                  </div>
                  <div className="pl-4 text-[#464555]">
                    {'"client_id":"<your-client-id>",'}
                  </div>
                  <div className="pl-4 text-[#464555]">
                    {'"client_secret":"<your-client-secret>"}]'}
                  </div>
                </div>
              </div>
            </li>

            {/* Step 4 */}
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                4
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">
                    Choose scope in the wizard
                  </span>{" "}
                  — after connecting, optionally scope the sync to specific
                  pages or databases. Leave blank to index all content the
                  integration can access.
                </div>
                <div className="rounded-xl border border-blue-300 bg-white px-3 py-2.5 font-mono text-xs leading-relaxed text-[#2a2640]">
                  <div>page_ids, database_ids</div>
                  <div>include_comments, include_attachments</div>
                  <div>max_page_depth, import_property_metadata</div>
                </div>
              </div>
            </li>
          </ol>

          <div className="flex items-start gap-2 rounded-xl border border-blue-200 bg-white p-3 text-xs text-blue-800">
            <span className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-blue-600">
              lock
            </span>
            <span>
              Rudix requests read-only access only. It cannot create, edit, or
              delete any Notion pages, databases, or comments.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function MicrosoftSharePointOneDriveSetupGuide() {
  const [open, setOpen] = useState(false);
  let callbackUrl = "{API_BASE_URL}/connectors/oauth/callback";
  try {
    const apiUrl = getFrontendRuntimeConfig().apiUrl.replace(/\/$/, "");
    callbackUrl = `${apiUrl}/connectors/oauth/callback`;
  } catch {
    // runtime config unavailable during SSR
  }

  return (
    <div className="w-full max-w-4xl overflow-hidden rounded-2xl border border-blue-200 bg-blue-50">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-blue-100/60"
      >
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-[20px] text-blue-700">
            cloud_done
          </span>
          <div>
            <div className="text-sm font-semibold text-blue-900">
              Microsoft 365 tenant setup required
            </div>
            <div className="text-xs text-blue-700">
              One-time prerequisite - create an Azure app registration before
              connecting
            </div>
          </div>
        </div>
        <span
          className={`material-symbols-outlined shrink-0 text-[20px] text-blue-600 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          expand_more
        </span>
      </button>

      {open && (
        <div className="space-y-5 border-t border-blue-200 px-5 pt-4 pb-5">
          <p className="text-sm leading-relaxed text-blue-800">
            Rudix connects to SharePoint and OneDrive through Microsoft Graph.
            After the OAuth app is configured, choose the sites, libraries,
            drives, and folders you want to index, then scope file types and
            sync frequency through the shared wizard fields.
          </p>

          <ol className="space-y-4">
            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                1
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">Register an app</span> - open
                the{" "}
                <a
                  href="https://portal.azure.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 hover:text-blue-700"
                >
                  Azure portal
                </a>
                , create an app registration, and note the tenant, client ID,
                and client secret for your deployment.
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                2
              </span>
              <div className="text-sm text-blue-900">
                <span className="font-semibold">Add the redirect URI</span> -
                under <strong>Authentication</strong>, add this exact callback
                URL:
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                3
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">
                    Grant Microsoft Graph permissions
                  </span>{" "}
                  - add the read-only scopes below so Rudix can validate the
                  tenant, discover sites and drives, and read document content.
                </div>
                <div className="flex items-center gap-2 rounded-xl border border-blue-300 bg-white px-3 py-2">
                  <span className="flex-1 font-mono text-xs break-all text-[#2a2640]">
                    {callbackUrl}
                  </span>
                  <button
                    type="button"
                    title="Copy callback URL"
                    onClick={() => navigator.clipboard.writeText(callbackUrl)}
                    className="shrink-0 rounded-lg p-1.5 text-blue-600 transition-colors hover:bg-blue-100"
                  >
                    <span className="material-symbols-outlined text-[16px]">
                      content_copy
                    </span>
                  </button>
                </div>
                <div className="divide-y divide-blue-100 overflow-hidden rounded-xl border border-blue-300 bg-white">
                  {MICROSOFT_SHAREPOINT_ONEDRIVE_SCOPES.map(
                    ({ scope, required, description }) => (
                      <div
                        key={scope}
                        className="flex items-center gap-3 px-3 py-2.5"
                      >
                        <span className="flex-1 font-mono text-xs break-all text-[#2a2640]">
                          {scope}
                        </span>
                        <span className="hidden text-xs text-[#6a6780] sm:block">
                          {description}
                        </span>
                        {required ? (
                          <span className="shrink-0 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold tracking-wide text-rose-700 uppercase">
                            Required
                          </span>
                        ) : (
                          <span className="shrink-0 rounded-full bg-[#ece8ff] px-2 py-0.5 text-[10px] font-bold tracking-wide text-[#3525cd] uppercase">
                            Recommended
                          </span>
                        )}
                      </div>
                    ),
                  )}
                </div>
              </div>
            </li>

            <li className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-900">
                4
              </span>
              <div className="flex-1 space-y-2 text-sm text-blue-900">
                <div>
                  <span className="font-semibold">
                    Choose source scope in the wizard
                  </span>{" "}
                  - select the SharePoint sites, document libraries, OneDrive
                  drives, and folders to index, then set allowed file types and
                  sync frequency.
                </div>
                <div className="rounded-xl border border-blue-300 bg-white px-3 py-2.5 font-mono text-xs leading-relaxed text-[#2a2640]">
                  <div>site_ids, drive_ids, folder_ids</div>
                  <div>allowed_file_types, include_folder_paths</div>
                  <div>exclude_folder_paths, sync_frequency_minutes</div>
                  <div>permission_import_behavior, max_file_size_mb</div>
                </div>
              </div>
            </li>
          </ol>

          <div className="flex items-start gap-2 rounded-xl border border-blue-200 bg-white p-3 text-xs text-blue-800">
            <span className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-blue-600">
              lock
            </span>
            <span>
              Rudix requests read-only Graph scopes only. It does not modify or
              delete content in Microsoft 365.
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
      confirmed: false,
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
      key: "permissions",
      label: "Permissions",
      component: (props: WizardStepProps<ConnectorSetupState>) => (
        <PermissionReviewStep
          {...props}
          provider={provider}
          scopeValues={props.state.config_values}
        />
      ),
      canProceed: (state: ConnectorSetupState) => state.confirmed === true,
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

      {provider.key === "confluence" && <ConfluenceSetupGuide />}
      {provider.key === "google_drive" && <GoogleDriveSetupGuide />}
      {provider.key === "microsoft-sharepoint-onedrive" && (
        <MicrosoftSharePointOneDriveSetupGuide />
      )}
      {provider.key === "notion" && <NotionSetupGuide />}

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
