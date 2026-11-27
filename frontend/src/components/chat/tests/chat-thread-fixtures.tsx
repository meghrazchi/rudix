import { vi } from "vitest";

import { toTurnResponseFromHistoryMessage } from "@/components/chat/chat-turns";
import type { ChatTurn } from "@/components/chat/chat-types";
import type { ChatThread } from "@/components/chat/ChatThread";
import type { ChatSessionMessageResponse } from "@/lib/api/chat";
import {
  createStreamingTextStore,
  type FrameScheduler,
  type StreamingTextStore,
} from "@/lib/chat/streaming-text-store";

type ThreadProps = Parameters<typeof ChatThread>[0];

export function makeTurn(index: number): ChatTurn {
  return {
    question: `Question ${index}`,
    response: toTurnResponseFromHistoryMessage({
      message_id: `answer-${index}`,
      role: "assistant",
      content: `Answer ${index}`,
      confidence_score: 0.9,
      confidence_category: "high",
      citations: [],
      created_at: "2026-05-14T10:00:00Z",
    } as ChatSessionMessageResponse),
  };
}

export function makeTurns(count: number, offset = 0): ChatTurn[] {
  return Array.from({ length: count }, (_, i) => makeTurn(i + offset));
}

/** Frames advance only when the test calls `frame()`. */
export function manualFrames() {
  const queue: Array<() => void> = [];
  const scheduler: FrameScheduler = {
    schedule: (callback) => {
      queue.push(callback);
      return queue.length;
    },
    cancel: () => undefined,
  };
  return {
    scheduler,
    frame: () => {
      for (const callback of queue.splice(0)) callback();
    },
  };
}

export function makeThreadProps(
  overrides: {
    thread?: ChatTurn[];
    pendingQuestion?: string | null;
    store?: StreamingTextStore;
    hasOlderMessages?: boolean;
    isLoadingOlder?: boolean;
    olderMessagesError?: unknown;
    loadOlderMessages?: () => Promise<boolean>;
    activeSessionId?: string | null;
  } = {},
): ThreadProps {
  const store = overrides.store ?? createStreamingTextStore();
  const session = {
    activeSessionId: overrides.activeSessionId ?? "session-1",
    activeSession: null,
    thread: overrides.thread ?? [],
    pendingQuestion: overrides.pendingQuestion ?? null,
    sessionMessagesQuery: {
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    },
    setSelectedResponseMessageId: vi.fn(),
    hasOlderMessages: overrides.hasOlderMessages ?? false,
    isLoadingOlder: overrides.isLoadingOlder ?? false,
    olderMessagesError: overrides.olderMessagesError ?? null,
    loadOlderMessages: overrides.loadOlderMessages ?? vi.fn(async () => false),
  } as unknown as ThreadProps["session"];
  return {
    session,
    panel: {
      setIsKnowledgeHubOpen: vi.fn(),
      setPreviewCitationSet: vi.fn(),
    },
    feedback: {
      chatFeedbackEnabled: true,
      feedbackByMessageId: {},
      feedbackDeleteMutation: { mutate: vi.fn() },
      feedbackSubmitMutation: { mutate: vi.fn() },
      setFeedbackModalMessageId: vi.fn(),
    } as unknown as ThreadProps["feedback"],
    overlays: {
      openTrustPanelMessageId: null,
      setOpenTrustPanelMessageId: vi.fn(),
      copiedMessageId: null,
      setCopiedMessageId: vi.fn(),
      setAnswerShareMessageId: vi.fn(),
    },
    submit: {
      stream: {
        textStore: store,
        timelineSteps: [],
        phaseLabel: "Generating answer...",
      },
      regenerateDisabled: false,
      submitQuestionText: vi.fn(async () => undefined),
    } as unknown as ThreadProps["submit"],
    selectedCollectionIds: [],
  };
}

/** Give the scroll container a size and a writable scroll position. */
export function sizeContainer(
  element: HTMLElement,
  { clientHeight = 400, rowHeight = 100 } = {},
) {
  let scrollTop = 0;
  Object.defineProperty(element, "clientHeight", {
    configurable: true,
    get: () => clientHeight,
  });
  Object.defineProperty(element, "scrollHeight", {
    configurable: true,
    get: () => element.querySelectorAll("li").length * rowHeight,
  });
  Object.defineProperty(element, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (value: number) => {
      scrollTop = value;
    },
  });
}
