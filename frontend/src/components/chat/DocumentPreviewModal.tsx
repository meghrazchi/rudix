"use client";

import { useEffect, useRef } from "react";

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
  citation: ChatCitationResponse;
  onClose: () => void;
};

function splitOnSnippet(
  text: string,
  snippet: string,
): { before: string; match: string; after: string } | null {
  if (!snippet) return null;
  const idx = text.toLowerCase().indexOf(snippet.toLowerCase());
  if (idx === -1) return null;
  return {
    before: text.slice(0, idx),
    match: text.slice(idx, idx + snippet.length),
    after: text.slice(idx + snippet.length),
  };
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

export function DocumentPreviewModal({ citation, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const highlightedChunkRef = useRef<HTMLDivElement | null>(null);

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
  }, [chunksQuery.data]);

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
  const displayFilename =
    citation.filename ?? doc?.filename ?? "Document";
  const displayStatus = doc?.status ?? null;
  const canDownload =
    !isDocDeleted && !isDocRestricted && !downloadMutation.isPending;

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
                <span className="rounded bg-[#f0ecf9] px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-[#3525cd]">
                  {fileTypeLabel(displayFileType)}
                </span>
              ) : null}
              {citation.page_number != null ? (
                <span className="font-mono text-xs text-[#6a6780]">
                  Page {citation.page_number}
                </span>
              ) : null}
              {displayStatus === "indexed" ? (
                <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-emerald-800">
                  indexed
                </span>
              ) : displayStatus ? (
                <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-slate-600">
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
            className="ml-2 shrink-0 rounded-full p-1.5 text-[#464555] transition-colors hover:bg-[#f0ecf9]"
          >
            <span
              className="material-symbols-outlined text-[20px]"
              aria-hidden="true"
            >
              close
            </span>
          </button>
        </div>

        {/* Metadata strip */}
        {(citation.chunk_id ||
          doc?.created_at ||
          citation.rerank_score != null ||
          citation.similarity_score != null ||
          citation.score != null) ? (
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
            <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wide text-[#3525cd]">
              Cited passage
            </p>
            <p className="rounded-r border-l-4 border-[#3525cd] bg-white py-2 pl-3 pr-2 text-sm italic text-[#1b1b24]">
              {citation.text_snippet}
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
                <p className="text-[10px] font-semibold uppercase tracking-wide text-[#6a6780]">
                  {extractionNote(displayFileType)}
                </p>
              ) : null}
              {chunksQuery.data.total > chunksQuery.data.items.length ? (
                <p className="mb-1 text-[10px] uppercase tracking-wide text-[#6a6780]">
                  Showing {chunksQuery.data.items.length} of{" "}
                  {chunksQuery.data.total} passages
                </p>
              ) : null}
              {chunksQuery.data.items.map((chunk) => {
                const isHighlighted = chunk.chunk_id === citation.chunk_id;
                const chunkText = chunk.text ?? chunk.text_preview;
                const parts =
                  isHighlighted && citation.text_snippet
                    ? splitOnSnippet(chunkText, citation.text_snippet)
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
                      <p className="mb-1 font-sans text-[10px] font-semibold uppercase tracking-wide text-[#3525cd]">
                        Page {chunk.page_number}
                      </p>
                    ) : null}
                    {parts ? (
                      <p>
                        {parts.before}
                        <mark className="rounded bg-[#3525cd]/20 px-0.5 font-bold not-italic text-[#3525cd]">
                          {parts.match}
                        </mark>
                        {parts.after}
                      </p>
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
            className="inline-flex items-center gap-1.5 rounded border border-[#cbc5e6] px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
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
