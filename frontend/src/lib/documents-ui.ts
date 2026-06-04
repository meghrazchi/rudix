import type {
  DocumentListItemResponse,
  DocumentStatus,
} from "@/lib/api/documents";
import type { AppRole } from "@/lib/auth-session";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";

const POLLING_STATUSES = new Set<DocumentStatus>([
  "uploaded",
  "processing",
  "delete_requested",
  "deleting",
]);

export type DocumentCapabilities = {
  canUpload: boolean;
  canDelete: boolean;
  canReindex: boolean;
  canViewChunkFullText: boolean;
  canOverrideLanguage: boolean;
};

export function resolveDocumentCapabilities(
  role: AppRole | null | undefined,
): DocumentCapabilities {
  if (role === "owner") {
    return {
      canUpload: true,
      canDelete: true,
      canReindex: true,
      canViewChunkFullText: true,
      canOverrideLanguage: true,
    };
  }
  if (role === "admin") {
    return {
      canUpload: true,
      canDelete: true,
      canReindex: true,
      canViewChunkFullText: true,
      canOverrideLanguage: true,
    };
  }
  if (role === "member") {
    return {
      canUpload: true,
      canDelete: true,
      canReindex: false,
      canViewChunkFullText: true,
      canOverrideLanguage: false,
    };
  }
  return {
    canUpload: false,
    canDelete: false,
    canReindex: false,
    canViewChunkFullText: false,
    canOverrideLanguage: false,
  };
}

export function shouldPollDocumentStatus(status: DocumentStatus): boolean {
  return POLLING_STATUSES.has(status);
}

export function shouldPollDocumentList(
  items: DocumentListItemResponse[] | undefined,
): boolean {
  if (!items || items.length === 0) {
    return false;
  }
  return items.some((item) => shouldPollDocumentStatus(item.status));
}

export function canDeleteDocument(status: DocumentStatus): boolean {
  return (
    status !== "deleted" &&
    status !== "deleting" &&
    status !== "delete_requested" &&
    status !== "retained_by_policy"
  );
}

export function canReindexDocument(status: DocumentStatus): boolean {
  return status === "uploaded" || status === "indexed" || status === "failed";
}

export function getDocumentLifecycleActionErrorMessage(
  action: "delete" | "reindex",
  error: unknown,
): string {
  if (isApiClientError(error) && error.status === 409) {
    if (action === "delete") {
      return "Document cannot be deleted in its current lifecycle state. Wait for processing/deleting to finish, then refresh and retry.";
    }
    return "Document cannot be re-indexed in its current lifecycle state. Wait for processing/deleting to finish, then refresh and retry.";
  }
  return getApiErrorMessage(error);
}

export function isDeletionInProgress(status: DocumentStatus): boolean {
  return status === "delete_requested" || status === "deleting";
}

export function isRetainedByPolicy(status: DocumentStatus): boolean {
  return status === "retained_by_policy";
}
