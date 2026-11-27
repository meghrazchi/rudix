import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { buildHistoryPage } from "@/components/chat/chat-history";
import { useChatHistoryPages } from "@/components/chat/hooks/useChatHistoryPages";
import {
  CHAT_HISTORY_PAGE_SIZE,
  SESSION_LIST_LIMIT,
  type ChatSessionListInfiniteData,
  type ChatSessionListItem,
  type ChatTurn,
} from "@/components/chat/chat-types";
import {
  activeThreadKey,
  toSessionDisplayTitle,
} from "@/components/chat/chat-turns";
import { replaceSessionParamInUrl } from "@/components/chat/chat-session-utils";
import {
  createChatSession,
  deleteChatSession,
  listChatSessionMessages,
  listChatSessions,
  updateChatSession,
} from "@/lib/api/chat";
import {
  listSessionFeedback,
  type MessageFeedbackResponse,
} from "@/lib/api/feedback";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

export function useChatSession({
  searchParams,
  chatFeedbackEnabled,
  setFeedbackByMessageId,
  setQuestion,
}: {
  searchParams: URLSearchParams;
  chatFeedbackEnabled: boolean;
  setFeedbackByMessageId: Dispatch<
    SetStateAction<Record<string, MessageFeedbackResponse>>
  >;
  setQuestion: Dispatch<SetStateAction<string>>;
}) {
  const queryClient = useQueryClient();
  const lastAppliedSessionIdRef = useRef<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [threadsBySession, setThreadsBySession] = useState<
    Record<string, ChatTurn[]>
  >({});
  const [selectedResponseMessageId, setSelectedResponseMessageId] = useState<
    string | null
  >(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [submitRequestId, setSubmitRequestId] = useState<string | null>(null);
  const [sessionSearchQuery, setSessionSearchQuery] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");
  const [confirmDeleteSessionId, setConfirmDeleteSessionId] = useState<
    string | null
  >(null);
  const deleteSessionModalRef = useRef<HTMLDivElement>(null);
  const deleteSessionOverlayRef = useRef<HTMLDivElement>(null);
  const sessionMenuRef = useRef<HTMLDivElement>(null);
  const editSessionInputRef = useRef<HTMLInputElement>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [openSessionMenuId, setOpenSessionMenuId] = useState<string | null>(
    null,
  );

  const sessionsQuery = useInfiniteQuery({
    queryKey: queryKeys.chat.sessionsQuery(
      debouncedSearchQuery ? { search: debouncedSearchQuery } : undefined,
    ),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listChatSessions({
        limit: SESSION_LIST_LIMIT,
        offset: Number(pageParam),
        search: debouncedSearchQuery || undefined,
      }),
    getNextPageParam: (lastPage, allPages) => {
      const loadedCount = allPages.reduce(
        (total, page) => total + page.items.length,
        0,
      );
      if (loadedCount >= (lastPage.total ?? 0)) {
        return undefined;
      }
      return loadedCount;
    },
  });

  const sessions = useMemo(() => {
    const allItems =
      sessionsQuery.data?.pages.flatMap((page) => page.items) ?? [];
    const seen = new Set<string>();
    return allItems.filter((session) => {
      if (seen.has(session.session_id)) {
        return false;
      }
      seen.add(session.session_id);
      return true;
    });
  }, [sessionsQuery.data?.pages]);

  const totalSessions = sessionsQuery.data?.pages[0]?.total ?? sessions.length;

  const shouldLoadActiveSessionHistory =
    activeSessionId !== null &&
    (threadsBySession[activeThreadKey(activeSessionId)] ?? []).length === 0;

  useEffect(() => {
    const sessionIdFromQuery = searchParams.get("session_id");
    if (!sessionIdFromQuery) {
      lastAppliedSessionIdRef.current = null;
      return;
    }
    if (lastAppliedSessionIdRef.current === sessionIdFromQuery) {
      return;
    }
    setActiveSessionId(sessionIdFromQuery);
    setPendingQuestion(null);
    setSubmitRequestId(null);
    lastAppliedSessionIdRef.current = sessionIdFromQuery;
  }, [searchParams]);

  const history = useChatHistoryPages({ activeSessionId, setThreadsBySession });
  const { recordHistoryPage } = history;

  // Newest page first (R05-11); older pages load from the top of the thread.
  const sessionMessagesQuery = useQuery({
    queryKey: queryKeys.chat.sessionMessages(activeSessionId ?? ""),
    queryFn: async () => {
      const response = await listChatSessionMessages(activeSessionId ?? "", {
        limit: CHAT_HISTORY_PAGE_SIZE,
        order: "desc",
      });
      if (!activeSessionId) {
        return response;
      }
      const threadKey = activeThreadKey(activeSessionId);
      const { turns: hydratedTurns, state: pageState } = buildHistoryPage(
        response.items,
        response.next_cursor,
      );
      setThreadsBySession((previous) => {
        const existing = previous[threadKey];
        if (existing && existing.length > 0) {
          return previous;
        }
        return {
          ...previous,
          [threadKey]: hydratedTurns,
        };
      });
      // The query only runs while this thread is empty, so the cursor matches.
      recordHistoryPage(activeSessionId, pageState);
      if (chatFeedbackEnabled) {
        try {
          const feedbackResponse = await listSessionFeedback(activeSessionId);
          setFeedbackByMessageId((previous) => {
            const next = { ...previous };
            for (const fb of feedbackResponse.items) {
              next[fb.message_id] = fb;
            }
            return next;
          });
        } catch {
          // non-critical — feedback state remains as-is
        }
      }
      return response;
    },
    enabled: shouldLoadActiveSessionHistory,
  });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearchQuery(sessionSearchQuery.trim());
    }, 300);
    return () => {
      window.clearTimeout(timer);
    };
  }, [sessionSearchQuery]);

  useEffect(() => {
    if (!openSessionMenuId) return;
    const close = (event: MouseEvent) => {
      if (
        sessionMenuRef.current &&
        event.target instanceof Node &&
        sessionMenuRef.current.contains(event.target)
      ) {
        return;
      }
      setOpenSessionMenuId(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [openSessionMenuId]);

  useOverlayFocus({
    isOpen: confirmDeleteSessionId !== null,
    containerRef: deleteSessionModalRef,
    onClose: () => setConfirmDeleteSessionId(null),
  });

  const activeSession =
    sessions.find((item) => item.session_id === activeSessionId) ?? null;
  const deleteSessionCandidate = useMemo(
    () =>
      confirmDeleteSessionId
        ? (sessions.find(
            (session) => session.session_id === confirmDeleteSessionId,
          ) ?? null)
        : null,
    [confirmDeleteSessionId, sessions],
  );
  const thread = useMemo(
    () => threadsBySession[activeThreadKey(activeSessionId)] ?? [],
    [activeSessionId, threadsBySession],
  );
  const sessionDisplayTitleById = useMemo(() => {
    const mapped = new Map<string, string>();
    for (const session of sessions) {
      const sessionThread =
        threadsBySession[activeThreadKey(session.session_id)] ?? [];
      mapped.set(
        session.session_id,
        toSessionDisplayTitle(session.title, sessionThread),
      );
    }
    return mapped;
  }, [sessions, threadsBySession]);
  const activeSessionDisplayTitle = useMemo(() => {
    if (!activeSessionId) {
      return null;
    }
    return toSessionDisplayTitle(activeSession?.title, thread);
  }, [activeSession?.title, activeSessionId, thread]);
  const effectiveSelectedResponseMessageId = useMemo(() => {
    if (thread.length === 0) {
      return null;
    }
    if (
      selectedResponseMessageId &&
      thread.some(
        (turn) => turn.response.message_id === selectedResponseMessageId,
      )
    ) {
      return selectedResponseMessageId;
    }
    return thread[thread.length - 1].response.message_id;
  }, [selectedResponseMessageId, thread]);
  const selectedCitationTurn =
    thread.find(
      (turn) => turn.response.message_id === effectiveSelectedResponseMessageId,
    ) ??
    thread[thread.length - 1] ??
    null;

  const createSessionMutation = useMutation({
    mutationFn: (title: string | null) => createChatSession({ title }),
  });

  const updateSessionMutation = useMutation({
    mutationFn: ({
      sessionId,
      title,
    }: {
      sessionId: string;
      title: string | null;
    }) => updateChatSession(sessionId, { title }),
    onSuccess: async (updatedSession, variables) => {
      const { sessionId } = variables;
      const updateSessionInCache = (
        current: ChatSessionListInfiniteData | undefined,
      ): ChatSessionListInfiniteData | undefined => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          pages: current.pages.map((page) => ({
            ...page,
            items: (page.items ?? []).map((session: ChatSessionListItem) =>
              session.session_id === sessionId
                ? { ...session, title: updatedSession.title ?? null }
                : session,
            ),
          })),
        };
      };
      queryClient.setQueryData(
        queryKeys.chat.sessionsQuery(
          debouncedSearchQuery ? { search: debouncedSearchQuery } : undefined,
        ),
        updateSessionInCache,
      );
      queryClient.setQueriesData(
        { queryKey: queryKeys.chat.sessions },
        updateSessionInCache,
      );
      setEditingSessionId(null);
      setEditingSessionTitle("");
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => deleteChatSession(sessionId),
    onSuccess: async (_, deletedSessionId) => {
      if (activeSessionId === deletedSessionId) {
        resetForNewChat();
      }
      const removeDeletedSession = (
        current: ChatSessionListInfiniteData | undefined,
      ): ChatSessionListInfiniteData | undefined => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          pages: current.pages.map((page) => ({
            ...page,
            items: (page.items ?? []).filter(
              (session: ChatSessionListItem) =>
                session.session_id !== deletedSessionId,
            ),
            total:
              typeof page.total === "number"
                ? Math.max(0, page.total - 1)
                : page.total,
          })),
        };
      };
      queryClient.setQueryData(
        queryKeys.chat.sessionsQuery(
          debouncedSearchQuery ? { search: debouncedSearchQuery } : undefined,
        ),
        removeDeletedSession,
      );
      queryClient.setQueriesData(
        { queryKey: queryKeys.chat.sessions },
        removeDeletedSession,
      );
      setThreadsBySession((previous) => {
        const next = { ...previous };
        delete next[activeThreadKey(deletedSessionId)];
        return next;
      });
      await invalidateAfterMutation(queryClient, "chat.session.delete");
    },
  });

  function resetForNewChat() {
    setActiveSessionId(null);
    setSelectedResponseMessageId(null);
    setQuestion("");
    setPendingQuestion(null);
    setSubmitRequestId(null);
    replaceSessionParamInUrl(null);
  }

  const handleDeleteRequest = useCallback((sessionId: string) => {
    setConfirmDeleteSessionId(sessionId);
  }, []);

  const handleRenameRequest = useCallback(
    (sessionId: string, currentTitle: string | null) => {
      setOpenSessionMenuId(null);
      setConfirmDeleteSessionId(null);
      setEditingSessionId(sessionId);
      setEditingSessionTitle(currentTitle ?? "");
    },
    [],
  );

  const handleDeleteConfirm = useCallback(
    (sessionId: string) => {
      setConfirmDeleteSessionId(null);
      deleteSessionMutation.mutate(sessionId);
    },
    [deleteSessionMutation],
  );

  const handleDeleteCancel = useCallback(() => {
    setConfirmDeleteSessionId(null);
  }, []);

  const handleRenameCancel = useCallback(() => {
    setEditingSessionId(null);
    setEditingSessionTitle("");
  }, []);

  const handleRenameSave = useCallback(
    (sessionId: string) => {
      const nextTitle = editingSessionTitle.trim();
      updateSessionMutation.mutate({
        sessionId,
        title: nextTitle.length > 0 ? nextTitle : null,
      });
    },
    [editingSessionTitle, updateSessionMutation],
  );

  useEffect(() => {
    if (!editingSessionId) {
      return;
    }
    editSessionInputRef.current?.focus();
    editSessionInputRef.current?.select();
  }, [editingSessionId]);

  return {
    activeSessionId,
    setActiveSessionId,
    threadsBySession,
    setThreadsBySession,
    selectedResponseMessageId,
    setSelectedResponseMessageId,
    pendingQuestion,
    setPendingQuestion,
    submitRequestId,
    setSubmitRequestId,
    sessionSearchQuery,
    setSessionSearchQuery,
    debouncedSearchQuery,
    deleteSessionModalRef,
    deleteSessionOverlayRef,
    sessionMenuRef,
    editSessionInputRef,
    editingSessionId,
    editingSessionTitle,
    setEditingSessionTitle,
    openSessionMenuId,
    setOpenSessionMenuId,
    sessionsQuery,
    sessions,
    totalSessions,
    sessionMessagesQuery,
    hasOlderMessages: history.hasOlderMessages,
    isLoadingOlder: history.isLoadingOlder,
    olderMessagesError: history.olderMessagesError,
    loadOlderMessages: history.loadOlderMessages,
    activeSession,
    deleteSessionCandidate,
    thread,
    sessionDisplayTitleById,
    activeSessionDisplayTitle,
    selectedCitationTurn,
    createSessionMutation,
    updateSessionMutation,
    deleteSessionMutation,
    resetForNewChat,
    handleDeleteRequest,
    handleRenameRequest,
    handleDeleteConfirm,
    handleDeleteCancel,
    handleRenameCancel,
    handleRenameSave,
  };
}

export type ChatSessionController = ReturnType<typeof useChatSession>;
