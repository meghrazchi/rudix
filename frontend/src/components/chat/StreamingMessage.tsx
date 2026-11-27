import { useTranslations } from "next-intl";

import { ActivityTimeline } from "@/components/chat/ActivityTimeline";
import { ChatResponseLoadingState } from "@/components/chat/ChatResponseLoadingState";
import {
  CHAT_WEBSOCKET_ENABLED,
  STREAMING_PLACEHOLDER_ENABLED,
} from "@/components/chat/chat-types";
import type { ChatStreamController } from "@/components/chat/hooks/useChatStream";

/** The in-progress assistant turn: pending question, timeline, partial text. */
export function StreamingMessage({
  pendingQuestion,
  stream,
}: {
  pendingQuestion: string;
  stream: ChatStreamController;
}) {
  const tc = useTranslations("chat.page");
  const { timelineSteps, partialAnswer, phaseLabel } = stream;

  return (
    <li className="space-y-3">
      <div className="flex flex-col items-end gap-2">
        <article className="max-w-[85%] rounded-3xl rounded-tr-none bg-[#f0ecf9] px-6 py-4 shadow-sm">
          <p className="sr-only">{tc("questionLabel")}</p>
          <p className="rudix-chat-scrollbar max-h-72 overflow-y-auto pr-1 text-[15px] leading-relaxed break-words whitespace-pre-wrap text-[#1b1b24]">
            {pendingQuestion}
          </p>
        </article>
        <div className="mr-2 flex items-center gap-2 text-[10px] font-bold tracking-widest text-[#777587] uppercase">
          <span>{tc("you")}</span>
        </div>
      </div>
      {CHAT_WEBSOCKET_ENABLED && timelineSteps.length > 0 && (
        <ActivityTimeline steps={timelineSteps} />
      )}
      {CHAT_WEBSOCKET_ENABLED && partialAnswer ? (
        <div className="flex justify-start">
          <article className="w-full rounded-3xl rounded-tl-none border border-[#e4e1ee] bg-white px-6 py-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded bg-[#3525cd] text-[10px] font-bold text-white italic">
                R
              </span>
              <span className="text-[10px] font-bold tracking-widest text-[#3525cd] uppercase">
                Rudix AI
              </span>
            </div>
            <p className="text-[16px] leading-relaxed break-words whitespace-pre-wrap text-[#2f2a46]">
              {partialAnswer}
              <span
                className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[#3525cd] align-middle"
                aria-hidden="true"
              />
            </p>
          </article>
        </div>
      ) : (
        <ChatResponseLoadingState
          label={
            CHAT_WEBSOCKET_ENABLED && phaseLabel
              ? phaseLabel
              : STREAMING_PLACEHOLDER_ENABLED
                ? tc("streamingLabel")
                : tc("generatingLabel")
          }
        />
      )}
    </li>
  );
}
