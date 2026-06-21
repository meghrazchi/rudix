"use client";

import { useEffect, useRef, useState } from "react";

import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";

import type { ChatCitationResponse } from "@/lib/api/chat";
import {
  downloadDocumentFile,
  getDocument,
  getDocumentChunks,
} from "@/lib/api/documents";
import { isApiClientError } from "@/lib/api/errors";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

type Props = {
  citations: ChatCitationResponse[];
  initialIndex?: number;
  onClose: () => void;
};

type SplitResult = {
  before: string;
  match: string;
  after: string;
  exact: boolean;
};

function splitOnSnippet(
  text: string,
  snippet: string,
  startOffset?: number | null,
  endOffset?: number | null,
): SplitResult | null {
  if (!snippet && startOffset == null) return null;

  // Use persisted offsets when available — most precise.
  if (startOffset != null && endOffset != null && endOffset > startOffset) {
    const clamped = Math.min(endOffset, text.length);
    return {
      before: text.slice(0, startOffset),
      match: text.slice(startOffset, clamped),
      after: text.slice(clamped),
      exact: true,
    };
  }

  if (!snippet) return null;

  // Case-insensitive substring fallback.
  const idx = text.toLowerCase().indexOf(snippet.toLowerCase());
  if (idx !== -1) {
    return {
      before: text.slice(0, idx),
      match: text.slice(idx, idx + snippet.length),
      after: text.slice(idx + snippet.length),
      exact: true,
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

function fileTypeIcon(fileType: string): string {
  if (fileType === "pdf") return "picture_as_pdf";
  if (fileType === "docx") return "description";
  return "notes";
}

function fileTypeLabel(fileType: string): string {
  if (fileType === "pdf") return "PDF";
  if (fileType === "docx") return "DOCX";
  if (fileType === "txt") return "Plain text";
  return fileType.toUpperCase();
}

function extractionNote(fileType: string): string | null {
  if (fileType === "pdf") return "Extracted text from PDF";
  if (fileType === "docx") return "Extracted text from DOCX";
  return null;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatScore(value: number | null | undefined): string {
  if (value == null) return "-";
  return value.toFixed(3);
}

function freshnessBadge(
  citation: ChatCitationResponse,
): { label: string; className: string } | null {
  const status = citation.doc_review_status ?? null;
  if (citation.doc_expired_warning || status === "expired") {
    return {
      label: "Expired",
      className:
        "rounded bg-rose-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-rose-800 uppercase",
    };
  }
  if (status === "stale") {
    return {
      label: "Stale",
      className:
        "rounded bg-orange-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-orange-800 uppercase",
    };
  }
  if (status === "needs_review") {
    return {
      label: "Needs review",
      className:
        "rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-amber-800 uppercase",
    };
  }
  if (status === "archived") {
    return {
      label: "Archived",
      className:
        "rounded bg-slate-200 px-1.5 py-0.5 font-mono text-[10px] font-bold text-slate-700 uppercase",
    };
  }
  if (status) {
    return {
      label: status.replaceAll("_", " "),
      className:
        "rounded bg-sky-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-sky-800 uppercase",
    };
  }
  return null;
}

export function DocumentPreviewModal({
  citations,
  initialIndex = 0,
  onClose,
}: Props) {
  const [activeIndex, setActiveIndex] = useState(
    Math.min(initialIndex, Math.max(0, citations.length - 1)),
  );
  const containerRef = useRef<HTMLDivElement | null>(null);
  const highlightedChunkRef = useRef<HTMLDivElement | null>(null);

  const citation = citations[activeIndex] ?? citations[0];

  useOverlayFocus({ isOpen: true, containerRef, onClose });

  const docQuery = useQuery({
    queryKey: ["document-preview-detail", citation.document_id],
    queryFn: () => getDocument(citation.document_id),
    enabled: Boolean(citation.document_id),
  });

  const chunksQuery = useQuery({
    queryKey: ["document-chunks-preview", citation.document_id],
    queryFn: () =>
      getDocumentChunks(citation.document_id, {
        limit: 100,
        include_full_text: true,
      }),
    enabled: Boolean(citation.document_id),
  });

  const downloadMutation = useMutation({
    mutationFn: () => downloadDocumentFile(citation.document_id),
    onSuccess: (blob) => {
      const filename =
        citation.filename?.trim() || `document-${citation.document_id}`;
      triggerBlobDownload(blob, filename);
    },
  });

  useEffect(() => {
    if (!chunksQuery.data || !highlightedChunkRef.current) return;
    highlightedChunkRef.current.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, [chunksQuery.data, activeIndex]);

  const doc = docQuery.data;
  const isDocRestricted =
    isApiClientError(docQuery.error) && docQuery.error.status === 403;
  const isDocDeleted =
    isApiClientError(docQuery.error) && docQuery.error.status === 404;
  const isChunksRestricted =
    isApiClientError(chunksQuery.error) && chunksQuery.error.status === 403;
  const isChunksDeleted =
    isApiClientError(chunksQuery.error) && chunksQuery.error.status === 404;
  const isUnavailable =
    isDocRestricted || isDocDeleted || isChunksRestricted || isChunksDeleted;

  const displayFileType = doc?.file_type ?? null;
  const displayFilename = citation.filename ?? doc?.filename ?? "Document";
  const displayStatus = doc?.status ?? null;
  const canDownload =
    !isDocDeleted && !isDocRestricted && !downloadMutation.isPending;
  const sourceProvider =
    citation.source_provider_label ?? citation.source_provider ?? null;
  const sourceSection = citation.source_section ?? null;
  const sourceTrust = citation.source_trust_status ?? null;
  const freshness = freshnessBadge(citation);
  const ocrQualityStatus = citation.doc_ocr_quality_status ?? null;
  const ocrLowConfidence = citation.doc_ocr_low_confidence_warning ?? false;

  const hasSiblings = citations.length > 1;
  const canGoPrev = activeIndex > 0;
  const canGoNext = activeIndex < citations.length - 1;

  const viewInDocsHref = citation.document_id
    ? `/documents/${encodeURIComponent(citation.document_id)}` +
      `?chunk_id=${encodeURIComponent(citation.chunk_id)}` +
      (citation.text_snippet
        ? `&snippet=${encodeURIComponent(citation.text_snippet)}`
        : "") +
      (citation.page_number != null
        ? `&page=${encodeURIComponent(String(citation.page_number))}`
        : "") +
      `&back=${encodeURIComponent("/chat")}`
    : null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#1f1a3f]/50 p-4">
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Preview: ${displayFilename}`}
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
      >
        {/* Header */}
        <div className="flex shrink-0 items-center gap-3 border-b border-[#e4e1ee] px-5 py-4">
          <span
            className={`material-symbols-outlined shrink-0 text-[24px] ${displayFileType ? "text-[#3525cd]" : "text-[#6a6780]"}`}
            aria-hidden="true"
          >
            {displayFileType ? fileTypeIcon(displayFileType) : "article"}
          </span>
          <div className="min-w-0 flex-1">
            <h2
              className="truncate text-base font-semibold text-[#1b1b24]"
              title={displayFilename}
            >
              {displayFilename}
            </h2>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              {displayFileType ? (
                <span className="rounded bg-[#f0ecf9] px-1.5 py-0.5 font-mono text-[10px] font-bold text-[#3525cd] uppercase">
                  {fileTypeLabel(displayFileType)}
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
              {sourceTrust ? (
                <span className="rounded bg-[#f0ecf9] px-1.5 py-0.5 font-mono text-[10px] font-bold text-[#5d58a8] uppercase">
                  {sourceTrust}
                </span>
              ) : null}
              {freshness ? (
                <span className={freshness.className}>{freshness.label}</span>
              ) : null}
              {ocrQualityStatus && ocrQualityStatus !== "not_required" ? (
                <span
                  className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase ${
                    ocrQualityStatus === "high"
                      ? "bg-emerald-50 text-emerald-700"
                      : ocrQualityStatus === "medium"
                        ? "bg-amber-50 text-amber-700"
                        : "bg-red-50 text-red-700"
                  }`}
                  title={`OCR quality: ${ocrQualityStatus}`}
                >
                  OCR {ocrQualityStatus}
                </span>
              ) : null}
              {citation.page_number != null ? (
                <span className="font-mono text-xs text-[#6a6780]">
                  Page {citation.page_number}
                </span>
              ) : null}
              {displayStatus === "indexed" ? (
                <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-800 uppercase">
                  indexed
                </span>
              ) : displayStatus ? (
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
            aria-label="Close preview"
            className="ml-2 shrink-0 cursor-pointer rounded-full p-1.5 text-[#464555] transition-colors hover:bg-[#f0ecf9] focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
          >
            <span
              className="material-symbols-outlined text-[20px]"
              aria-hidden="true"
            >
              close
            </span>
          </button>
        </div>

        {sourceSection ||
        citation.source_last_synced_at ||
        citation.source_deep_link ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[#e4e1ee] bg-[#faf9ff] px-5 py-2 text-[11px] text-[#6a6780]">
            {sourceSection ? <span>Section: {sourceSection}</span> : null}
            {citation.source_last_synced_at ? (
              <span>Synced {formatDate(citation.source_last_synced_at)}</span>
            ) : null}
            {citation.source_deep_link ? (
              <a
                href={citation.source_deep_link}
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

        {/* Citation navigation */}
        {hasSiblings ? (
          <div className="flex shrink-0 items-center justify-between border-b border-[#e4e1ee] bg-[#faf9ff] px-5 py-2">
            <span className="text-[11px] font-semibold text-[#6a6780]">
              Citation {activeIndex + 1} of {citations.length}
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={!canGoPrev}
                onClick={() => setActiveIndex((i) => i - 1)}
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
                onClick={() => setActiveIndex((i) => i + 1)}
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

        {/* Metadata strip */}
        {citation.chunk_id ||
        doc?.created_at ||
        citation.rerank_score != null ||
        citation.similarity_score != null ||
        citation.score != null ? (
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
        ) : null}

        {/* Cited passage banner */}
        {citation.text_snippet ? (
          <div className="shrink-0 border-b border-[#e4e1ee] bg-[#f5f2ff] px-5 py-3">
            <p className="mb-1.5 text-[10px] font-bold tracking-wide text-[#3525cd] uppercase">
              Cited passage
            </p>
            <p className="rounded-r border-l-4 border-[#3525cd] bg-white py-2 pr-2 pl-3 text-sm text-[#1b1b24] italic">
              {citation.text_snippet}
            </p>
          </div>
        ) : null}

        {/* OCR low-confidence warning */}
        {ocrLowConfidence ? (
          <div className="flex shrink-0 items-start gap-2 border-b border-amber-200 bg-amber-50 px-5 py-2.5">
            <span
              className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-amber-600"
              aria-hidden="true"
            >
              warning
            </span>
            <p className="text-[11px] text-amber-800">
              This source was extracted via low-confidence OCR. The text may
              contain errors and the answer reliability may be reduced.
            </p>
          </div>
        ) : null}

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {/* Restricted */}
          {(isDocRestricted || isChunksRestricted) && !chunksQuery.data ? (
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
            </div>
          ) : (isDocDeleted || isChunksDeleted) && !chunksQuery.data ? (
            /* Deleted / not found */
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
            </div>
          ) : chunksQuery.isPending ? (
            /* Loading */
            <div className="flex min-h-[40vh] items-center justify-center p-8">
              <span
                className="material-symbols-outlined animate-spin text-[32px] text-[#3525cd]"
                aria-label="Loading"
              >
                progress_activity
              </span>
            </div>
          ) : chunksQuery.isError && !isUnavailable ? (
            /* Generic error */
            <div className="flex min-h-[40vh] flex-col items-center justify-center gap-2 p-8 text-center">
              <p className="text-sm text-[#777587]">
                Failed to load document content.
              </p>
              <button
                type="button"
                onClick={() => void chunksQuery.refetch()}
                className="text-xs font-semibold text-[#3525cd] hover:underline"
              >
                Try again
              </button>
            </div>
          ) : chunksQuery.data ? (
            /* Chunks */
            <div className="space-y-2 p-5">
              {displayFileType && extractionNote(displayFileType) ? (
                <p className="text-[10px] font-semibold tracking-wide text-[#6a6780] uppercase">
                  {extractionNote(displayFileType)}
                </p>
              ) : null}
              {chunksQuery.data.total > chunksQuery.data.items.length ? (
                <p className="mb-1 text-[10px] tracking-wide text-[#6a6780] uppercase">
                  Showing {chunksQuery.data.items.length} of{" "}
                  {chunksQuery.data.total} passages
                </p>
              ) : null}
              {chunksQuery.data.items.map((chunk) => {
                const isHighlighted = chunk.chunk_id === citation.chunk_id;
                const chunkText = chunk.text ?? chunk.text_preview;
                const parts = isHighlighted
                  ? splitOnSnippet(
                      chunkText,
                      citation.text_snippet ?? "",
                      citation.start_offset,
                      citation.end_offset,
                    )
                  : null;

                return (
                  <div
                    key={chunk.chunk_id}
                    ref={isHighlighted ? highlightedChunkRef : undefined}
                    className={`rounded-lg p-3 font-serif text-sm leading-relaxed text-[#1b1b24] transition-colors ${
                      isHighlighted
                        ? "border border-[#3525cd]/30 bg-[#f0ecff] shadow-sm"
                        : "bg-[#faf9ff]"
                    }`}
                  >
                    {isHighlighted && chunk.page_number != null ? (
                      <p className="mb-1 font-sans text-[10px] font-semibold tracking-wide text-[#3525cd] uppercase">
                        Page {chunk.page_number}
                      </p>
                    ) : null}
                    {isHighlighted && citation.is_table_chunk ? (
                      <div className="font-sans">
                        <div className="mb-2 flex items-center gap-1.5">
                          <span
                            className="material-symbols-outlined text-[14px] text-[#3525cd]"
                            aria-hidden="true"
                          >
                            table_chart
                          </span>
                          <span className="text-[10px] font-semibold tracking-wide text-[#3525cd] uppercase">
                            Table chunk
                          </span>
                        </div>
                        {citation.table_caption ? (
                          <p className="mb-1 text-xs font-semibold text-[#1b1b24]">
                            {citation.table_caption}
                          </p>
                        ) : null}
                        {citation.table_section_context ? (
                          <p className="mb-2 text-[11px] text-[#6a6780]">
                            Section: {citation.table_section_context}
                          </p>
                        ) : null}
                        {citation.table_headers &&
                        citation.table_headers.length > 0 ? (
                          <div className="mb-2 overflow-x-auto rounded border border-[#cbc5e6]">
                            <table className="min-w-full text-[11px]">
                              <thead>
                                <tr className="bg-[#ede9ff]">
                                  {citation.table_headers.map((h, i) => (
                                    <th
                                      key={i}
                                      className="border-r border-[#cbc5e6] px-2 py-1 text-left font-semibold text-[#3e376f] last:border-r-0"
                                    >
                                      {h}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                            </table>
                          </div>
                        ) : null}
                        <div className="flex gap-3 text-[10px] text-[#6a6780]">
                          {citation.table_row_count != null ? (
                            <span>{citation.table_row_count} rows</span>
                          ) : null}
                          {citation.table_col_count != null ? (
                            <span>{citation.table_col_count} columns</span>
                          ) : null}
                        </div>
                        {chunkText ? (
                          <details className="mt-2">
                            <summary className="cursor-pointer text-[10px] text-[#6a6780] hover:text-[#3525cd]">
                              Show raw text
                            </summary>
                            <p className="mt-1 font-serif text-xs leading-relaxed text-[#1b1b24]">
                              {chunkText}
                            </p>
                          </details>
                        ) : null}
                      </div>
                    ) : parts ? (
                      <p>
                        {parts.before}
                        <mark className="rounded bg-[#3525cd]/20 px-0.5 font-bold text-[#3525cd] not-italic">
                          {parts.match}
                        </mark>
                        {parts.after}
                      </p>
                    ) : isHighlighted ? (
                      <>
                        <p>{chunkText}</p>
                        <p className="mt-2 font-sans text-[10px] text-[#6a6780] italic">
                          Exact highlight unavailable — passage is shown in
                          full.
                        </p>
                      </>
                    ) : (
                      <p>{chunkText}</p>
                    )}
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="flex shrink-0 items-center justify-between border-t border-[#e4e1ee] bg-white px-5 py-3">
          <button
            type="button"
            disabled={!canDownload}
            onClick={() => downloadMutation.mutate()}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded border border-[#cbc5e6] px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span
              className="material-symbols-outlined text-[16px]"
              aria-hidden="true"
            >
              download
            </span>
            {downloadMutation.isPending ? "Downloading…" : "Download original"}
          </button>
          {viewInDocsHref ? (
            <Link
              href={viewInDocsHref}
              onClick={onClose}
              className="inline-flex items-center gap-1.5 rounded bg-[#3525cd] px-3 py-2 text-xs font-semibold text-white hover:bg-[#2b1fa8]"
            >
              <span
                className="material-symbols-outlined text-[16px]"
                aria-hidden="true"
              >
                open_in_new
              </span>
              View in Documents
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}
