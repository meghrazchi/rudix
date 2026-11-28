"use client";

import { useTranslations } from "next-intl";

import type { DocumentSortBy } from "@/lib/api/documents";

import type {
  FileTypeFilter,
  FreshnessFilter,
  QualityFilter,
  StatusFilter,
} from "@/components/documents/list/documents-list-format";

/** Translated option lists for the documents filter bar and badges. */
export function useDocumentsFilterOptions() {
  const tp = useTranslations("documents.page");

  const statusFilterOptions: Array<{ value: StatusFilter; label: string }> = [
    { value: "all", label: tp("statusAll") },
    { value: "uploaded", label: tp("statusUploaded") },
    { value: "processing", label: tp("statusProcessing") },
    { value: "indexed", label: tp("statusIndexed") },
    { value: "failed", label: tp("statusFailed") },
    { value: "quarantined", label: tp("statusQuarantined") },
    { value: "blocked", label: tp("statusBlocked") },
    { value: "delete_requested", label: tp("statusDeleteRequested") },
    { value: "deleting", label: tp("statusDeleting") },
    { value: "deleted", label: tp("statusDeleted") },
    { value: "retained_by_policy", label: tp("statusRetainedByPolicy") },
  ];
  const freshnessFilterOptions: Array<{
    value: FreshnessFilter;
    label: string;
  }> = [
    { value: "all", label: tp("freshnessAll") },
    { value: "current", label: tp("freshnessCurrent") },
    { value: "trusted", label: tp("freshnessTrusted") },
    { value: "needs_review", label: tp("freshnessNeedsReview") },
    { value: "stale", label: tp("freshnessStale") },
    { value: "expired", label: tp("freshnessExpired") },
    { value: "archived", label: tp("freshnessArchived") },
  ];
  const qualityFilterOptions: Array<{ value: QualityFilter; label: string }> = [
    { value: "all", label: tp("qualityAll") },
    { value: "draft", label: tp("qualityDraft") },
    { value: "verified", label: tp("qualityVerified") },
    { value: "reviewed", label: tp("qualityReviewed") },
    { value: "unreviewed", label: tp("qualityUnreviewed") },
    { value: "stale", label: tp("qualityStale") },
    { value: "expired", label: tp("qualityExpired") },
    { value: "deprecated", label: tp("qualityDeprecated") },
    { value: "archived", label: tp("qualityArchived") },
  ];

  const sortByOptions: Array<{ value: DocumentSortBy; label: string }> = [
    { value: "created_at", label: tp("sortCreated") },
    { value: "updated_at", label: tp("sortUpdated") },
    { value: "filename", label: tp("sortFilename") },
    { value: "status", label: tp("sortStatus") },
  ];

  const fileTypeFilterOptions: Array<{ value: FileTypeFilter; label: string }> =
    [
      { value: "all", label: tp("typeAll") },
      { value: "pdf", label: tp("typePdf") },
      { value: "docx", label: tp("typeDocx") },
      { value: "txt", label: tp("typeTxt") },
    ];

  return {
    statusFilterOptions,
    freshnessFilterOptions,
    qualityFilterOptions,
    sortByOptions,
    fileTypeFilterOptions,
  };
}
