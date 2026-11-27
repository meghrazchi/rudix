import Link from "next/link";
import { useTranslations } from "next-intl";

import {
  citationDisplayTitle,
  citationFreshnessLabel,
  citationOrdinal,
  citationProviderLabel,
} from "@/components/chat/chat-citations";
import {
  formatDate,
  formatScorePercent,
  getFileIcon,
  getFileTypeColorClass,
  getFileTypeLabel,
} from "@/components/chat/chat-format";
import {
  renderChunkCitationExcerpt,
  renderCitationExcerpt,
} from "@/components/chat/citation-excerpts";
import type { CitationPanelController } from "@/components/chat/hooks/useCitationPanel";
import { citationCopyText } from "@/components/chat/chat-citations";
import type { ChatCitationResponse } from "@/lib/api/chat";
import { copyToClipboard } from "@/lib/export-utils";

export function CitationDetails({
  panel,
  activePreviewCitation,
}: {
  panel: CitationPanelController;
  activePreviewCitation: ChatCitationResponse;
}) {
  const tc = useTranslations("chat.page");
  const {
    previewCitationSet,
    setPreviewCitationSet,
    previewCitationIndex,
    activePreviewCitationChunkQuery,
    activePreviewCitationChunk,
    activePreviewCitationTitle,
    activePreviewCitationDocumentHref,
    activePreviewCitationScore,
    activePreviewCitationScorePercent,
    relatedPreviewCitations,
  } = panel;

  return (
    <div className="space-y-6 p-6">
      <section className="rounded-2xl border border-[#e4e1ee] bg-white p-4 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#f0ecf9] text-[#3525cd] shadow-inner">
            <span
              className="material-symbols-outlined text-[26px]"
              aria-hidden="true"
            >
              {getFileIcon(activePreviewCitation.filename)}
            </span>
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-black tracking-[0.18em] text-[#3525cd] uppercase">
              {citationOrdinal(previewCitationIndex)}
            </p>
            <h3
              className="mt-1 line-clamp-2 text-lg leading-tight font-black tracking-tight text-[#1b1b24]"
              title={activePreviewCitationTitle ?? undefined}
            >
              {activePreviewCitationTitle}
            </h3>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span
                className={`rounded-lg bg-[#f5f2ff] px-2 py-1 text-[10px] font-black tracking-wider uppercase ${getFileTypeColorClass(activePreviewCitation.filename)}`}
              >
                {citationProviderLabel(activePreviewCitation) ??
                  getFileTypeLabel(activePreviewCitation.filename)}
              </span>
              {citationFreshnessLabel(activePreviewCitation) ? (
                <span
                  className={
                    citationFreshnessLabel(activePreviewCitation)?.className
                  }
                >
                  {citationFreshnessLabel(activePreviewCitation)?.label}
                </span>
              ) : null}
            </div>
          </div>
          <Link
            href={activePreviewCitationDocumentHref ?? "#"}
            aria-label={`${tc("citationFullDocument")}: ${
              activePreviewCitationTitle ?? tc("unknownDocument")
            }`}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#e4e1ee] bg-white text-[#777587] transition-colors hover:border-[#3525cd] hover:text-[#3525cd]"
          >
            <span
              className="material-symbols-outlined text-[18px]"
              aria-hidden="true"
            >
              open_in_new
            </span>
          </Link>
        </div>
        <div className="mt-5 grid w-full grid-cols-2 items-stretch gap-3">
          <div className="h-full w-full rounded-2xl border border-[#e4e1ee] bg-[#faf9ff] px-3 pt-4 pb-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
            <p className="text-[10px] font-black tracking-[0.18em] text-[#777587] uppercase">
              {tc("citationPositionMetric")}
            </p>
            <p className="mt-3 text-[15px] font-black tracking-tight text-[#1b1b24]">
              {activePreviewCitation.page_number
                ? tc("citationPositionPage", {
                    page: activePreviewCitation.page_number,
                  })
                : activePreviewCitation.chunk_id
                  ? tc("citationPositionChunk", {
                      chunk: activePreviewCitation.chunk_id.slice(0, 8),
                    })
                  : "—"}
            </p>
          </div>
          <div className="h-full w-full rounded-2xl border border-[#e4e1ee] bg-[#faf9ff] px-3 pt-4 pb-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
            <p className="text-[10px] font-black tracking-[0.18em] text-[#777587] uppercase">
              {tc("citationRelevanceMetric")}
            </p>
            <div className="mt-3 flex items-center gap-3">
              <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-[#e4e1ee]">
                <div
                  className="h-full rounded-full bg-[#3525cd]"
                  style={{
                    width: `${activePreviewCitationScorePercent ?? 0}%`,
                  }}
                />
              </div>
              <p className="shrink-0 text-[15px] font-black tracking-tight text-[#3525cd]">
                {formatScorePercent(activePreviewCitationScore)}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section>
        <p className="mb-3 text-[10px] font-black tracking-[0.18em] text-[#464555] uppercase">
          {tc("citationReferencedContext")}
        </p>
        <div className="rounded-2xl border border-[#e4e1ee] bg-white p-4 shadow-sm">
          {activePreviewCitationChunkQuery.isLoading ? (
            <p className="rounded-2xl border border-dashed border-[#d7d4e8] bg-[#faf9ff] p-4 text-sm text-[#6a6780]">
              Loading chunk text...
            </p>
          ) : (
            (renderChunkCitationExcerpt(
              activePreviewCitationChunk,
              activePreviewCitation.text_snippet,
            ) ?? renderCitationExcerpt(activePreviewCitation.text_snippet))
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {activePreviewCitation.page_number ? (
              <span className="rounded-full bg-[#f0ecf9] px-3 py-1 font-mono text-[10px] font-bold text-[#464555]">
                {tc("citationPositionPage", {
                  page: activePreviewCitation.page_number,
                })}
              </span>
            ) : null}
            {activePreviewCitation.source_section ? (
              <span className="rounded-full bg-[#f0ecf9] px-3 py-1 text-[10px] font-bold text-[#464555]">
                {tc("citationSection", {
                  section: activePreviewCitation.source_section,
                })}
              </span>
            ) : null}
            {activePreviewCitation.source_last_synced_at ? (
              <span className="rounded-full bg-[#f0ecf9] px-3 py-1 text-[10px] font-bold text-[#464555]">
                {tc("citationSynced", {
                  date: formatDate(activePreviewCitation.source_last_synced_at),
                })}
              </span>
            ) : null}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3">
        <Link
          href={activePreviewCitationDocumentHref ?? "#"}
          className="flex items-center justify-center gap-2 rounded-2xl bg-[#1b1b24] px-4 py-3 text-sm font-black text-white shadow-sm transition-colors hover:bg-[#3525cd]"
        >
          <span
            className="material-symbols-outlined text-[18px]"
            aria-hidden="true"
          >
            article
          </span>
          {tc("citationFullDocument")}
        </Link>
        <button
          type="button"
          onClick={() => {
            void copyToClipboard(
              citationCopyText(
                activePreviewCitation,
                citationOrdinal(previewCitationIndex),
                activePreviewCitationTitle ?? tc("unknownDocument"),
              ),
            );
          }}
          className="flex cursor-pointer items-center justify-center gap-2 rounded-2xl border border-[#e4e1ee] bg-white px-4 py-3 text-sm font-black text-[#464555] shadow-sm transition-colors hover:border-[#3525cd] hover:text-[#3525cd]"
        >
          <span
            className="material-symbols-outlined text-[18px]"
            aria-hidden="true"
          >
            ios_share
          </span>
          {tc("citationShare")}
        </button>
      </section>

      <section>
        <p className="mb-3 text-[10px] font-black tracking-[0.18em] text-[#464555] uppercase">
          {tc("citationOtherFindings")}
        </p>
        {relatedPreviewCitations.length > 0 ? (
          <div className="space-y-2">
            {relatedPreviewCitations.map(({ citation, index }) => {
              const title = citationDisplayTitle(
                citation,
                tc("unknownDocument"),
              );
              return (
                <button
                  key={`related:${citation.document_id}:${citation.chunk_id}:${index}`}
                  type="button"
                  onClick={() => {
                    setPreviewCitationSet({
                      citations: previewCitationSet?.citations ?? [
                        activePreviewCitation,
                      ],
                      initialIndex: index,
                    });
                  }}
                  className="group w-full rounded-2xl border border-[#e4e1ee] bg-white p-3 text-left shadow-sm transition-colors hover:border-[#3525cd]"
                >
                  <div className="mb-1 flex items-center justify-between gap-3">
                    <span className="text-[10px] font-black tracking-[0.18em] text-[#3525cd] uppercase">
                      {citationOrdinal(index)}
                    </span>
                    {citation.page_number ? (
                      <span className="rounded-full bg-[#f0ecf9] px-2 py-0.5 font-mono text-[9px] font-bold text-[#464555]">
                        {tc("citationPositionPage", {
                          page: citation.page_number,
                        })}
                      </span>
                    ) : null}
                  </div>
                  <p className="truncate text-sm font-black text-[#1b1b24]">
                    {title}
                  </p>
                  {citation.text_snippet ? (
                    <div className="mt-2">
                      {renderCitationExcerpt(citation.text_snippet, {
                        compact: true,
                      })}
                    </div>
                  ) : null}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="rounded-2xl border border-dashed border-[#d7d4e8] bg-white/70 p-4 text-sm text-[#6a6780]">
            {tc("citationRelatedEmpty")}
          </p>
        )}
      </section>
    </div>
  );
}
