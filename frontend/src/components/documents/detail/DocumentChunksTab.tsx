"use client";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";

import {
  CHUNK_PAGE_SIZE,
  formatDate,
  noChunksMessage,
  truncateChunkPreview,
} from "@/components/documents/detail/detail-format";
import type { DocumentDetailController } from "@/components/documents/detail/useDocumentDetail";

/** Chunks tab: full-text toggle, sample search, chunk cards, and paging. */
export function DocumentChunksTab({ ctl }: { ctl: DocumentDetailController }) {
  const {
    td,
    noChunkMessages,
    highlightedChunkId,
    capabilities,
    setChunksOffset,
    includeFullText,
    setIncludeFullText,
    chunkSearchQuery,
    setChunkSearchQuery,
    highlightedChunkRef,
    chunksQuery,
    chunkStatus,
    selectedChunks,
    filteredChunks,
    canGoPrevChunks,
    canGoNextChunks,
  } = ctl;
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-bold text-[#2a2640]">
          {td("chunkPreviewTitle")}
        </h3>
        <div className="flex items-center gap-3">
          {capabilities.canViewChunkFullText ? (
            <label className="flex items-center gap-2 text-xs font-semibold tracking-wide text-[#5f5b72] uppercase">
              <input
                type="checkbox"
                checked={includeFullText}
                onChange={(event) => {
                  setChunksOffset(0);
                  setIncludeFullText(event.target.checked);
                }}
                className="h-4 w-4 rounded border-[#c9c4de]"
              />
              {td("includeFullText")}
            </label>
          ) : null}
          {chunksQuery.isFetching ? (
            <span className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {td("refreshing")}
            </span>
          ) : null}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="space-y-1">
          <span className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
            {td("searchSampleChunks")}
          </span>
          <input
            value={chunkSearchQuery}
            onChange={(event) => setChunkSearchQuery(event.target.value)}
            placeholder={td("searchPlaceholder")}
            className="w-full rounded-xl border border-[#c9c4de] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
          />
        </label>
        <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3 text-sm text-[#4d4963]">
          <p className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
            {td("searchScope")}
          </p>
          <p className="mt-1">
            {(selectedChunks?.items.length ?? 0) === 1
              ? td("loadedChunkSample", {
                  count: selectedChunks?.items.length ?? 0,
                })
              : td("loadedChunkSamples", {
                  count: selectedChunks?.items.length ?? 0,
                })}
          </p>
        </div>
      </div>

      {chunksQuery.isLoading ? (
        <LoadingState compact title={td("loadingChunks")} />
      ) : null}

      {chunksQuery.isError ? (
        <ErrorState
          compact
          error={chunksQuery.error}
          description={getApiErrorMessage(chunksQuery.error)}
          onRetry={() => {
            void chunksQuery.refetch();
          }}
          retryLabel={td("retryChunkLoad")}
        />
      ) : null}

      {selectedChunks && selectedChunks.items.length === 0 && chunkStatus ? (
        <EmptyState
          compact
          title={noChunksMessage(chunkStatus, noChunkMessages)}
        />
      ) : null}

      {selectedChunks &&
      selectedChunks.items.length > 0 &&
      filteredChunks.length === 0 ? (
        <EmptyState
          compact
          title={td("noChunkMatch")}
          description={td("noChunkMatchDesc")}
        />
      ) : null}

      {selectedChunks && filteredChunks.length > 0 ? (
        <div className="space-y-2">
          {filteredChunks.map((chunk) => {
            const isCited = chunk.chunk_id === highlightedChunkId;
            return (
              <article
                key={chunk.chunk_id}
                ref={
                  isCited
                    ? (el) => {
                        highlightedChunkRef.current = el;
                      }
                    : undefined
                }
                className={`rounded-lg border px-3 py-3 ${
                  isCited
                    ? "border-[#3525cd]/30 bg-[#f0ecff] shadow-sm ring-1 ring-[#3525cd]/20"
                    : "border-[#e4e1f2] bg-[#faf9ff]"
                }`}
              >
                <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  {isCited ? (
                    <span className="rounded bg-[#3525cd] px-1.5 py-0.5 text-[10px] font-bold text-white uppercase">
                      {td("citedLabel")}
                    </span>
                  ) : null}
                  <span>
                    {td("chunkIndex", {
                      index: chunk.chunk_index,
                    })}
                  </span>
                  <span>
                    {td("chunkPage", {
                      n: chunk.page_number ?? "-",
                    })}
                  </span>
                  <span>
                    {td("chunkTokens", {
                      n: chunk.token_count,
                    })}
                  </span>
                  <span>
                    {td("chunkModel", {
                      name: chunk.embedding_model,
                    })}
                  </span>
                  <span>
                    {td("chunkIndexVersion", {
                      version: chunk.index_version,
                    })}
                  </span>
                  <span>
                    {td("chunkCreated", {
                      date: formatDate(chunk.created_at),
                    })}
                  </span>
                </div>
                <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-[#5f5a74]">
                  <span>
                    {chunk.section_path
                      ? td("chunkSection", {
                          path: chunk.section_path,
                        })
                      : td("chunkSectionNone")}
                  </span>
                  <span>·</span>
                  <span>
                    {td("chunkLanguage", {
                      lang: chunk.language ?? "-",
                    })}
                  </span>
                  <span>·</span>
                  <span>
                    {td("chunkLevel", {
                      n: chunk.chunk_level ?? 0,
                    })}
                  </span>
                  {chunk.source_start_offset != null &&
                  chunk.source_end_offset != null ? (
                    <>
                      <span>·</span>
                      <span>
                        {td("chunkOffsets", {
                          start: chunk.source_start_offset,
                          end: chunk.source_end_offset,
                        })}
                      </span>
                    </>
                  ) : null}
                </div>
                <p className="text-sm break-words whitespace-pre-wrap text-[#2a2640]">
                  {includeFullText && chunk.text
                    ? chunk.text
                    : truncateChunkPreview(chunk.text_preview)}
                </p>
              </article>
            );
          })}
          <div className="mt-2 flex items-center justify-between gap-2">
            <p className="text-xs text-[#6e6a86]">
              {td("showingChunks", {
                shown: filteredChunks.length,
                total: selectedChunks.total,
              })}
            </p>
            {!highlightedChunkId ? (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={!canGoPrevChunks}
                  onClick={() =>
                    setChunksOffset((current) =>
                      Math.max(0, current - CHUNK_PAGE_SIZE),
                    )
                  }
                  className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {td("previous")}
                </button>
                <button
                  type="button"
                  disabled={!canGoNextChunks}
                  onClick={() =>
                    setChunksOffset((current) => current + CHUNK_PAGE_SIZE)
                  }
                  className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {td("next")}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
