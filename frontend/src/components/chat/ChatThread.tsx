import { useCallback, useRef, useState } from "react";

import { useTranslations } from "next-intl";

import { ChatTurnItem } from "@/components/chat/ChatTurnItem";
import { ChatTurnRows } from "@/components/chat/ChatTurnRows";
import { StreamingMessage } from "@/components/chat/StreamingMessage";
import { CHAT_VIRTUALIZE_MIN_TURNS } from "@/components/chat/chat-types";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import type { ChatFeedbackController } from "@/components/chat/hooks/useChatFeedback";
import type { ChatOverlaysController } from "@/components/chat/hooks/useChatOverlays";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import type { ChatSubmitController } from "@/components/chat/hooks/useChatSubmit";
import { useChatTurnHandlers } from "@/components/chat/hooks/useChatTurnHandlers";
import { useThreadScroll } from "@/components/chat/hooks/useThreadScroll";
import type { CitationPanelController } from "@/components/chat/hooks/useCitationPanel";
import { getApiErrorMessage } from "@/lib/api/errors";

/**
 * The message list. Completed turns are memoised and, above
 * NEXT_PUBLIC_CHAT_VIRTUALIZE_MIN_TURNS, virtualised; the streaming turn is
 * the only part that renders per token (R05-11). The view follows new content
 * only while the user is at the bottom, and older history loads at the top
 * with the scroll position kept.
 */
export function ChatThread({
  session,
  panel,
  feedback,
  overlays,
  submit,
  selectedCollectionIds,
  virtualizeMinTurns = CHAT_VIRTUALIZE_MIN_TURNS,
}: {
  session: Pick<
    ChatSessionController,
    | "activeSessionId"
    | "activeSession"
    | "thread"
    | "pendingQuestion"
    | "sessionMessagesQuery"
    | "setSelectedResponseMessageId"
    | "hasOlderMessages"
    | "isLoadingOlder"
    | "olderMessagesError"
    | "loadOlderMessages"
  >;
  panel: Pick<
    CitationPanelController,
    "setIsKnowledgeHubOpen" | "setPreviewCitationSet"
  >;
  feedback: Pick<
    ChatFeedbackController,
    | "chatFeedbackEnabled"
    | "feedbackByMessageId"
    | "feedbackDeleteMutation"
    | "feedbackSubmitMutation"
    | "setFeedbackModalMessageId"
  >;
  overlays: Pick<
    ChatOverlaysController,
    | "openTrustPanelMessageId"
    | "setOpenTrustPanelMessageId"
    | "copiedMessageId"
    | "setCopiedMessageId"
    | "setAnswerShareMessageId"
  >;
  submit: Pick<
    ChatSubmitController,
    "stream" | "regenerateDisabled" | "submitQuestionText"
  >;
  selectedCollectionIds: string[];
  /** Threads with more turns than this are virtualised. */
  virtualizeMinTurns?: number;
}) {
  const tc = useTranslations("chat.page");
  const {
    activeSessionId,
    activeSession,
    thread,
    pendingQuestion,
    sessionMessagesQuery,
    hasOlderMessages,
    isLoadingOlder,
    olderMessagesError,
    loadOlderMessages,
  } = session;
  const { stream, regenerateDisabled, submitQuestionText } = submit;
  const containerRef = useRef<HTMLDivElement>(null);
  // The virtualiser needs the element in state: the container's ref is set
  // after the rows' layout effects run on the first commit.
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(
    null,
  );
  const attachContainer = useCallback((element: HTMLDivElement | null) => {
    containerRef.current = element;
    setScrollElement(element);
  }, []);
  const virtualize = thread.length > virtualizeMinTurns;

  const handlers = useChatTurnHandlers({
    session,
    panel,
    feedback,
    overlays,
    regenerate: (question) => {
      void submitQuestionText(question, false);
    },
  });

  const scroll = useThreadScroll({
    containerRef,
    activeSessionId,
    turnCount: thread.length,
    firstTurnId: thread[0]?.response.message_id ?? null,
    pendingQuestion,
    canLoadOlder: hasOlderMessages && !isLoadingOlder,
    loadOlder: loadOlderMessages,
  });
  const { followIfAtBottom } = scroll;
  const onContentGrow = useCallback(
    () => followIfAtBottom(),
    [followIfAtBottom],
  );

  const collectionId = selectedCollectionIds[0] ?? null;
  const renderTurn = (
    index: number,
    measureRef?: (el: Element | null) => void,
  ) => {
    const turn = thread[index];
    const messageId = turn.response.message_id;
    const isLatestTurn = index === thread.length - 1;
    const rating = feedback.feedbackByMessageId[messageId]?.rating;
    return (
      <ChatTurnItem
        key={messageId}
        turn={turn}
        index={index}
        measureRef={measureRef}
        collectionId={collectionId}
        handlers={handlers}
        isLatestTurn={isLatestTurn}
        regenerateDisabled={isLatestTurn && regenerateDisabled}
        isTrustPanelOpen={overlays.openTrustPanelMessageId === messageId}
        isCopied={overlays.copiedMessageId === messageId}
        feedbackEnabled={feedback.chatFeedbackEnabled}
        feedbackRating={rating === "up" || rating === "down" ? rating : null}
      />
    );
  };

  return (
    <div
      ref={attachContainer}
      onScroll={scroll.onScroll}
      data-testid="chat-thread"
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

      {hasOlderMessages || isLoadingOlder || olderMessagesError ? (
        <div className="mx-auto mb-6 flex max-w-3xl justify-center">
          <button
            type="button"
            onClick={() => void scroll.loadOlderAnchored()}
            disabled={isLoadingOlder || !hasOlderMessages}
            aria-busy={isLoadingOlder}
            className="rounded-full border border-[#e4e1ee] px-4 py-1.5 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoadingOlder
              ? tc("loadingOlderMessages")
              : olderMessagesError
                ? tc("loadOlderMessagesRetry")
                : tc("loadOlderMessages")}
          </button>
        </div>
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
        <>
          {virtualize ? (
            <ChatTurnRows
              count={thread.length}
              scrollElement={scrollElement}
              getItemKey={(index) => thread[index].response.message_id}
              renderTurn={renderTurn}
              registerScrollToEnd={scroll.registerScrollToEnd}
            />
          ) : null}
          <ul
            className={`mx-auto max-w-3xl space-y-12 ${virtualize && pendingQuestion ? "mt-12" : ""}`}
          >
            {virtualize ? null : thread.map((_, index) => renderTurn(index))}
            {pendingQuestion ? (
              <StreamingMessage
                pendingQuestion={pendingQuestion}
                stream={stream}
                onContentGrow={onContentGrow}
              />
            ) : null}
          </ul>
        </>
      )}
    </div>
  );
}
