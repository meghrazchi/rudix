import { useTranslations } from "next-intl";

import {
  citationFreshnessLabel,
  citationProviderLabel,
  conflictStatusLabel,
} from "@/components/chat/chat-citations";
import {
  getFileIcon,
  getFileTypeColorClass,
  isPreviewableFile,
} from "@/components/chat/chat-format";
import type { ChatTurn } from "@/components/chat/chat-types";
import type { CitationPanelController } from "@/components/chat/hooks/useCitationPanel";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";

export function ChatCitationChips({
  turn,
  session,
  panel,
}: {
  turn: ChatTurn;
  session: ChatSessionController;
  panel: CitationPanelController;
}) {
  const tc = useTranslations("chat.page");
  const { setSelectedResponseMessageId } = session;
  const { setIsKnowledgeHubOpen, setPreviewCitationSet } = panel;

  return (
    <>
      {turn.response.citations.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {turn.response.citations.map((citation, ci) => {
            const label =
              citation.source_title ??
              citation.filename ??
              tc("documentFallback");
            const ext =
              citation.filename?.split(".").pop()?.toUpperCase() ?? "FILE";
            const freshness = citationFreshnessLabel(citation);
            return (
              <div
                key={`inline:${citation.document_id}:${citation.chunk_id}:${ci}`}
                className="relative flex max-w-[18rem] shrink-0 items-stretch overflow-hidden rounded-xl border border-[#c7c4d8] bg-[#fcfbff] transition-colors hover:border-[#3525cd] hover:bg-[#f0ecf9]"
              >
                <button
                  type="button"
                  onClick={() => {
                    const siblings = turn.response.citations.filter(
                      (c) => c.document_id === citation.document_id,
                    );
                    setSelectedResponseMessageId(turn.response.message_id);
                    setIsKnowledgeHubOpen(false);
                    setPreviewCitationSet({
                      citations: siblings.length > 0 ? siblings : [citation],
                      initialIndex: Math.max(0, siblings.indexOf(citation)),
                    });
                  }}
                  title={label}
                  className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 overflow-hidden px-2.5 py-2 text-left"
                >
                  <span
                    className={`material-symbols-outlined shrink-0 text-[20px] ${getFileTypeColorClass(citation.filename)}`}
                    aria-hidden="true"
                  >
                    {getFileIcon(citation.filename)}
                  </span>
                  <span className="min-w-0 flex-1 overflow-hidden">
                    <span
                      className={`block text-[10px] font-bold uppercase ${getFileTypeColorClass(citation.filename)}`}
                    >
                      {citationProviderLabel(citation)?.toUpperCase() ?? ext}
                    </span>
                    <span className="block truncate text-xs font-bold text-[#1b1b24]">
                      {label}
                    </span>
                    {freshness ? (
                      <span
                        className={`mt-1 inline-flex ${freshness.className}`}
                      >
                        {freshness.label}
                      </span>
                    ) : null}
                    {conflictStatusLabel(citation.conflict_status) ? (
                      <span className="mt-1 inline-flex rounded-full border border-[#e0dced] bg-[#faf9ff] px-1.5 py-0.5 text-[9px] font-semibold text-[#5d58a8] uppercase">
                        {conflictStatusLabel(citation.conflict_status)}
                      </span>
                    ) : null}
                  </span>
                </button>
                {isPreviewableFile(citation.filename) && (
                  <button
                    type="button"
                    aria-label={tc("previewCitation", {
                      filename: citation.filename ?? tc("documentFallback"),
                    })}
                    onClick={() => {
                      const siblings = turn.response.citations.filter(
                        (c) => c.document_id === citation.document_id,
                      );
                      const idx = siblings.indexOf(citation);
                      setSelectedResponseMessageId(turn.response.message_id);
                      setIsKnowledgeHubOpen(false);
                      setPreviewCitationSet({
                        citations: siblings,
                        initialIndex: idx >= 0 ? idx : 0,
                      });
                    }}
                    className="shrink-0 self-center border-l border-[#e4e1ee] px-2 text-[#6a6780] transition-colors hover:bg-[#ede9f9] hover:text-[#3525cd]"
                  >
                    <span
                      className="material-symbols-outlined text-[16px]"
                      aria-hidden="true"
                    >
                      open_in_new
                    </span>
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
