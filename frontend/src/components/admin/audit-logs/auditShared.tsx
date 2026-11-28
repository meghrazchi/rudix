"use client";

import { useTranslations } from "next-intl";
import {
  type AuditLogExportFormat,
  type AuditLogListItemResponse,
} from "@/lib/api/admin-usage";

export const AUDIT_PAGE_LIMIT = 20;

export type AppliedFilters = {
  organizationId: string | null;
  actor: string | null;
  action: string | null;
  entity: string | null;
  resourceId: string | null;
  documentId: string | null;
  collectionId: string | null;
  ipAddress: string | null;
  sessionId: string | null;
  requestId: string | null;
  result: "all" | "success" | "failure" | "unknown";
  severity: string | null;
  search: string | null;
};

export type BeforeAfterSummary = {
  before: unknown | null;
  after: unknown | null;
  changedFields: string[];
};

export const DEFAULT_FILTERS: AppliedFilters = {
  organizationId: null,
  actor: null,
  action: null,
  entity: null,
  resourceId: null,
  documentId: null,
  collectionId: null,
  ipAddress: null,
  sessionId: null,
  requestId: null,
  result: "all",
  severity: null,
  search: null,
};

export function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function formatTimestamp(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return value;
  }
  return new Date(timestamp).toLocaleString();
}

export function triggerBlobDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export function buildExportFilename(
  format: AuditLogExportFormat,
  fromDate: string,
  toDate: string,
): string {
  return `audit-logs-${fromDate}-${toDate}.${format}`;
}

export function normalizeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => (typeof entry === "string" ? entry.trim() : ""))
    .filter((entry) => entry.length > 0);
}

export function summarizeBeforeAfter(
  metadata: Record<string, unknown>,
): BeforeAfterSummary {
  const beforeCandidates = [
    "before_summary",
    "before",
    "old",
    "previous",
    "old_access_policy",
    "previous_value",
  ];
  const afterCandidates = [
    "after_summary",
    "after",
    "new",
    "current",
    "new_access_policy",
    "next_value",
  ];

  let before: unknown | null = null;
  for (const key of beforeCandidates) {
    if (key in metadata) {
      before = metadata[key] ?? null;
      break;
    }
  }

  let after: unknown | null = null;
  for (const key of afterCandidates) {
    if (key in metadata) {
      after = metadata[key] ?? null;
      break;
    }
  }

  const changedFields = [
    ...normalizeStringArray(metadata.changed_fields),
    ...normalizeStringArray(metadata.changed_field_names),
  ];

  return { before, after, changedFields };
}

export function resultPillClass(
  result: AuditLogListItemResponse["result"],
): string {
  if (result === "success") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (result === "failure") {
    return "bg-rose-100 text-rose-800";
  }
  return "bg-slate-200 text-slate-700";
}

export function buildRelatedLinks(
  event: AuditLogListItemResponse,
  t: ReturnType<typeof useTranslations>,
): Array<{ href: string; label: string }> {
  const links: Array<{ href: string; label: string }> = [];
  const documentId =
    trimToNull(event.document_id) ??
    (event.resource_type === "document" ? trimToNull(event.resource_id) : null);
  if (documentId) {
    links.push({
      href: `/documents/${encodeURIComponent(documentId)}`,
      label: t("openDocument"),
    });
  }

  const collectionId =
    trimToNull(event.collection_id) ??
    (event.resource_type === "collection"
      ? trimToNull(event.resource_id)
      : null);
  if (collectionId) {
    links.push({ href: "/collections", label: t("openCollections") });
  }

  const sessionId =
    trimToNull(event.session_id) ??
    (event.resource_type === "chat_session"
      ? trimToNull(event.resource_id)
      : null);
  if (sessionId) {
    links.push({
      href: `/chat?session_id=${encodeURIComponent(sessionId)}`,
      label: t("openChatSession"),
    });
  }

  return links;
}

export function getActorLabel(
  item: AuditLogListItemResponse,
  systemLabel: string,
): string {
  if (item.user_id) {
    return item.user_id;
  }
  const actorEmail = item.metadata.actor_email;
  if (typeof actorEmail === "string" && actorEmail.trim().length > 0) {
    return actorEmail;
  }
  return systemLabel;
}
