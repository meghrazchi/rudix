import type { useTranslations } from "next-intl";

import type {
  DocumentDetailResponse,
  DocumentFileType,
  DocumentQualityState,
  DocumentSortBy,
  DocumentStatus,
  DocumentStatusResponse,
  SortOrder,
} from "@/lib/api/documents";

export type DocumentsPageTranslator = ReturnType<
  typeof useTranslations<"documents.page">
>;

const DOCUMENT_PAGE_SIZE = 20;
const CHUNK_PAGE_SIZE = 8;

type StatusFilter = "all" | DocumentStatus;
type FileTypeFilter = "all" | DocumentFileType;
type FreshnessFilter =
  | "all"
  | "current"
  | "trusted"
  | "needs_review"
  | "stale"
  | "expired"
  | "archived";
type QualityFilter = "all" | DocumentQualityState;
type IndexingStatusSummary = {
  total: number;
  uploaded: number;
  indexed: number;
  processing: number;
  failed: number;
};

function parseStatusFilter(value: string | null): StatusFilter {
  if (!value) {
    return "all";
  }
  const supported: DocumentStatus[] = [
    "uploaded",
    "processing",
    "indexed",
    "failed",
    "quarantined",
    "blocked",
    "delete_requested",
    "deleting",
    "deleted",
    "retained_by_policy",
  ];
  return supported.includes(value as DocumentStatus)
    ? (value as DocumentStatus)
    : "all";
}

function parseFreshnessFilter(value: string | null): FreshnessFilter {
  if (!value) {
    return "all";
  }
  const supported: FreshnessFilter[] = [
    "current",
    "trusted",
    "needs_review",
    "stale",
    "expired",
    "archived",
  ];
  return supported.includes(value as FreshnessFilter)
    ? (value as FreshnessFilter)
    : "all";
}

function parseQualityFilter(value: string | null): QualityFilter {
  if (!value) {
    return "all";
  }
  const supported: QualityFilter[] = [
    "draft",
    "verified",
    "reviewed",
    "unreviewed",
    "stale",
    "expired",
    "deprecated",
    "archived",
  ];
  return supported.includes(value as QualityFilter)
    ? (value as QualityFilter)
    : "all";
}

function parseSortBy(value: string | null): DocumentSortBy {
  if (value === "updated_at" || value === "filename" || value === "status") {
    return value;
  }
  return "created_at";
}

function parseSortOrder(value: string | null): SortOrder {
  return value === "asc" ? "asc" : "desc";
}

function parseOffset(value: string | null): number {
  if (!value) {
    return 0;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 0;
  }
  return parsed;
}

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function statusBadge(status: DocumentStatus): string {
  if (status === "indexed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "processing") {
    return "rounded-full bg-blue-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-blue-800";
  }
  if (status === "uploaded") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "failed") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "quarantined") {
    return "rounded-full bg-orange-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-orange-800";
  }
  if (status === "blocked") {
    return "rounded-full bg-red-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-red-800";
  }
  if (status === "delete_requested") {
    return "rounded-full bg-rose-50 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-600";
  }
  if (status === "deleting") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  if (status === "deleted") {
    return "rounded-full bg-slate-300 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-800";
  }
  if (status === "retained_by_policy") {
    return "rounded-full bg-yellow-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-yellow-800";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function freshnessBadge(status: FreshnessFilter | undefined): string {
  if (status === "trusted") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "current") {
    return "rounded-full bg-sky-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-sky-800";
  }
  if (status === "needs_review") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "stale") {
    return "rounded-full bg-orange-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-orange-800";
  }
  if (status === "expired") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "archived") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold tracking-wide text-slate-700 uppercase";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function qualityBadge(status: DocumentQualityState | null | undefined): string {
  if (status === "verified") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "reviewed") {
    return "rounded-full bg-sky-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-sky-800";
  }
  if (status === "unreviewed") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "draft") {
    return "rounded-full bg-violet-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-violet-800";
  }
  if (status === "stale") {
    return "rounded-full bg-orange-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-orange-800";
  }
  if (status === "expired") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "deprecated") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  if (status === "archived") {
    return "rounded-full bg-slate-300 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-800";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function documentTypeIcon(fileType: string): string {
  if (fileType === "pdf") {
    return "picture_as_pdf";
  }
  if (fileType === "docx") {
    return "description";
  }
  return "notes";
}

function documentTypeIconClass(fileType: string): string {
  if (fileType === "pdf") {
    return "text-[#3525cd]";
  }
  if (fileType === "docx") {
    return "text-[#505f76]";
  }
  return "text-[#7e3000]";
}

function truncateFilename(name: string, maxLen = 28): string {
  if (name.length <= maxLen) return name;
  const extDot = name.lastIndexOf(".");
  const ext = extDot > 0 ? name.slice(extDot) : "";
  const base = extDot > 0 ? name.slice(0, extDot) : name;
  const budget = maxLen - ext.length - 1;
  const startLen = Math.ceil(budget * 0.6);
  const endLen = Math.floor(budget * 0.4);
  return base.slice(0, startLen) + "…" + base.slice(-endLen) + ext;
}

function documentSourceLabel(
  sourceProvider: string | null | undefined,
  sourceProviderLabel: string | null | undefined,
  localUploadLabel: string,
): string | null {
  if (sourceProviderLabel) return sourceProviderLabel;
  if (!sourceProvider) return null;
  const map: Record<string, string> = {
    confluence: "Confluence",
    google_drive: "Google Drive",
    "microsoft-sharepoint-onedrive": "SharePoint / OneDrive",
    notion: "Notion",
    jira: "Jira",
    upload: localUploadLabel,
  };
  return map[sourceProvider] ?? sourceProvider.replace(/_/g, " ");
}

function documentSourceIcon(sourceProvider: string | null | undefined): string {
  if (!sourceProvider || sourceProvider === "upload") return "upload_file";
  const map: Record<string, string> = {
    confluence: "integration_instructions",
    google_drive: "add_to_drive",
    "microsoft-sharepoint-onedrive": "cloud",
    notion: "article",
    jira: "bug_report",
  };
  return map[sourceProvider] ?? "cloud_sync";
}

function buildPaginationItems(
  currentPage: number,
  totalPages: number,
): Array<number | null> {
  if (totalPages <= 6) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const items: Array<number | null> = [1];
  const left = Math.max(2, currentPage - 1);
  const right = Math.min(totalPages - 1, currentPage + 1);

  if (left > 2) {
    items.push(null);
  }

  for (let page = left; page <= right; page += 1) {
    items.push(page);
  }

  if (right < totalPages - 1) {
    items.push(null);
  }

  items.push(totalPages);
  return items;
}

function deriveDetailStatus(
  detail: DocumentDetailResponse,
  liveStatus: DocumentStatusResponse | undefined,
): DocumentStatus {
  return liveStatus?.status ?? detail.status;
}

function triggerBlobDownload(blob: Blob, filename: string): void {
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

export {
  CHUNK_PAGE_SIZE,
  DOCUMENT_PAGE_SIZE,
  buildPaginationItems,
  deriveDetailStatus,
  documentSourceIcon,
  documentSourceLabel,
  documentTypeIcon,
  documentTypeIconClass,
  formatDate,
  freshnessBadge,
  parseFreshnessFilter,
  parseOffset,
  parseQualityFilter,
  parseSortBy,
  parseSortOrder,
  parseStatusFilter,
  qualityBadge,
  statusBadge,
  triggerBlobDownload,
  truncateFilename,
};
export type {
  FileTypeFilter,
  FreshnessFilter,
  IndexingStatusSummary,
  QualityFilter,
  StatusFilter,
};
