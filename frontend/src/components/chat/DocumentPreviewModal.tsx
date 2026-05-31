"use client";

import { useEffect, useRef } from "react";

import { useQuery } from "@tanstack/react-query";

import type { ChatCitationResponse } from "@/lib/api/chat";
import { getDocumentChunks } from "@/lib/api/documents";
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

export function DocumentPreviewModal({ citation, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const highlightedChunkRef = useRef<HTMLDivElement | null>(null);

  useOverlayFocus({ isOpen: true, containerRef, onClose });

  const chunksQuery = useQuery({
    queryKey: ["document-chunks-preview", citation.document_id],
    queryFn: () =>
      getDocumentChunks(citation.document_id, {
        limit: 100,
        include_full_text: true,
      }),
    enabled: Boolean(citation.document_id),
  });

  useEffect(() => {
    if (!chunksQuery.data || !highlightedChunkRef.current) return;
    highlightedChunkRef.current.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, [chunksQuery.data]);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#1f1a3f]/50 p-4">
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Preview: ${citation.filename ?? "Document"}`}
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-2xl"
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-[#e4e1ee] px-5 py-4">
          <div className="min-w-0">
            <h2
              className="truncate text-base font-semibold text-[#1b1b24]"
              title={citation.filename ?? "Document Preview"}
            >
              {citation.filename ?? "Document Preview"}
            </h2>
            {citation.page_number ? (
              <p className="font-mono text-xs text-[#6a6780]">
                Page {citation.page_number}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            data-overlay-autofocus="true"
            aria-label="Close preview"
            className="ml-3 shrink-0 rounded-full p-1.5 text-[#464555] transition-colors hover:bg-[#f0ecf9]"
          >
            <span
              className="material-symbols-outlined text-[20px]"
              aria-hidden="true"
            >
              close
            </span>
          </button>
        </div>

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

        {/* Document chunks body */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {chunksQuery.isPending ? (
            <div className="flex min-h-[40vh] items-center justify-center p-8">
              <span
                className="material-symbols-outlined animate-spin text-[32px] text-[#3525cd]"
                aria-label="Loading"
              >
                progress_activity
              </span>
            </div>
          ) : chunksQuery.isError ? (
            <div className="flex min-h-[40vh] items-center justify-center p-8 text-sm text-[#777587]">
              Failed to load document content.
            </div>
          ) : (
            <div className="space-y-2 p-5">
              {chunksQuery.data.total > chunksQuery.data.items.length ? (
                <p className="mb-3 font-sans text-[10px] uppercase tracking-wide text-[#6a6780]">
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
          )}
        </div>
      </div>
    </div>
  );
}
