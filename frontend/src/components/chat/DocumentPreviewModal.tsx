"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";

import { downloadDocumentFile, getDocument } from "@/lib/api/documents";
import { isApiClientError } from "@/lib/api/errors";
import { copyToClipboard } from "@/lib/export-utils";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

type CitationPreviewItem = {
  document_id: string;
  chunk_id: string | null;
  filename?: string | null;
  source_title?: string | null;
  source_provider?: string | null;
  source_provider_label?: string | null;
  source_key?: string | null;
  source_section?: string | null;
  source_deep_link?: string | null;
  source_last_synced_at?: string | null;
  source_trust_status?: string | null;
  doc_review_status?: string | null;
  doc_expired_warning?: boolean | null;
  doc_stale_warning?: boolean | null;
  doc_is_excluded_status?: boolean | null;
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

function sourceFreshnessBadge(
  citation: CitationPreviewItem,
): { label: string; className: string } | null {
  const trust =
    citation.doc_review_status ?? citation.source_trust_status ?? null;
  if (citation.doc_expired_warning || trust === "expired") {
    return {
      label: "Expired",
      className:
        "rounded bg-rose-100 px-1.5 py-0.5 text-[9px] font-semibold text-rose-800 uppercase",
    };
  }
  if (trust === "stale" || citation.doc_stale_warning) {
    return {
      label: "Stale",
      className:
        "rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  }
  if (trust === "archived") {
    return {
      label: "Archived",
      className:
        "rounded bg-slate-200 px-1.5 py-0.5 text-[9px] font-semibold text-slate-700 uppercase",
    };
  }
  if (trust === "needs_review") {
    return {
      label: "Needs review",
      className:
        "rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-800 uppercase",
    };
  }
  return null;
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

export function CitationPreviewDrawer({
  citations,
  initialIndex = 0,
  onClose,
}: Props) {
  const [activeIndex, setActiveIndex] = useState(
    Math.min(initialIndex, Math.max(0, citations.length - 1)),
  );
  const [copied, setCopied] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!copied) return;
    const timeout = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timeout);
  }, [copied]);

  useOverlayFocus({ isOpen: true, containerRef, onClose });

  const maxIndex = Math.max(0, citations.length - 1);
  const safeActiveIndex = Math.min(activeIndex, maxIndex);
  const citation = citations[safeActiveIndex] ?? citations[0];

  const docQuery = useQuery({
    queryKey: ["citation-preview", "document", citation.document_id],
    queryFn: () => getDocument(citation.document_id),
    enabled: Boolean(citation.document_id),
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
    citation.source_title ?? citation.filename ?? doc?.filename ?? "Document";
  const displayFileType = doc?.file_type ?? null;
  const displayStatus = doc?.status ?? null;
  const displayLanguage = doc?.language?.trim().toUpperCase() ?? null;
  const sourceProvider =
    citation.source_provider_label ?? citation.source_provider ?? null;
  const freshness = sourceFreshnessBadge(citation);
  const sourceSection = citation.source_section ?? null;
  const sourceLink = citation.source_deep_link ?? null;

  const viewInDocsHref =
    citation.document_id && citation.chunk_id != null
      ? `/documents/${encodeURIComponent(citation.document_id)}` +
        `?chunk_id=${encodeURIComponent(citation.chunk_id)}` +
        (citation.page_number != null
          ? `&page=${encodeURIComponent(String(citation.page_number))}`
          : "") +
        `&back=${encodeURIComponent("/chat")}`
      : null;

  const copyLink = sourceLink ?? viewInDocsHref;
  const canDownload = Boolean(
    citation.document_id &&
    !downloadMutation.isPending &&
    !(
      (isApiClientError(docQuery.error) && docQuery.error.status === 403) ||
      (isApiClientError(docQuery.error) && docQuery.error.status === 404)
    ),
  );
  const hasSiblings = citations.length > 1;
  const canGoPrev = activeIndex > 0;
  const canGoNext = activeIndex < citations.length - 1;

  const isPermissionDenied =
    isApiClientError(docQuery.error) && docQuery.error.status === 403;
  const isNotFound =
    isApiClientError(docQuery.error) && docQuery.error.status === 404;
  const isError = docQuery.isError && !isPermissionDenied && !isNotFound;

  const highlightText = citation.text_snippet?.trim() ?? "";
  const highlightUnavailable = highlightText.length > 0;

  const warningMessages = [
    citation.doc_ocr_low_confidence_warning
      ? "This source was extracted via low-confidence OCR. The text may contain errors and the answer reliability may be reduced."
      : null,
    citation.table_low_confidence_warning ||
    (citation.table_extraction_confidence != null &&
      citation.table_extraction_confidence < 0.4)
      ? "This citation comes from a low-confidence table extraction, so the highlighted passage may be incomplete."
      : null,
    citation.doc_extraction_warning
      ? "This source had extraction quality issues, so the evidence preview may be incomplete or noisy."
      : null,
    citation.doc_processing_warning
      ? "This source was only partially processed, so some surrounding text may be unavailable."
      : null,
  ].filter((message): message is string => Boolean(message));
  const excerptCard = highlightText ? (
    <div className="rounded-xl border border-[#e4e1ee] bg-[#faf9ff] p-3">
      <p className="mb-1 text-[10px] font-bold tracking-[0.14em] text-[#5d58a8] uppercase">
        Cited excerpt
      </p>
      <p
        lang={displayLanguage?.toLowerCase() ?? undefined}
        className="text-sm leading-relaxed whitespace-pre-wrap text-[#1b1b24]"
      >
        <mark className="rounded bg-[#f7e7a9] px-0.5">{highlightText}</mark>
      </p>
      {highlightUnavailable ? (
        <p className="mt-2 text-xs text-[#6a6780]">
          Exact highlight unavailable. Showing the cited excerpt as received.
        </p>
      ) : null}
    </div>
  ) : null;

  async function handleCopySourceLink(): Promise<void> {
    if (!copyLink) return;
    await copyToClipboard(copyLink);
    setCopied(true);
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
          aria-label={`Citation preview: ${displayFilename}`}
          onClick={(event) => event.stopPropagation()}
          onKeyDown={handleKeyDown}
          className="flex h-full w-full max-w-none flex-col overflow-hidden rounded-none border-l border-[#d7d4e8] bg-white shadow-2xl sm:max-w-[48rem] sm:rounded-l-2xl"
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
                Citation preview
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
                  <span className={freshness.className}>{freshness.label}</span>
                ) : null}
                {citation.doc_ocr_quality_status &&
                citation.doc_ocr_quality_status !== "not_required" ? (
                  <span className="rounded bg-[#f7f5ff] px-1.5 py-0.5 text-[10px] font-semibold text-[#5d58a8] uppercase">
                    OCR {citation.doc_ocr_quality_status}
                  </span>
                ) : null}
                {citation.page_number != null ? (
                  <span className="font-mono text-xs text-[#6a6780]">
                    Page {citation.page_number}
                  </span>
                ) : null}
                {displayStatus ? (
                  <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-600 uppercase">
                    {displayStatus}
                  </span>
                ) : null}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              data-overlay-autofocus="true"
              aria-label="Close citation preview"
              className="ml-2 shrink-0 rounded-full p-1.5 text-[#464555] transition-colors hover:bg-[#f0ecf9] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
            >
              <span
                className="material-symbols-outlined text-[20px]"
                aria-hidden="true"
              >
                close
              </span>
            </button>
          </div>

          {sourceSection || citation.source_last_synced_at || sourceLink ? (
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[#e4e1ee] bg-[#faf9ff] px-5 py-2 text-[11px] text-[#6a6780]">
              {sourceSection ? <span>Section: {sourceSection}</span> : null}
              {citation.source_last_synced_at ? (
                <span>Synced {formatDate(citation.source_last_synced_at)}</span>
              ) : null}
              {sourceLink ? (
                <a
                  href={sourceLink}
                  target="_blank"
                  rel="noreferrer"
                  className="font-semibold text-[#3525cd] hover:underline"
                >
                  Open source
                </a>
              ) : null}
            </div>
          ) : null}

          {citation.doc_stale_warning ||
          citation.doc_expired_warning ||
          citation.doc_is_excluded_status ? (
            <div className="flex shrink-0 items-start gap-2 border-b border-amber-200 bg-amber-50 px-5 py-2.5">
              <span
                className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-amber-600"
                aria-hidden="true"
              >
                warning
              </span>
              <p className="text-[11px] text-amber-800">
                This citation references a stale, expired, or archived source.
              </p>
            </div>
          ) : null}

          {hasSiblings ? (
            <div className="flex shrink-0 items-center justify-between border-b border-[#e4e1ee] bg-[#faf9ff] px-5 py-2">
              <span className="text-[11px] font-semibold text-[#6a6780]">
                Citation {safeActiveIndex + 1} of {citations.length}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={!canGoPrev}
                  onClick={() => setActiveIndex((current) => current - 1)}
                  aria-label="Previous citation"
                  className="rounded p-1 text-[#464555] transition-colors hover:bg-[#f0ecf9] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <span
                    className="material-symbols-outlined text-[18px]"
                    aria-hidden="true"
                  >
                    chevron_left
                  </span>
                </button>
                <button
                  type="button"
                  disabled={!canGoNext}
                  onClick={() => setActiveIndex((current) => current + 1)}
                  aria-label="Next citation"
                  className="rounded p-1 text-[#464555] transition-colors hover:bg-[#f0ecf9] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <span
                    className="material-symbols-outlined text-[18px]"
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
                  title={`Chunk ID: ${citation.chunk_id}`}
                >
                  Chunk: {citation.chunk_id.slice(0, 8)}&hellip;
                </span>
              ) : null}
              {doc?.created_at ? (
                <span>Indexed: {formatDate(doc.created_at)}</span>
              ) : null}
              {citation.rerank_score != null ? (
                <span>Rerank: {formatScore(citation.rerank_score)}</span>
              ) : citation.similarity_score != null ? (
                <span>
                  Similarity: {formatScore(citation.similarity_score)}
                </span>
              ) : citation.score != null ? (
                <span>Score: {formatScore(citation.score)}</span>
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
                  Citation unavailable
                </p>
                <p className="max-w-sm text-xs text-[#6a6780]">
                  A safe preview is not available for this citation.
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
                  Access restricted
                </p>
                <p className="max-w-sm text-xs text-[#6a6780]">
                  You do not have permission to view this document. Contact an
                  administrator if you believe this is an error.
                </p>
                {excerptCard ? (
                  <div className="mt-1 w-full max-w-2xl text-left">
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
                  Document unavailable
                </p>
                <p className="max-w-sm text-xs text-[#6a6780]">
                  This document has been deleted or is no longer available.
                </p>
                {excerptCard ? (
                  <div className="mt-1 w-full max-w-2xl text-left">
                    {excerptCard}
                  </div>
                ) : null}
              </div>
            ) : docQuery.isPending ? (
              <div className="flex min-h-[40vh] items-center justify-center p-8">
                <span
                  className="material-symbols-outlined animate-spin text-[32px] text-[#3525cd]"
                  aria-label="Loading"
                >
                  progress_activity
                </span>
              </div>
            ) : isError ? (
              <div className="flex min-h-[40vh] flex-col items-center justify-center gap-2 p-8 text-center">
                <p className="text-sm text-[#777587]">
                  Failed to load citation metadata.
                </p>
                {excerptCard ? (
                  <div className="w-full max-w-2xl text-left">
                    {excerptCard}
                  </div>
                ) : null}
                <button
                  type="button"
                  onClick={() => void docQuery.refetch()}
                  className="text-xs font-semibold text-[#3525cd] hover:underline"
                >
                  Try again
                </button>
              </div>
            ) : (
              <div className="space-y-3 p-5">
                <div className="rounded-xl border border-[#e4e1ee] bg-[#faf9ff] p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
                    {citation.page_number != null ? (
                      <span>Page {citation.page_number}</span>
                    ) : null}
                    {citation.chunk_id ? (
                      <span className="font-mono">
                        Chunk {citation.chunk_id.slice(0, 8)}&hellip;
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
                      Exact page rendering is not available for this source.
                    </div>
                  )}
                </div>

                {citation.is_table_chunk ? (
                  <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800">
                    <p className="font-semibold tracking-wide uppercase">
                      Table evidence
                    </p>
                    <p className="mt-1">
                      {citation.table_caption
                        ? citation.table_caption
                        : "Table extraction"}
                      {citation.table_row_count != null ||
                      citation.table_col_count != null ? (
                        <>
                          {" "}
                          ({citation.table_row_count ?? "?"} rows ×{" "}
                          {citation.table_col_count ?? "?"} columns)
                        </>
                      ) : null}
                    </p>
                    {citation.table_headers?.length ? (
                      <p className="mt-1">
                        Headers: {citation.table_headers.join(", ")}
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
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#d2cee6] bg-white px-4 py-3 text-sm font-semibold text-[#3e376f] transition-colors hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span
                  className="material-symbols-outlined text-[18px]"
                  aria-hidden="true"
                >
                  content_copy
                </span>
                {copied ? "Copied" : "Copy source link"}
              </button>
              <button
                type="button"
                onClick={() => void downloadMutation.mutate()}
                disabled={!canDownload}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#d2cee6] bg-white px-4 py-3 text-sm font-semibold text-[#3e376f] transition-colors hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span
                  className="material-symbols-outlined text-[18px]"
                  aria-hidden="true"
                >
                  download
                </span>
                Download original
              </button>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              {sourceLink ? (
                <a
                  href={sourceLink}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-[#d2cee6] bg-white px-4 py-3 text-sm font-semibold text-[#3e376f] transition-colors hover:bg-[#f5f3ff]"
                >
                  <span
                    className="material-symbols-outlined text-[18px]"
                    aria-hidden="true"
                  >
                    open_in_new
                  </span>
                  Open source
                </a>
              ) : null}
              {viewInDocsHref ? (
                <Link
                  href={viewInDocsHref}
                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-[#3525cd] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8]"
                >
                  <span
                    className="material-symbols-outlined text-[18px]"
                    aria-hidden="true"
                  >
                    open_in_new
                  </span>
                  View in documents
                </Link>
              ) : (
                <p className="rounded-xl border border-[#d2cee6] px-4 py-3 text-center text-xs text-[#777587] sm:flex-1">
                  Document link unavailable.
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
