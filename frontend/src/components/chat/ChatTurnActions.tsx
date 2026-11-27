import { useTranslations } from "next-intl";

import type { ChatTurn } from "@/components/chat/chat-types";
import type { ChatTurnHandlers } from "@/components/chat/hooks/useChatTurnHandlers";

/** Per-turn view state, all primitives so `ChatTurnItem` memoises (R05-11). */
export type ChatTurnView = {
  isLatestTurn: boolean;
  /** Only meaningful on the latest turn; pass false elsewhere. */
  regenerateDisabled: boolean;
  isTrustPanelOpen: boolean;
  isCopied: boolean;
  feedbackEnabled: boolean;
  feedbackRating: "up" | "down" | null;
};

export function ChatTurnActions({
  turn,
  view,
  handlers,
}: {
  turn: ChatTurn;
  view: ChatTurnView;
  handlers: ChatTurnHandlers;
}) {
  const tc = useTranslations("chat.page");
  const {
    isLatestTurn,
    regenerateDisabled,
    isTrustPanelOpen,
    isCopied,
    feedbackEnabled,
    feedbackRating,
  } = view;

  return (
    <div className="mt-3 flex items-center gap-1 px-1 pt-3">
      {!turn.response.not_found ? (
        <div className="group relative">
          <button
            type="button"
            aria-label={tc("explainAnswer")}
            aria-expanded={isTrustPanelOpen}
            onClick={() => handlers.toggleTrustPanel(turn.response.message_id)}
            className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${isTrustPanelOpen ? "text-[#3525cd]" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
          >
            <span
              className="material-symbols-outlined text-[16px]"
              aria-hidden="true"
              style={{
                fontVariationSettings: isTrustPanelOpen
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
            onClick={() => handlers.copyAnswer(turn)}
            className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${isCopied ? "text-[#3525cd]" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
          >
            <span
              className="material-symbols-outlined text-[16px]"
              aria-hidden="true"
            >
              {isCopied ? "check" : "content_copy"}
            </span>
          </button>
          <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 -translate-x-1/2 rounded bg-[#2a2640] px-2 py-0.5 text-[10px] whitespace-nowrap text-white opacity-0 transition-opacity group-hover:opacity-100">
            {isCopied ? tc("copiedTooltip") : tc("copyTooltip")}
          </span>
        </div>
      ) : null}
      {!turn.response.not_found ? (
        <div className="group relative">
          <button
            type="button"
            aria-label={tc("shareAnswer")}
            onClick={() => handlers.shareAnswer(turn.response.message_id)}
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
      {feedbackEnabled ? (
        <>
          <div className="group relative">
            <button
              type="button"
              aria-label={tc("markHelpful")}
              onClick={() => handlers.rateHelpful(turn.response.message_id)}
              className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${feedbackRating === "up" ? "text-emerald-600" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
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
              onClick={() => handlers.reportIssue(turn.response.message_id)}
              className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-[#f1f0f5] ${feedbackRating === "down" ? "text-rose-500" : "text-[#9d98b5] hover:text-[#6a6780]"}`}
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
              handlers.regenerate(turn.question);
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
