import { useTranslations } from "next-intl";

import { toExportTurns } from "@/components/chat/chat-turns";
import { formatDate } from "@/components/chat/chat-format";
import type { ChatOverlaysController } from "@/components/chat/hooks/useChatOverlays";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import {
  copyToClipboard,
  downloadMarkdown,
  formatTranscriptAsMarkdown,
  sanitizeFilename,
} from "@/lib/export-utils";

export function ChatHeader({
  session,
  overlays,
}: {
  session: ChatSessionController;
  overlays: ChatOverlaysController;
}) {
  const tc = useTranslations("chat.page");
  const { activeSession, activeSessionDisplayTitle, activeSessionId, thread } =
    session;
  const { setIsShareModalOpen } = overlays;

  return (
    <div className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b border-[#e4e1ee] px-4 py-3 lg:px-6">
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-[#1b1b24]">
          {tc("conversationTitle")}
        </h2>
        <p className="mt-1 truncate text-xs text-[#505f76]">
          {activeSession ? (
            <>
              {tc("sessionLabel")}{" "}
              <span className="font-semibold text-[#2f2a46]">
                {activeSessionDisplayTitle}
              </span>
              {" • "}
              {tc("messagesCount", {
                count: activeSession.message_count,
              })}
              {" • "}
              {tc("updatedLabel", {
                date: formatDate(activeSession.updated_at),
              })}
            </>
          ) : (
            tc("newChatDraft")
          )}
        </p>
      </div>
      {activeSessionId && thread.length > 0 ? (
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            aria-label={tc("copyTranscriptTitle")}
            title={tc("copyTranscriptTitle")}
            onClick={() => {
              const md = formatTranscriptAsMarkdown(
                toExportTurns(thread),
                activeSessionDisplayTitle,
              );
              void copyToClipboard(md);
            }}
            className="inline-flex items-center gap-1 rounded-xl border border-[#d2cee6] px-2.5 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            <span
              className="material-symbols-outlined text-[14px]"
              aria-hidden="true"
            >
              content_copy
            </span>
            {tc("copyTranscript")}
          </button>
          <button
            type="button"
            aria-label={tc("exportTranscriptTitle")}
            title={tc("exportTranscriptTitle")}
            onClick={() => {
              const md = formatTranscriptAsMarkdown(
                toExportTurns(thread),
                activeSessionDisplayTitle,
              );
              downloadMarkdown(
                md,
                `${sanitizeFilename(activeSessionDisplayTitle ?? "chat")}.md`,
              );
            }}
            className="inline-flex items-center gap-1 rounded-xl border border-[#d2cee6] px-2.5 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            <span
              className="material-symbols-outlined text-[14px]"
              aria-hidden="true"
            >
              download
            </span>
            {tc("exportTranscript")}
          </button>
          <button
            type="button"
            aria-label={tc("shareSessionTitle")}
            title={tc("shareSessionTitle")}
            onClick={() => setIsShareModalOpen(true)}
            className="inline-flex items-center gap-1 rounded-xl border border-[#d2cee6] px-2.5 py-1.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            <span
              className="material-symbols-outlined text-[14px]"
              aria-hidden="true"
            >
              share
            </span>
            {tc("shareSession")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
