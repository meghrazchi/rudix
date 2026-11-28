"use client";

import type { DetailSectionProps } from "@/components/documents/detail/useDocumentDetail";

/** Citation evidence callout shown when arriving from a chat citation deep-link. */
export function CitationEvidenceCallout({
  ctl,
  detail,
}: Omit<DetailSectionProps, "currentStatus">) {
  const {
    td,
    highlightedChunkId,
    highlightedSnippet,
    activeTab,
    setActiveTab,
    setPreviewCitationSet,
    highlightedChunk,
  } = ctl;
  if (!highlightedChunkId) {
    return null;
  }
  return (
    <div className="rounded-xl border border-[#3525cd]/30 bg-[#f5f2ff] p-4">
      <div className="mb-2 flex items-center gap-2">
        <span
          className="material-symbols-outlined text-[18px] text-[#3525cd]"
          aria-hidden="true"
        >
          format_quote
        </span>
        <p className="text-xs font-bold tracking-wide text-[#3525cd] uppercase">
          {td("citationEvidence")}
        </p>
      </div>
      {highlightedSnippet ? (
        <p className="rounded-r border-l-4 border-[#3525cd] bg-white py-2 pr-2 pl-3 text-sm text-[#1b1b24] italic">
          {highlightedSnippet}
        </p>
      ) : null}
      <p
        className="mt-2 font-mono text-[10px] text-[#6a6780]"
        title={td("chunkIdTitle", { id: highlightedChunkId })}
      >
        {td("chunkIdShort", {
          id: highlightedChunkId.slice(0, 16),
        })}
      </p>
      <button
        type="button"
        onClick={() => {
          if (!detail || !highlightedChunkId) return;
          setPreviewCitationSet({
            citations: [
              {
                document_id: detail.document_id,
                chunk_id: highlightedChunkId,
                filename: detail.filename,
                page_number: highlightedChunk?.page_number ?? null,
                text_snippet: highlightedSnippet ?? null,
                score: null,
                similarity_score: null,
                rerank_score: null,
              },
            ],
            initialIndex: 0,
          });
        }}
        className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-[#d2cee6] bg-white px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
      >
        <span
          className="material-symbols-outlined text-[15px]"
          aria-hidden="true"
        >
          visibility
        </span>
        {td("previewCitation")}
      </button>
      {activeTab !== "chunks" ? (
        <button
          type="button"
          onClick={() => setActiveTab("chunks")}
          className="mt-2 text-xs font-semibold text-[#3525cd] hover:underline"
        >
          {td("viewInChunks")}
        </button>
      ) : null}
    </div>
  );
}
