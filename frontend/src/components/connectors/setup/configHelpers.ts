import {
  type ProviderConfigSchemaField,
  type ProviderSummary,
} from "@/lib/api/connector-providers";

export function buildConfigFieldState(
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

export function normalizeFieldValue(
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

export function toStringArray(
  value: string | boolean,
  uppercase = false,
): string[] {
  if (typeof value === "boolean") {
    return value ? ["true"] : [];
  }
  return value
    .split(",")
    .map((item) => item.trim())
    .map((item) => (uppercase ? item.toUpperCase() : item))
    .filter((item) => item.length > 0);
}

export function fieldLabel(
  name: string,
  field: ProviderConfigSchemaField,
): string {
  return field.title ?? name.replace(/_/g, " ");
}

export function fieldPlaceholder(
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

export function externalAccountPlaceholder(providerKey: string): string {
  if (providerKey === "microsoft-sharepoint-onedrive") {
    return "contoso.onmicrosoft.com or user@contoso.com";
  }
  return "acme.atlassian.net";
}

export function validateConfigField(
  field: ProviderConfigSchemaField,
  rawValue: string | boolean,
  required: boolean,
): "required" | "url" | null {
  if (field.type === "boolean") {
    return null;
  }

  const value = typeof rawValue === "string" ? rawValue.trim() : "";
  if (!value && required) {
    return "required";
  }
  if (!value) {
    return null;
  }
  if (field.format === "uri" && !/^https?:\/\/.+/i.test(value)) {
    return "url";
  }
  return null;
}

export function parseConfigValue(
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

export function buildProviderConfig(
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

export function configSummary(
  provider: ProviderSummary,
  values: Record<string, string | boolean>,
  enabledLabel: string,
  aclSummary: string,
): string[] {
  const fields = provider.config_schema.properties ?? {};
  const selected: string[] = [];

  for (const [name, field] of Object.entries(fields)) {
    const value = values[name];
    const label = fieldLabel(name, field);
    if (field.type === "boolean") {
      if (Boolean(value)) {
        selected.push(`${label}: ${enabledLabel}`);
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
    selected.push(aclSummary);
  }
  return selected;
}
