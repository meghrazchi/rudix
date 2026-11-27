import { useEffect, useRef } from "react";

import { useTranslations } from "next-intl";

import { ChatTurnItem } from "@/components/chat/ChatTurnItem";
import { StreamingMessage } from "@/components/chat/StreamingMessage";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import type { ChatFeedbackController } from "@/components/chat/hooks/useChatFeedback";
import type { ChatOverlaysController } from "@/components/chat/hooks/useChatOverlays";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import type { ChatSubmitController } from "@/components/chat/hooks/useChatSubmit";
import type { CitationPanelController } from "@/components/chat/hooks/useCitationPanel";
import { getApiErrorMessage } from "@/lib/api/errors";

export function ChatThread({
  session,
  panel,
  feedback,
  overlays,
  submit,
  selectedCollectionIds,
}: {
  session: ChatSessionController;
  panel: CitationPanelController;
  feedback: ChatFeedbackController;
  overlays: ChatOverlaysController;
  submit: ChatSubmitController;
  selectedCollectionIds: string[];
}) {
  const tc = useTranslations("chat.page");
  const {
    activeSessionId,
    activeSession,
    thread,
    pendingQuestion,
    sessionMessagesQuery,
  } = session;
  const { stream, regenerateDisabled, submitQuestionText } = submit;
  const { partialAnswer } = stream;
  const messagesContainerRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = (smooth = false) => {
    const el = messagesContainerRef.current;
    if (!el) return;
    if (smooth) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  };

  // Jump to the bottom instantly when switching sessions or loading history.
  useEffect(() => {
    scrollToBottom();
  }, [activeSessionId, thread.length]);

  // Smooth-scroll as new content arrives during streaming.
  useEffect(() => {
    if (!pendingQuestion && !partialAnswer) return;
    scrollToBottom(true);
  }, [pendingQuestion, partialAnswer]);

  return (
    <div
      ref={messagesContainerRef}
      className="rudix-chat-scrollbar min-h-0 flex-1 overflow-y-auto bg-white px-4 py-8 lg:px-6"
    >
      {sessionMessagesQuery.isLoading &&
      activeSession &&
      thread.length === 0 &&
      activeSession.message_count > 0 ? (
        <LoadingState compact title={tc("loadingHistory")} />
      ) : null}

      {sessionMessagesQuery.isError &&
      activeSession &&
      thread.length === 0 &&
      activeSession.message_count > 0 ? (
        <ErrorState
          compact
          title={tc("loadHistoryError")}
          error={sessionMessagesQuery.error}
          description={getApiErrorMessage(sessionMessagesQuery.error)}
          onRetry={() => {
            void sessionMessagesQuery.refetch();
          }}
        />
      ) : null}

      {thread.length === 0 &&
      !pendingQuestion &&
      !sessionMessagesQuery.isLoading ? (
        <div className="mx-auto flex max-w-3xl justify-start">
          <div className="flex max-w-[85%] items-start gap-3 rounded-3xl rounded-tl-none border border-[#e4e1ee] bg-[#f5f2ff] px-5 py-4 shadow-sm">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white text-[#3525cd] shadow-sm">
              <span
                className="material-symbols-outlined text-[18px]"
                aria-hidden="true"
              >
                auto_awesome
              </span>
            </span>
            <div>
              <p className="text-sm font-semibold text-[#2f2a46]">
                Rudix is here.
              </p>
              <p className="mt-1 text-sm leading-relaxed text-[#4f4b63]">
                {tc("noMessages")}
              </p>
            </div>
          </div>
        </div>
      ) : (
        <ul className="mx-auto max-w-3xl space-y-12">
          {thread.map((turn, turnIndex) => (
            <ChatTurnItem
              key={turn.response.message_id}
              turn={turn}
              isLatestTurn={turnIndex === thread.length - 1}
              selectedCollectionIds={selectedCollectionIds}
              regenerateDisabled={regenerateDisabled}
              onRegenerate={(questionText) => {
                void submitQuestionText(questionText, false);
              }}
              session={session}
              panel={panel}
              feedback={feedback}
              overlays={overlays}
            />
          ))}
          {pendingQuestion ? (
            <StreamingMessage
              pendingQuestion={pendingQuestion}
              stream={stream}
            />
          ) : null}
        </ul>
      )}
    </div>
  );
}
