import type { AuditLogListItemResponse } from "@/lib/api/admin-usage";

export type AuditStatusFilter =
  | "all"
  | "success"
  | "client_error"
  | "server_error"
  | "unknown";

const REDACTED_VALUE = "[redacted]";
const TRUNCATED_VALUE_SUFFIX = "…";
const MAX_STRING_LENGTH = 400;
const MAX_OBJECT_KEYS = 40;
const MAX_ARRAY_ITEMS = 40;
const MAX_DEPTH = 6;
const SENSITIVE_KEY_PATTERN =
  /(authorization|token|cookie|password|secret|api[_-]?key|credential|session)/i;

function truncateString(value: string): string {
  if (value.length <= MAX_STRING_LENGTH) {
    return value;
  }
  return `${value.slice(0, MAX_STRING_LENGTH)}${TRUNCATED_VALUE_SUFFIX}`;
}

function sanitizeValue(value: unknown, depth: number): unknown {
  if (value == null) {
    return value;
  }

  if (depth > MAX_DEPTH) {
    return "[max depth]";
  }

  if (typeof value === "string") {
    return truncateString(value);
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return value;
  }

  if (Array.isArray(value)) {
    const trimmed = value
      .slice(0, MAX_ARRAY_ITEMS)
      .map((item) => sanitizeValue(item, depth + 1));
    if (value.length > MAX_ARRAY_ITEMS) {
      trimmed.push(`[truncated ${value.length - MAX_ARRAY_ITEMS} items]`);
    }
    return trimmed;
  }

  if (typeof value === "object") {
    const source = value as Record<string, unknown>;
    const entries = Object.entries(source).slice(0, MAX_OBJECT_KEYS);
    const sanitized: Record<string, unknown> = {};

    for (const [key, nested] of entries) {
      if (SENSITIVE_KEY_PATTERN.test(key)) {
        sanitized[key] = REDACTED_VALUE;
        continue;
      }
      sanitized[key] = sanitizeValue(nested, depth + 1);
    }

    if (Object.keys(source).length > MAX_OBJECT_KEYS) {
      sanitized.__truncated_keys__ = `[truncated ${Object.keys(source).length - MAX_OBJECT_KEYS} keys]`;
    }

    return sanitized;
  }

  return String(value);
}

export function sanitizeAuditMetadata(
  metadata: Record<string, unknown>,
): Record<string, unknown> {
  return sanitizeValue(metadata, 0) as Record<string, unknown>;
}

export function getAuditStatusCode(
  metadata: Record<string, unknown>,
): number | null {
  const candidates = [
    metadata.status_code,
    metadata.http_status,
    metadata.statusCode,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      return Math.trunc(candidate);
    }
    if (typeof candidate === "string") {
      const parsed = Number.parseInt(candidate, 10);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return null;
}

export function getAuditStatusFilter(
  event: AuditLogListItemResponse,
): Exclude<AuditStatusFilter, "all"> {
  const statusCode = getAuditStatusCode(event.metadata ?? {});
  if (statusCode == null) {
    return "unknown";
  }
  if (statusCode >= 200 && statusCode < 400) {
    return "success";
  }
  if (statusCode >= 400 && statusCode < 500) {
    return "client_error";
  }
  if (statusCode >= 500) {
    return "server_error";
  }
  return "unknown";
}

export function matchesAuditStatusFilter(
  event: AuditLogListItemResponse,
  filter: AuditStatusFilter,
): boolean {
  if (filter === "all") {
    return true;
  }
  return getAuditStatusFilter(event) === filter;
}

export function formatAuditStatusLabel(
  filter: Exclude<AuditStatusFilter, "all">,
): string {
  if (filter === "success") {
    return "Success";
  }
  if (filter === "client_error") {
    return "Client error";
  }
  if (filter === "server_error") {
    return "Server error";
  }
  return "Unknown";
}
