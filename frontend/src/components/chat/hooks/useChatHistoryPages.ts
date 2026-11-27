import {
  useCallback,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import {
  buildHistoryPage,
  type HistoryPageState,
} from "@/components/chat/chat-history";
import { activeThreadKey } from "@/components/chat/chat-turns";
import {
  CHAT_HISTORY_PAGE_SIZE,
  type ChatTurn,
} from "@/components/chat/chat-types";
import { listChatSessionMessages } from "@/lib/api/chat";

/**
 * Older history pages for the active session (R05-11). The newest page is
 * loaded by `useChatSession`; this hook keeps each session's cursor and
 * prepends older pages when the thread is scrolled to the top.
 */
export function useChatHistoryPages({
  activeSessionId,
  setThreadsBySession,
}: {
  activeSessionId: string | null;
  setThreadsBySession: Dispatch<SetStateAction<Record<string, ChatTurn[]>>>;
}) {
  const [pagesBySession, setPagesBySession] = useState<
    Record<string, HistoryPageState>
  >({});
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [olderMessagesError, setOlderMessagesError] = useState<unknown>(null);
  const inFlightRef = useRef(false);
  const page = activeSessionId
    ? pagesBySession[activeThreadKey(activeSessionId)]
    : undefined;

  const recordHistoryPage = useCallback(
    (sessionId: string, state: HistoryPageState) => {
      setPagesBySession((previous) => ({
        ...previous,
        [activeThreadKey(sessionId)]: state,
      }));
    },
    [],
  );

  const loadOlderMessages = useCallback(async (): Promise<boolean> => {
    if (!activeSessionId || !page?.nextCursor || inFlightRef.current) {
      return false;
    }
    const key = activeThreadKey(activeSessionId);
    inFlightRef.current = true;
    setIsLoadingOlder(true);
    setOlderMessagesError(null);
    try {
      const response = await listChatSessionMessages(activeSessionId, {
        limit: CHAT_HISTORY_PAGE_SIZE,
        order: "desc",
        cursor: page.nextCursor,
      });
      const { turns, state } = buildHistoryPage(
        response.items,
        response.next_cursor,
        page.held,
      );
      setThreadsBySession((previous) => ({
        ...previous,
        [key]: [...turns, ...(previous[key] ?? [])],
      }));
      setPagesBySession((previous) => ({ ...previous, [key]: state }));
      return true;
    } catch (error) {
      setOlderMessagesError(error);
      return false;
    } finally {
      inFlightRef.current = false;
      setIsLoadingOlder(false);
    }
  }, [activeSessionId, page, setThreadsBySession]);

  return {
    hasOlderMessages: Boolean(page?.nextCursor),
    isLoadingOlder,
    olderMessagesError,
    loadOlderMessages,
    recordHistoryPage,
  };
}
