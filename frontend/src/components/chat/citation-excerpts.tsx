import type { ReactElement } from "react";

import { buildCitationExcerptParts } from "@/components/chat/chat-citations";
import type { DocumentChunkPreviewResponse } from "@/lib/api/documents";

export function renderCitationExcerpt(
  value: string | null | undefined,
  options: { compact?: boolean } = {},
): ReactElement | null {
  if (!value) {
    return null;
  }

  const normalized = value.replace(/\s+/g, " ").trim();
  const excerptParts = buildCitationExcerptParts(normalized, options.compact);
  const containerClassName = options.compact
    ? "relative overflow-hidden rounded-2xl border border-[#e6e0fb] bg-gradient-to-br from-[#fcfbff] via-white to-[#f7f3ff] p-3 pl-4"
    : "relative overflow-hidden rounded-2xl border border-[#e6e0fb] bg-gradient-to-br from-[#fcfbff] via-white to-[#f7f3ff] p-5 pl-5";
  const textClassName = options.compact
    ? "text-xs leading-snug text-[#2f2a46]"
    : "text-sm leading-relaxed text-[#2f2a46]";

  return (
    <div className={containerClassName}>
      <div className="absolute inset-y-0 left-0 w-1 rounded-r-full bg-gradient-to-b from-[#3525cd] via-[#7b61ff] to-[#14b8a6]" />
      <p className="mb-2 text-[10px] font-black tracking-[0.18em] text-[#5d58a8] uppercase">
        Cited excerpt
      </p>
      <p className={`${textClassName} whitespace-pre-wrap`}>
        {excerptParts.before ? (
          <span className="text-[#5f5a73]">{`${excerptParts.before} `}</span>
        ) : null}
        {excerptParts.highlightedPrefix ? (
          <span className="text-[#5f5a73]">
            {`${excerptParts.highlightedPrefix} `}
          </span>
        ) : null}
        <mark className="rounded-lg bg-[#f0ecf9] box-decoration-clone px-1.5 py-0.5 text-[#3525cd] ring-1 ring-[#d7d4e8] ring-inset">
          {excerptParts.highlighted}
        </mark>
        {excerptParts.highlightedSuffix ? (
          <span className="text-[#5f5a73]">
            {` ${excerptParts.highlightedSuffix}`}
          </span>
        ) : null}
        {excerptParts.after ? (
          <span className="text-[#5f5a73]">{` ${excerptParts.after}`}</span>
        ) : null}
      </p>
    </div>
  );
}

export function renderChunkCitationExcerpt(
  chunk: DocumentChunkPreviewResponse | null | undefined,
  citationSnippet: string | null | undefined,
): ReactElement | null {
  if (!chunk?.text) {
    return null;
  }

  const chunkText = chunk.text.replace(/\s+/g, " ").trim();
  const snippet = citationSnippet?.replace(/\s+/g, " ").trim() ?? "";
  if (!chunkText) {
    return null;
  }

  let before = chunkText;
  let highlighted = snippet;
  let after = "";
  if (snippet) {
    const matchIndex = chunkText.toLowerCase().indexOf(snippet.toLowerCase());
    if (matchIndex >= 0) {
      before = chunkText.slice(0, matchIndex);
      highlighted = chunkText.slice(matchIndex, matchIndex + snippet.length);
      after = chunkText.slice(matchIndex + snippet.length);
    } else {
      highlighted = snippet;
    }
  }

  const excerptWindow = 220;
  const maxLength = 900;
  if (before.length + highlighted.length + after.length > maxLength) {
    const center = before.length + Math.floor(highlighted.length / 2);
    const start = Math.max(0, center - excerptWindow);
    const end = Math.min(chunkText.length, center + excerptWindow);
    const windowText = chunkText.slice(start, end);
    const windowIndex = snippet
      ? windowText.toLowerCase().indexOf(snippet.toLowerCase())
      : -1;
    if (windowIndex >= 0) {
      before = windowText.slice(0, windowIndex);
      highlighted = windowText.slice(windowIndex, windowIndex + snippet.length);
      after = windowText.slice(windowIndex + snippet.length);
    } else {
      before = windowText;
      highlighted = snippet || windowText;
      after = "";
    }
  }

  return (
    <div className="relative overflow-hidden rounded-2xl border border-[#e6e0fb] bg-gradient-to-br from-[#fcfbff] via-white to-[#f7f3ff] p-5 pl-5">
      <div className="absolute inset-y-0 left-0 w-1 rounded-r-full bg-gradient-to-b from-[#3525cd] via-[#7b61ff] to-[#14b8a6]" />
      <p className="mb-2 text-[10px] font-black tracking-[0.18em] text-[#5d58a8] uppercase">
        Cited chunk text
      </p>
      <p className="text-sm leading-relaxed whitespace-pre-wrap text-[#2f2a46]">
        <span className="text-[#5f5a73]">&ldquo;...</span>
        {before ? <span className="text-[#5f5a73]">{` ${before}`}</span> : null}
        {before ? " " : null}
        <mark className="rounded-lg bg-[#f0ecf9] box-decoration-clone px-1.5 py-0.5 text-[#3525cd] ring-1 ring-[#d7d4e8] ring-inset">
          {highlighted}
        </mark>
        {after ? <span className="text-[#5f5a73]">{` ${after}`}</span> : null}
        <span className="text-[#5f5a73]">...&rdquo;</span>
      </p>
    </div>
  );
}
