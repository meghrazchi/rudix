import { useTranslations } from "next-intl";

import type { ChatTurn } from "@/components/chat/chat-types";
import type { ChatFeedbackController } from "@/components/chat/hooks/useChatFeedback";
import type { ChatOverlaysController } from "@/components/chat/hooks/useChatOverlays";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import { copyToClipboard, formatAnswerAsMarkdown } from "@/lib/export-utils";

export function ChatTurnActions({
  turn,
  isLatestTurn,
  regenerateDisabled,
  onRegenerate,
  session,
  feedback,
  overlays,
}: {
  turn: ChatTurn;
  isLatestTurn: boolean;
  regenerateDisabled: boolean;
  onRegenerate: (question: string) => void;
  session: ChatSessionController;
  feedback: ChatFeedbackController;
  overlays: ChatOverlaysController;
}) {
  const tc = useTranslations("chat.page");
  const { setSelectedResponseMessageId } = session;
  const {
    chatFeedbackEnabled,
    feedbackByMessageId,
    feedbackDeleteMutation,
    feedbackSubmitMutation,
    setFeedbackModalMessageId,
  } = feedback;
  const {
    openTrustPanelMessageId,
    setOpenTrustPanelMessageId,
    copiedMessageId,
    setCopiedMessageId,
    setAnswerShareMessageId,
  } = overlays;

  return (
    <div className="mt-3 flex items-center gap-1 px-1 pt-3">
      {!turn.response.not_found ? (
        <div className="group relative">
          <button
            type="button"
            aria-label={tc("explainAnswer")}
            aria-expanded={openTrustPanelMessageId === turn.response.message_id}
            onClick={() => {
              setSelectedResponseMessageId(turn.response.message_id);
              setOpenTrustPanelMessageId(
                openTrustPanelMessageId === turn.response.message_id
                  ? null
                  : turn.response.message_id,
              );
            }}
            className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${openTrustPanelMessageId === turn.response.message_id ? "text-[#3525cd]" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
          >
            <span
              className="material-symbols-outlined text-[16px]"
              aria-hidden="true"
              style={{
                fontVariationSettings:
                  openTrustPanelMessageId === turn.response.message_id
                    ? "'FILL' 1"
                    : "'FILL' 0",
              }}
            >
              info
            </span>
          </button>
          <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover:opacity-100">
            Explain answer
          </span>
        </div>
      ) : null}
      {!turn.response.not_found ? (
        <div className="group relative">
          <button
            type="button"
            aria-label={tc("copyAnswer")}
            onClick={() => {
              const md = formatAnswerAsMarkdown({
                question: turn.question,
                answer: turn.response.answer,
                citations: turn.response.citations,
                created_at: turn.response.created_at,
              });
              void copyToClipboard(md).then(() => {
                setCopiedMessageId(turn.response.message_id);
                setTimeout(() => setCopiedMessageId(null), 2000);
              });
            }}
            className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${copiedMessageId === turn.response.message_id ? "text-[#3525cd]" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
          >
            <span
              className="material-symbols-outlined text-[16px]"
              aria-hidden="true"
            >
              {copiedMessageId === turn.response.message_id
                ? "check"
                : "content_copy"}
            </span>
          </button>
          <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover:opacity-100">
            {copiedMessageId === turn.response.message_id
              ? tc("copiedTooltip")
              : tc("copyTooltip")}
          </span>
        </div>
      ) : null}
      {!turn.response.not_found ? (
        <div className="group relative">
          <button
            type="button"
            aria-label={tc("shareAnswer")}
            onClick={() => setAnswerShareMessageId(turn.response.message_id)}
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-[#9d98b5] transition-colors hover:bg-[#f1f0f5] hover:text-[#6a6780]"
          >
            <span
              className="material-symbols-outlined text-[16px]"
              aria-hidden="true"
            >
              ios_share
            </span>
          </button>
          <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover:opacity-100">
            Share answer
          </span>
        </div>
      ) : null}
      {chatFeedbackEnabled ? (
        <>
          <div className="group relative">
            <button
              type="button"
              aria-label={tc("markHelpful")}
              onClick={() => {
                const msgId = turn.response.message_id;
                if (feedbackByMessageId[msgId]?.rating === "up") {
                  feedbackDeleteMutation.mutate(msgId);
                } else {
                  feedbackSubmitMutation.mutate({
                    messageId: msgId,
                    rating: "up",
                  });
                }
              }}
              className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${feedbackByMessageId[turn.response.message_id]?.rating === "up" ? "text-emerald-600" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
            >
              <span
                className="material-symbols-outlined text-[16px]"
                aria-hidden="true"
              >
                thumb_up
              </span>
            </button>
            <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover:opacity-100">
              {tc("helpfulTooltip")}
            </span>
          </div>
          <div className="group relative">
            <button
              type="button"
              aria-label={tc("reportIssue")}
              onClick={() =>
                setFeedbackModalMessageId(turn.response.message_id)
              }
              className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${feedbackByMessageId[turn.response.message_id]?.rating === "down" ? "text-rose-500" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
            >
              <span
                className="material-symbols-outlined text-[16px]"
                aria-hidden="true"
              >
                thumb_down
              </span>
            </button>
            <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover:opacity-100">
              {tc("notHelpfulTooltip")}
            </span>
          </div>
        </>
      ) : null}
      {isLatestTurn ? (
        <div className="group relative">
          <button
            type="button"
            aria-label={tc("regenerateAnswer")}
            onClick={() => {
              onRegenerate(turn.question);
            }}
            disabled={regenerateDisabled}
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-[#9d98b5] transition-colors hover:bg-[#f1f0f5] hover:text-[#6a6780] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span
              className="material-symbols-outlined text-[16px]"
              aria-hidden="true"
            >
              refresh
            </span>
          </button>
          <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover:opacity-100">
            {tc("regenerateTooltip")}
          </span>
        </div>
      ) : null}
    </div>
  );
}
