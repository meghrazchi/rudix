"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { trackFeatureEvent } from "@/lib/analytics";
import type { AnalyticsEventPayload } from "@/lib/analytics";
import { downloadDocumentFile, getDocument } from "@/lib/api/documents";
import { isApiClientError } from "@/lib/api/errors";
import { copyToClipboard } from "@/lib/export-utils";
import { addFrontendBreadcrumb } from "@/lib/observability";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

type CitationPreviewItem = {
  document_id: string;
  chunk_id: string | null;
  filename?: string | null;
  freshness_state?: string | null;
  source_title?: string | null;
  source_provider?: string | null;
  source_provider_label?: string | null;
  source_key?: string | null;
  source_section?: string | null;
  source_url?: string | null;
  source_deep_link?: string | null;
  source_last_synced_at?: string | null;
  source_trust_status?: string | null;
  doc_version_label?: string | null;
  doc_review_status?: string | null;
  doc_last_updated_at?: string | null;
  doc_expired_warning?: boolean | null;
  doc_stale_warning?: boolean | null;
  doc_is_excluded_status?: boolean | null;
  doc_unreviewed_warning?: boolean | null;
  doc_deprecated_warning?: boolean | null;
  doc_ocr_quality_status?: string | null;
  doc_ocr_low_confidence_warning?: boolean | null;
  doc_extraction_warning?: boolean | null;
  doc_processing_warning?: boolean | null;
  page_number?: number | null;
  text_snippet?: string | null;
  score?: number | null;
  similarity_score?: number | null;
  rerank_score?: number | null;
  start_offset?: number | null;
  end_offset?: number | null;
  is_table_chunk?: boolean | null;
  table_caption?: string | null;
  table_section_context?: string | null;
  table_headers?: string[] | null;
  table_row_count?: number | null;
  table_col_count?: number | null;
  table_extraction_confidence?: number | null;
  table_low_confidence_warning?: boolean | null;
};

type Props = {
  citations: CitationPreviewItem[];
  initialIndex?: number;
  onClose: () => void;
};

const MAX_CITATIONS_TO_RENDER = 12;
const MAX_SNIPPET_LENGTH = 320;
const PREVIEW_ROUTE = "/chat";

type CitationPreviewEventName =
  | "feature.chat.citation_preview_opened"
  | "feature.chat.citation_preview_load_failed"
  | "feature.chat.citation_preview_permission_denied"
  | "feature.chat.citation_preview_source_missing"
  | "feature.chat.citation_preview_external_link_clicked";

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatScore(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(3)
    : "-";
}

function normalizeFreshnessState(
  citation: CitationPreviewItem,
  doc: CitationPreviewDoc | undefined,
): string | null {
  const explicit = citation.freshness_state ?? null;
  if (explicit) {
    return explicit;
  }
  const reviewStatus = doc?.review_status ?? citation.doc_review_status ?? null;
  const trustStatus = doc?.trust_status ?? citation.source_trust_status ?? null;
  if (reviewStatus === "needs_review" || citation.doc_unreviewed_warning) {
    return "unreviewed";
  }
  if (
    reviewStatus === "stale" ||
    trustStatus === "stale" ||
    citation.doc_stale_warning
  ) {
    return "stale";
  }
  if (
    reviewStatus === "expired" ||
    trustStatus === "deleted" ||
    trustStatus === "expired" ||
    citation.doc_expired_warning
  ) {
    return "expired";
  }
  if (
    reviewStatus === "archived" ||
    trustStatus === "deprecated" ||
    trustStatus === "superseded" ||
    trustStatus === "revoked" ||
    citation.doc_deprecated_warning
  ) {
    return "deprecated";
  }
  if (trustStatus === "draft") {
    return "draft";
  }
  if (trustStatus === "trusted" || trustStatus === "current") {
    return "current";
  }
  return null;
}

function freshnessBadge(
  state: string | null | undefined,
): { label: string; className: string } | null {
  if (!state) {
    return null;
  }
  if (state === "current") {
    return {
      label: "Current",
      className:
        "rounded bg-emerald-100 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-800 uppercase",
    };
  }
  if (state === "stale") {
    return {
      label: "Stale",
      className:
        "rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  }
  if (state === "expired") {
    return {
      label: "Expired",
      className:
        "rounded bg-rose-100 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  }
  if (state === "deprecated") {
    return {
      label: "Deprecated",
      className:
        "rounded bg-slate-200 px-1.5 py-0.5 text-[9px] font-semibold text-slate-700 uppercase",
    };
  }
  if (state === "draft") {
    return {
      label: "Draft",
      className:
        "rounded bg-sky-100 px-1.5 py-0.5 text-[9px] font-semibold text-sky-800 uppercase",
    };
  }
  if (state === "unreviewed") {
    return {
      label: "Unreviewed",
      className:
        "rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  }
  return {
    label: "Unknown",
    className:
      "rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-semibold text-slate-600 uppercase",
  };
}

type CitationPreviewDoc = {
  filename?: string | null;
  file_type?: string | null;
  status?: string | null;
  language?: string | null;
  source_provider?: string | null;
  source_provider_label?: string | null;
  source_title?: string | null;
  source_key?: string | null;
  source_url?: string | null;
  source_link_allowed?: boolean;
  source_last_synced_at?: string | null;
  source_sync_version?: number | null;
  source_visibility?: string | null;
  source_trust_status?: string | null;
  document_title?: string | null;
  document_type?: string | null;
  document_owner_email?: string | null;
  document_owner_display_name?: string | null;
  document_owner_id?: string | null;
  document_version_label?: string | null;
  document_last_updated_at?: string | null;
  document_last_indexed_at?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  uploaded_by_user_id?: string | null;
  uploaded_by_user_email?: string | null;
  uploaded_by_user_display_name?: string | null;
  review_status?: string | null;
  trust_status?: string | null;
  review_owner_id?: string | null;
  expiry_date?: string | null;
  ocr_quality_status?: string | null;
};

function fileTypeIcon(fileType: string | null | undefined): string {
  if (fileType === "pdf") return "picture_as_pdf";
  if (fileType === "docx") return "description";
  return "article";
}

function fileTypeLabel(fileType: string | null | undefined): string {
  if (fileType === "pdf") return "PDF";
  if (fileType === "docx") return "DOCX";
  if (fileType === "txt") return "Plain text";
  return (fileType ?? "file").toUpperCase();
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

function truncateSnippet(
  value: string,
  maxLength = MAX_SNIPPET_LENGTH,
): string {
  const normalized = value.trim().replace(/\s+/g, " ");
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trimEnd()}…`;
}

function citationPreviewKey(citation: CitationPreviewItem): string {
  return [
    citation.document_id,
    citation.chunk_id ?? "",
    citation.page_number ?? "",
    citation.source_key ?? "",
  ].join(":");
}

function emitCitationPreviewEvent(
  eventName: CitationPreviewEventName,
  payload: Omit<AnalyticsEventPayload, "surface">,
): void {
  addFrontendBreadcrumb({
    category: "citation.preview",
    message: eventName,
    level:
      eventName === "feature.chat.citation_preview_load_failed"
        ? "error"
        : "info",
    data: payload,
  });

  trackFeatureEvent(eventName, {
    surface: "app",
    featureArea: "chat",
    route: PREVIEW_ROUTE,
    source: "citation_preview",
    ...payload,
  }).catch(() => {
    // Fire-and-forget telemetry must never block preview rendering.
  });
}

export function CitationPreviewDrawer({
  citations,
  initialIndex = 0,
  onClose,
}: Props) {
  const t = useTranslations("chat.citationPreview");
  const visibleCitations = useMemo(
    () => citations.slice(0, MAX_CITATIONS_TO_RENDER),
    [citations],
  );
  const previewHasMoreCitations = citations.length > visibleCitations.length;
  const [activeIndex, setActiveIndex] = useState(
    Math.min(initialIndex, Math.max(0, visibleCitations.length - 1)),
  );
  const [copied, setCopied] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const openedCitationKeyRef = useRef<string | null>(null);
  const failureEventKeyRef = useRef<string | null>(null);
  const sourceMissingEventKeyRef = useRef<string | null>(null);
  const permissionDeniedEventKeyRef = useRef<string | null>(null);
  const maxIndex = Math.max(0, visibleCitations.length - 1);
  const safeActiveIndex = Math.min(activeIndex, maxIndex);
  const currentCitation = useMemo(
    () => visibleCitations[safeActiveIndex] ?? null,
    [safeActiveIndex, visibleCitations],
  );

  useEffect(() => {
    if (!copied) return;
    const timeout = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timeout);
  }, [copied]);

  useOverlayFocus({ isOpen: true, containerRef, onClose });
  const citation =
    currentCitation ??
    ({ document_id: "", chunk_id: null } as CitationPreviewItem);
  const hasCitation = currentCitation != null;

  useEffect(() => {
    if (!hasCitation) {
      return;
    }

    const citationKey = citationPreviewKey(citation);
    const eventContext = {
      entityId: citation.document_id,
      entityType: citation.chunk_id ? "citation_chunk" : "citation",
      count: visibleCitations.length,
      pageKey:
        citation.page_number != null
          ? `page-${citation.page_number}`
          : undefined,
      status: "opened",
      dedupeKey: citationKey,
      source: "citation_preview",
    } satisfies Omit<AnalyticsEventPayload, "surface">;

    if (!citation.document_id) {
      if (sourceMissingEventKeyRef.current === citationKey) {
        return;
      }
      sourceMissingEventKeyRef.current = citationKey;
      emitCitationPreviewEvent("feature.chat.citation_preview_source_missing", {
        ...eventContext,
        entityId: citation.document_id,
        status: "missing_document_id",
      });
      return;
    }

    if (openedCitationKeyRef.current === citationKey) {
      return;
    }

    openedCitationKeyRef.current = citationKey;
    emitCitationPreviewEvent("feature.chat.citation_preview_opened", {
      ...eventContext,
      status: "opened",
    });
  }, [citation, hasCitation, visibleCitations.length]);

  const docQuery = useQuery({
    queryKey: ["citation-preview", "document", citation?.document_id ?? "none"],
    queryFn: ({ signal }) =>
      citation?.document_id
        ? getDocument(citation.document_id, { signal })
        : Promise.reject(new Error("No citation document id")),
    enabled: Boolean(citation?.document_id),
    retry: false,
  });

  const downloadMutation = useMutation({
    mutationFn: () => downloadDocumentFile(citation.document_id),
    onSuccess: (blob) => {
      triggerBlobDownload(
        blob,
        citation.filename?.trim() || `document-${citation.document_id}`,
      );
    },
  });

  const doc = docQuery.data;
  const displayFilename =
    doc?.document_title ??
    doc?.filename ??
    citation?.source_title ??
    citation?.filename ??
    t("documentFallback");
  const displayFileType = doc?.document_type ?? doc?.file_type ?? null;
  const displayStatus = doc?.status ?? null;
  const displayLanguage = doc?.language?.trim().toUpperCase() ?? null;
  const sourceProvider =
    doc?.source_provider_label ??
    citation?.source_provider_label ??
    doc?.source_provider ??
    citation?.source_provider ??
    null;
  const sourceProviderKey =
    doc?.source_provider ?? citation?.source_provider ?? null;
  const freshnessState = citation
    ? normalizeFreshnessState(citation, doc)
    : null;
  const freshness = freshnessBadge(freshnessState);
  const documentOwner =
    doc?.document_owner_display_name ??
    doc?.document_owner_email ??
    doc?.uploaded_by_user_display_name ??
    doc?.uploaded_by_user_email ??
    doc?.document_owner_id ??
    doc?.uploaded_by_user_id ??
    null;
  const documentVersion =
    doc?.document_version_label ?? citation?.doc_version_label ?? null;
  const documentLastUpdatedAt =
    doc?.document_last_updated_at ??
    citation?.doc_last_updated_at ??
    doc?.updated_at ??
    null;
  const documentLastIndexedAt = doc?.document_last_indexed_at ?? null;
  const sourceLastSyncedAt =
    doc?.source_last_synced_at ?? citation?.source_last_synced_at ?? null;
  const sourceLink = doc?.source_link_allowed
    ? (doc.source_url ?? citation?.source_url ?? null)
    : null;
  const sourceSection = citation?.source_section ?? null;
  const sourceLinkLabel =
    doc?.source_provider_label ??
    sourceProvider ??
    (sourceProviderKey ? null : t("uploadedFile"));

  const viewInDocsHref =
    citation?.document_id && citation.chunk_id != null
      ? `/documents/${encodeURIComponent(citation.document_id)}` +
        `?chunk_id=${encodeURIComponent(citation.chunk_id)}` +
        (citation.page_number != null
          ? `&page=${encodeURIComponent(String(citation.page_number))}`
          : "") +
        `&back=${encodeURIComponent(PREVIEW_ROUTE)}`
      : null;

  const copyLink = sourceLink ?? viewInDocsHref;
  const canDownload = Boolean(
    citation?.document_id &&
    !downloadMutation.isPending &&
    !(
      (isApiClientError(docQuery.error) && docQuery.error.status === 403) ||
      (isApiClientError(docQuery.error) && docQuery.error.status === 404)
    ),
  );
  const hasSiblings = visibleCitations.length > 1;
  const canGoPrev = activeIndex > 0;
  const canGoNext = activeIndex < visibleCitations.length - 1;

  const isPermissionDenied =
    isApiClientError(docQuery.error) && docQuery.error.status === 403;
  const isNotFound =
    isApiClientError(docQuery.error) && docQuery.error.status === 404;
  const isCitationNotIndexed =
    isApiClientError(docQuery.error) &&
    docQuery.error.status === 409 &&
    docQuery.error.code === "citation_not_indexed";
  const isCitationStale =
    isApiClientError(docQuery.error) &&
    docQuery.error.status === 409 &&
    docQuery.error.code === "citation_stale";
  const isCitationDeleted =
    isApiClientError(docQuery.error) &&
    docQuery.error.status === 410 &&
    docQuery.error.code === "citation_deleted";
  const isError = docQuery.isError && !isPermissionDenied && !isNotFound;

  useEffect(() => {
    if (!citation.document_id) {
      return;
    }

    const citationKey = citationPreviewKey(citation);
    const eventBase = {
      entityId: citation.document_id,
      entityType: citation.chunk_id ? "citation_chunk" : "citation",
      pageKey:
        citation.page_number != null
          ? `page-${citation.page_number}`
          : undefined,
      count: visibleCitations.length,
      dedupeKey: citationKey,
    } satisfies Omit<AnalyticsEventPayload, "surface">;

    if (isPermissionDenied) {
      if (permissionDeniedEventKeyRef.current === citationKey) {
        return;
      }
      permissionDeniedEventKeyRef.current = citationKey;
      emitCitationPreviewEvent(
        "feature.chat.citation_preview_permission_denied",
        {
          ...eventBase,
          status: "forbidden",
        },
      );
      return;
    }

    if (isNotFound || isCitationDeleted) {
      if (sourceMissingEventKeyRef.current === citationKey) {
        return;
      }
      sourceMissingEventKeyRef.current = citationKey;
      emitCitationPreviewEvent("feature.chat.citation_preview_source_missing", {
        ...eventBase,
        status: isCitationDeleted ? "deleted" : "missing",
      });
      return;
    }

    if (isError) {
      if (failureEventKeyRef.current === citationKey) {
        return;
      }
      failureEventKeyRef.current = citationKey;
      emitCitationPreviewEvent("feature.chat.citation_preview_load_failed", {
        ...eventBase,
        status: isApiClientError(docQuery.error)
          ? `${docQuery.error.status}:${docQuery.error.code}`
          : "unknown_error",
      });
    }
  }, [
    citation,
    docQuery.error,
    isCitationDeleted,
    isError,
    isNotFound,
    isPermissionDenied,
    visibleCitations.length,
  ]);

  const highlightText = truncateSnippet(citation?.text_snippet ?? "");
  const highlightUnavailable = highlightText.length > 0;

  const warningMessages = [
    freshnessState === "stale" || citation.doc_stale_warning
      ? t("warnings.stale")
      : null,
    freshnessState === "expired" || citation.doc_expired_warning
      ? t("warnings.expired")
      : null,
    freshnessState === "deprecated" || citation.doc_deprecated_warning
      ? t("warnings.deprecated")
      : null,
    freshnessState === "unreviewed" || citation.doc_unreviewed_warning
      ? t("warnings.unreviewed")
      : null,
    citation?.doc_ocr_low_confidence_warning ||
    doc?.ocr_quality_status === "low"
      ? t("warnings.lowOcr")
      : null,
    citation?.table_low_confidence_warning ||
    (citation?.table_extraction_confidence != null &&
      citation.table_extraction_confidence < 0.4)
      ? t("warnings.lowTable")
      : null,
    citation?.doc_extraction_warning ? t("warnings.extraction") : null,
    citation?.doc_processing_warning ? t("warnings.processing") : null,
  ].filter((message): message is string => Boolean(message));
  const excerptCard = highlightText ? (
    <div className="rounded-xl border border-[#e4e1ee] bg-[#faf9ff] p-3">
      <p className="mb-1 text-[10px] font-bold tracking-[0.14em] text-[#5d58a8] uppercase">
        {t("citedExcerpt")}
      </p>
      <p
        lang={displayLanguage?.toLowerCase() ?? undefined}
        className="text-sm leading-relaxed whitespace-pre-wrap text-[#1b1b24]"
      >
        <mark className="rounded bg-[#f7e7a9] px-0.5">{highlightText}</mark>
      </p>
      {highlightUnavailable ? (
        <p className="mt-2 text-xs text-[#6a6780]">
          {t("highlightUnavailable")}
        </p>
      ) : null}
    </div>
  ) : null;

  const previewFallback = isCitationDeleted
    ? {
        icon: "delete",
        title: t("fallback.deletedTitle"),
        message: t("fallback.deletedMessage"),
        action: null,
      }
    : isCitationStale
      ? {
          icon: "history",
          title: t("fallback.reindexedTitle"),
          message: t("fallback.reindexedMessage"),
          action: t("tryAgain"),
        }
      : isCitationNotIndexed
        ? {
            icon: "search_off",
            title: t("fallback.notIndexedTitle"),
            message: t("fallback.notIndexedMessage"),
            action: t("tryAgain"),
          }
        : null;

  const sourceSummary = [
    {
      label: t("fields.documentTitle"),
      value: displayFilename,
    },
    {
      label: t("fields.owner"),
      value: documentOwner ?? "-",
    },
    {
      label: t("fields.type"),
      value: displayFileType?.toUpperCase() ?? "-",
    },
    {
      label: t("fields.version"),
      value: documentVersion ?? "-",
    },
    {
      label: t("fields.lastUpdated"),
      value: formatDate(documentLastUpdatedAt),
    },
    {
      label: t("fields.lastIndexed"),
      value: formatDate(documentLastIndexedAt),
    },
    {
      label: t("fields.lastSynced"),
      value: formatDate(sourceLastSyncedAt),
    },
    {
      label: t("fields.connector"),
      value: sourceLinkLabel ?? "-",
    },
    {
      label: t("fields.trust"),
      value: doc?.source_trust_status ?? citation.source_trust_status ?? "-",
    },
    {
      label: t("fields.freshness"),
      value: freshnessState ?? "-",
    },
  ];
  const helpTextId = "citation-preview-help";
  const previewLimitNotice = previewHasMoreCitations
    ? t("previewLimit", { count: MAX_CITATIONS_TO_RENDER })
    : null;

  async function handleCopySourceLink(): Promise<void> {
    if (!copyLink) return;
    await copyToClipboard(copyLink);
    setCopied(true);
  }

  function handleOpenSourceLink(): void {
    if (!sourceLink) {
      return;
    }

    emitCitationPreviewEvent(
      "feature.chat.citation_preview_external_link_clicked",
      {
        entityId: citation.document_id,
        entityType: citation.chunk_id ? "citation_chunk" : "citation",
        pageKey:
          citation.page_number != null
            ? `page-${citation.page_number}`
            : undefined,
        count: visibleCitations.length,
        dedupeKey: `${citationPreviewKey(citation)}:source-link`,
        status: sourceProviderKey ?? "source",
        source: "citation_preview",
      },
    );
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>): void {
    if (event.key === "ArrowLeft" && canGoPrev) {
      event.preventDefault();
      setActiveIndex((current) => Math.max(0, current - 1));
    }
    if (event.key === "ArrowRight" && canGoNext) {
      event.preventDefault();
      setActiveIndex((current) => Math.min(maxIndex, current + 1));
    }
    if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
    }
    if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(maxIndex);
    }
  }

  return (
    <div className="fixed inset-0 z-[60] bg-[#1f1a3f]/50">
      <div className="flex h-full justify-end" onClick={onClose}>
        <aside
          ref={containerRef}
          role="dialog"
          aria-modal="true"
          aria-label={t("dialogLabel", { filename: displayFilename })}
          aria-describedby={helpTextId}
          onClick={(event) => event.stopPropagation()}
          onKeyDown={handleKeyDown}
          className="flex h-full w-full max-w-none flex-col overflow-hidden rounded-none border-s border-[#d7d4e8] bg-white shadow-2xl outline-none sm:max-w-[48rem] sm:rounded-s-2xl"
        >
          <div className="flex shrink-0 items-center gap-3 border-b border-[#e4e1ee] px-5 py-4">
            <span
              className="material-symbols-outlined shrink-0 text-[24px] text-[#3525cd]"
              aria-hidden="true"
            >
              {fileTypeIcon(displayFileType)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
                {t("title")}
              </p>
              <h2 className="truncate text-base font-semibold text-[#1b1b24]">
                {displayFilename}
              </h2>
              <div className="mt-0.5 flex flex-wrap items-center gap-2">
                {displayFileType ? (
                  <span className="rounded bg-[#f0ecf9] px-1.5 py-0.5 font-mono text-[10px] font-bold text-[#3525cd] uppercase">
                    {fileTypeLabel(displayFileType)}
                  </span>
                ) : null}
                {displayLanguage ? (
                  <span className="rounded bg-sky-50 px-1.5 py-0.5 font-mono text-[10px] font-bold text-sky-700 uppercase">
                    {displayLanguage}
                  </span>
                ) : null}
                {sourceProvider ? (
                  <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-mono text-[10px] font-bold text-emerald-700 uppercase">
                    {sourceProvider}
                  </span>
                ) : null}
                {citation.source_key ? (
                  <span
                    className="rounded bg-[#f7f5ff] px-1.5 py-0.5 font-mono text-[10px] font-bold text-[#5d58a8]"
                    title={citation.source_key}
                  >
                    {citation.source_key}
                  </span>
                ) : null}
                {freshness ? (
                  <span className={freshness.className}>
                    {t(`freshness.${freshnessState ?? "unknown"}`)}
                  </span>
                ) : null}
                {citation.doc_ocr_quality_status &&
                citation.doc_ocr_quality_status !== "not_required" ? (
                  <span className="rounded bg-[#f7f5ff] px-1.5 py-0.5 text-[10px] font-semibold text-[#5d58a8] uppercase">
                    OCR {citation.doc_ocr_quality_status}
                  </span>
                ) : null}
                {citation.page_number != null ? (
                  <span className="font-mono text-xs text-[#6a6780]">
                    {t("page", { page: citation.page_number })}
                  </span>
                ) : null}
                {displayStatus ? (
                  <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-600 uppercase">
                    {t.has(`documentStatuses.${displayStatus}`)
                      ? t(`documentStatuses.${displayStatus}`)
                      : displayStatus}
                  </span>
                ) : null}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              data-overlay-autofocus="true"
              aria-label={t("close")}
              className="ms-2 shrink-0 rounded-full p-1.5 text-[#464555] transition-colors hover:bg-[#f0ecf9] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none motion-reduce:transition-none"
            >
              <span
                className="material-symbols-outlined text-[20px]"
                aria-hidden="true"
              >
                close
              </span>
            </button>
          </div>

          <div className="border-b border-[#e4e1ee] bg-[#faf9ff] px-5 py-3">
            <div className="grid gap-2 text-[11px] text-[#6a6780] sm:grid-cols-2 xl:grid-cols-3">
              {sourceSummary.map((item) => (
                <div key={item.label} className="min-w-0">
                  <p className="text-[9px] font-bold tracking-[0.16em] uppercase">
                    {item.label}
                  </p>
                  <p className="truncate text-[#1b1b24]" title={item.value}>
                    {item.value}
                  </p>
                </div>
              ))}
            </div>
            <p
              id={helpTextId}
              className="mt-3 text-[11px] leading-relaxed text-[#6a6780]"
            >
              {t("keyboardHelp")}
            </p>
            {previewLimitNotice ? (
              <p className="mt-1 text-[11px] text-[#6a6780]">
                {previewLimitNotice}
              </p>
            ) : null}
            {sourceSection ? (
              <p className="mt-2 text-[11px] text-[#6a6780]">
                {t("section", { section: sourceSection })}
              </p>
            ) : null}
          </div>

          {citation.doc_stale_warning ||
          citation.doc_expired_warning ||
          citation.doc_is_excluded_status ||
          citation.doc_unreviewed_warning ||
          citation.doc_deprecated_warning ? (
            <div className="flex shrink-0 items-start gap-2 border-b border-amber-200 bg-amber-50 px-5 py-2.5">
              <span
                className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-amber-600"
                aria-hidden="true"
              >
                warning
              </span>
              <p className="text-[11px] text-amber-800">{t("sourceWarning")}</p>
            </div>
          ) : null}

          {hasSiblings ? (
            <div className="flex shrink-0 items-center justify-between border-b border-[#e4e1ee] bg-[#faf9ff] px-5 py-2">
              <span className="text-[11px] font-semibold text-[#6a6780]">
                {t("position", {
                  current: safeActiveIndex + 1,
                  total: visibleCitations.length,
                })}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={!canGoPrev}
                  onClick={() => setActiveIndex((current) => current - 1)}
                  aria-label={t("previous")}
                  className="rounded p-1 text-[#464555] transition-colors hover:bg-[#f0ecf9] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none"
                >
                  <span
                    className="material-symbols-outlined text-[18px] rtl:rotate-180"
                    aria-hidden="true"
                  >
                    chevron_left
                  </span>
                </button>
                <button
                  type="button"
                  disabled={!canGoNext}
                  onClick={() => setActiveIndex((current) => current + 1)}
                  aria-label={t("next")}
                  className="rounded p-1 text-[#464555] transition-colors hover:bg-[#f0ecf9] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none"
                >
                  <span
                    className="material-symbols-outlined text-[18px] rtl:rotate-180"
                    aria-hidden="true"
                  >
                    chevron_right
                  </span>
                </button>
              </div>
            </div>
          ) : null}

          <div className="shrink-0 border-b border-[#e4e1ee] bg-[#faf9ff] px-5 py-2">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-[#6a6780]">
              {citation.chunk_id ? (
                <span
                  className="font-mono"
                  title={t("chunkId", { id: citation.chunk_id })}
                >
                  {t("chunkShort", { id: citation.chunk_id.slice(0, 8) })}
                </span>
              ) : null}
              {documentLastIndexedAt || doc?.created_at ? (
                <span>
                  {t("indexed", {
                    date: formatDate(documentLastIndexedAt ?? doc?.created_at),
                  })}
                </span>
              ) : null}
              {citation.rerank_score != null ? (
                <span>
                  {t("rerank", { score: formatScore(citation.rerank_score) })}
                </span>
              ) : citation.similarity_score != null ? (
                <span>
                  {t("similarity", {
                    score: formatScore(citation.similarity_score),
                  })}
                </span>
              ) : citation.score != null ? (
                <span>
                  {t("score", { score: formatScore(citation.score) })}
                </span>
              ) : null}
            </div>
          </div>

          {warningMessages.length > 0 ? (
            <div className="flex shrink-0 flex-col gap-2 border-b border-amber-200 bg-amber-50 px-5 py-3">
              {warningMessages.map((message) => (
                <div key={message} className="flex items-start gap-2">
                  <span
                    className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-amber-600"
                    aria-hidden="true"
                  >
                    warning
                  </span>
                  <p className="text-[11px] text-amber-800">{message}</p>
                </div>
              ))}
            </div>
          ) : null}

          <div className="min-h-0 flex-1 overflow-y-auto">
            {!citation.document_id ? (
              <div className="flex min-h-[20vh] flex-col items-center justify-center gap-3 p-8 text-center">
                <span
                  className="material-symbols-outlined text-[36px] text-[#6a6780]"
                  aria-hidden="true"
                >
                  visibility_off
                </span>
                <p className="text-sm font-semibold text-[#1b1b24]">
                  {t("states.citationUnavailable")}
                </p>
                <p className="max-w-sm text-xs text-[#6a6780]">
                  {t("states.citationUnavailableDescription")}
                </p>
              </div>
            ) : isPermissionDenied ? (
              <div className="flex min-h-[20vh] flex-col items-center justify-center gap-3 p-8 text-center">
                <span
                  className="material-symbols-outlined text-[36px] text-amber-500"
                  aria-hidden="true"
                >
                  lock
                </span>
                <p className="text-sm font-semibold text-[#1b1b24]">
                  {t("states.accessRestricted")}
                </p>
                <p className="max-w-sm text-xs text-[#6a6780]">
                  {t("states.accessRestrictedDescription")}
                </p>
                {excerptCard ? (
                  <div className="mt-1 w-full max-w-2xl text-start">
                    {excerptCard}
                  </div>
                ) : null}
              </div>
            ) : isNotFound ? (
              <div className="flex min-h-[20vh] flex-col items-center justify-center gap-3 p-8 text-center">
                <span
                  className="material-symbols-outlined text-[36px] text-[#6a6780]"
                  aria-hidden="true"
                >
                  delete
                </span>
                <p className="text-sm font-semibold text-[#1b1b24]">
                  {t("states.documentUnavailable")}
                </p>
                <p className="max-w-sm text-xs text-[#6a6780]">
                  {t("states.documentUnavailableDescription")}
                </p>
                {excerptCard ? (
                  <div className="mt-1 w-full max-w-2xl text-start">
                    {excerptCard}
                  </div>
                ) : null}
              </div>
            ) : previewFallback ? (
              <div className="flex min-h-[20vh] flex-col items-center justify-center gap-3 p-8 text-center">
                <span
                  className="material-symbols-outlined text-[36px] text-[#6a6780]"
                  aria-hidden="true"
                >
                  {previewFallback.icon}
                </span>
                <p className="text-sm font-semibold text-[#1b1b24]">
                  {previewFallback.title}
                </p>
                <p className="max-w-sm text-xs text-[#6a6780]">
                  {previewFallback.message}
                </p>
                {excerptCard ? (
                  <div className="mt-1 w-full max-w-2xl text-left">
                    {excerptCard}
                  </div>
                ) : null}
                {previewFallback.action ? (
                  <button
                    type="button"
                    onClick={() => void docQuery.refetch()}
                    className="text-xs font-semibold text-[#3525cd] hover:underline focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                  >
                    {previewFallback.action}
                  </button>
                ) : null}
              </div>
            ) : docQuery.isPending ? (
              <div className="flex min-h-[40vh] items-center justify-center p-8">
                <span
                  className="material-symbols-outlined animate-spin text-[32px] text-[#3525cd] motion-reduce:animate-none"
                  aria-label={t("loading")}
                >
                  progress_activity
                </span>
              </div>
            ) : isError ? (
              <div className="flex min-h-[40vh] flex-col items-center justify-center gap-2 p-8 text-center">
                <p className="text-sm text-[#777587]">
                  {t("states.loadFailed")}
                </p>
                {excerptCard ? (
                  <div className="w-full max-w-2xl text-start">
                    {excerptCard}
                  </div>
                ) : null}
                <button
                  type="button"
                  onClick={() => void docQuery.refetch()}
                  className="text-xs font-semibold text-[#3525cd] hover:underline focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                >
                  {t("tryAgain")}
                </button>
              </div>
            ) : (
              <div className="space-y-3 p-5">
                <div className="rounded-xl border border-[#e4e1ee] bg-[#faf9ff] p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
                    {citation.page_number != null ? (
                      <span>{t("page", { page: citation.page_number })}</span>
                    ) : null}
                    {citation.chunk_id ? (
                      <span className="font-mono">
                        {t("chunk", { id: citation.chunk_id.slice(0, 8) })}
                      </span>
                    ) : null}
                    {sourceSection ? (
                      <span className="truncate" title={sourceSection}>
                        {sourceSection}
                      </span>
                    ) : null}
                  </div>
                  {excerptCard ? (
                    <div className="rounded-lg border border-[#d9d5ec] bg-white p-3">
                      {excerptCard}
                    </div>
                  ) : (
                    <div className="rounded-lg border border-[#d9d5ec] bg-white p-3 text-sm text-[#6a6780]">
                      {t("states.pageUnavailable")}
                    </div>
                  )}
                </div>

                {citation.is_table_chunk ? (
                  <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800">
                    <p className="font-semibold tracking-wide uppercase">
                      {t("table.title")}
                    </p>
                    <p className="mt-1">
                      {citation.table_caption
                        ? citation.table_caption
                        : t("table.extraction")}
                      {citation.table_row_count != null ||
                      citation.table_col_count != null ? (
                        <>
                          {" "}
                          {t("table.dimensions", {
                            rows: citation.table_row_count ?? "?",
                            columns: citation.table_col_count ?? "?",
                          })}
                        </>
                      ) : null}
                    </p>
                    {citation.table_headers?.length ? (
                      <p className="mt-1">
                        {t("table.headers", {
                          headers: citation.table_headers.join(", "),
                        })}
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            )}
          </div>

          <div className="border-t border-[#e4e1ee] bg-white p-4">
            <div className="mb-3 grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => void handleCopySourceLink()}
                disabled={!copyLink}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#d2cee6] bg-white px-4 py-3 text-sm font-semibold text-[#3e376f] transition-colors hover:bg-[#f5f3ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
              >
                <span
                  className="material-symbols-outlined text-[18px]"
                  aria-hidden="true"
                >
                  content_copy
                </span>
                {copied ? t("copied") : t("copySourceLink")}
              </button>
              <button
                type="button"
                onClick={() => void downloadMutation.mutate()}
                disabled={!canDownload}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#d2cee6] bg-white px-4 py-3 text-sm font-semibold text-[#3e376f] transition-colors hover:bg-[#f5f3ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
              >
                <span
                  className="material-symbols-outlined text-[18px]"
                  aria-hidden="true"
                >
                  download
                </span>
                {t("downloadOriginal")}
              </button>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              {sourceLink ? (
                <a
                  href={sourceLink}
                  target="_blank"
                  rel="noreferrer"
                  onClick={handleOpenSourceLink}
                  aria-label={t("openSourceLabel", {
                    filename: displayFilename,
                  })}
                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-[#d2cee6] bg-white px-4 py-3 text-sm font-semibold text-[#3e376f] transition-colors hover:bg-[#f5f3ff] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none motion-reduce:transition-none"
                >
                  <span
                    className="material-symbols-outlined text-[18px]"
                    aria-hidden="true"
                  >
                    open_in_new
                  </span>
                  {t("openSource")}
                </a>
              ) : sourceProviderKey &&
                sourceProviderKey.toLowerCase() !== "upload" ? (
                <p className="rounded-xl border border-dashed border-[#d2cee6] px-4 py-3 text-center text-xs text-[#777587] sm:flex-1">
                  {t("connectorLinkUnavailable")}
                </p>
              ) : null}
              {viewInDocsHref ? (
                <Link
                  href={viewInDocsHref}
                  aria-label={t("viewDocumentsLabel", {
                    filename: displayFilename,
                  })}
                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-[#3525cd] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none motion-reduce:transition-none"
                >
                  <span
                    className="material-symbols-outlined text-[18px]"
                    aria-hidden="true"
                  >
                    open_in_new
                  </span>
                  {t("viewDocuments")}
                </Link>
              ) : (
                <p className="rounded-xl border border-[#d2cee6] px-4 py-3 text-center text-xs text-[#777587] sm:flex-1">
                  {t("documentLinkUnavailable")}
                </p>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

export const DocumentPreviewModal = CitationPreviewDrawer;
