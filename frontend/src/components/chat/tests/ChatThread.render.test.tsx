import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatThread } from "@/components/chat/ChatThread";
import { createStreamingTextStore } from "@/lib/chat/streaming-text-store";

import {
  makeThreadProps,
  makeTurns,
  manualFrames,
  sizeContainer,
} from "./chat-thread-fixtures";

vi.hoisted(() => {
  // CHAT_WEBSOCKET_ENABLED is a module-level constant frozen at import time.
  process.env.NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED = "true";
});

const commits = vi.hoisted(() => ({ turns: 0, streaming: 0 }));

// Wrap the real components in React Profilers. A wrapper re-renders whenever
// its parent does, so a turn Profiler also commits if ChatThread re-renders.
vi.mock("@/components/chat/ChatTurnItem", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/chat/ChatTurnItem")>();
  const { Profiler, createElement } = await import("react");
  function ProfiledTurn(props: Parameters<typeof actual.ChatTurnItem>[0]) {
    return createElement(
      Profiler,
      { id: "turn", onRender: () => void (commits.turns += 1) },
      createElement(actual.ChatTurnItem, props),
    );
  }
  return { ...actual, ChatTurnItem: ProfiledTurn };
});

vi.mock("@/components/chat/StreamingMessage", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/chat/StreamingMessage")>();
  const { Profiler, createElement } = await import("react");
  function ProfiledStreaming(
    props: Parameters<typeof actual.StreamingMessage>[0],
  ) {
    return createElement(
      Profiler,
      { id: "streaming", onRender: () => void (commits.streaming += 1) },
      createElement(actual.StreamingMessage, props),
    );
  }
  return { ...actual, StreamingMessage: ProfiledStreaming };
});

vi.mock("@/components/verified-answers/SuggestedKnowledgeCard", () => ({
  SuggestedKnowledgeCard: () => null,
}));

function wrap(children: ReactNode) {
  const client = new QueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  commits.turns = 0;
  commits.streaming = 0;
});

describe("ChatThread streaming render (R05-11)", () => {
  it("commits only the streaming message while 100 deltas stream into 20 turns", () => {
    const frames = manualFrames();
    const store = createStreamingTextStore(frames.scheduler);
    const props = makeThreadProps({
      thread: makeTurns(20),
      pendingQuestion: "What is new?",
      store,
    });
    render(wrap(<ChatThread {...props} />));
    expect(document.querySelectorAll("li[data-chat-turn]")).toHaveLength(20);
    // Mount (plus the commit that hands the scroll element to the virtualiser).
    expect(commits.turns).toBeGreaterThanOrEqual(20);

    commits.turns = 0;
    commits.streaming = 0;
    for (let i = 0; i < 100; i += 1) {
      act(() => {
        store.append(`token${i} `);
        frames.frame();
      });
    }

    expect(commits.turns).toBe(0);
    expect(commits.streaming).toBe(100);
    const answer = screen.getByTestId("streaming-answer");
    expect(answer).toHaveTextContent("token0");
    expect(answer).toHaveTextContent("token99");
    expect(answer).toHaveAttribute("data-stream-state", "provisional");
  });

  it("batches deltas that arrive within one frame into one commit", () => {
    const frames = manualFrames();
    const store = createStreamingTextStore(frames.scheduler);
    render(
      wrap(
        <ChatThread
          {...makeThreadProps({
            thread: makeTurns(3),
            pendingQuestion: "q",
            store,
          })}
        />,
      ),
    );
    commits.streaming = 0;
    act(() => {
      for (let i = 0; i < 50; i += 1) store.append("x");
    });
    expect(commits.streaming).toBe(0);
    act(() => frames.frame());
    expect(commits.streaming).toBe(1);
    expect(screen.getByTestId("streaming-answer").textContent).toContain(
      "x".repeat(50),
    );
  });

  it("renders replaced text, then the final text without the provisional cursor", () => {
    const frames = manualFrames();
    const store = createStreamingTextStore(frames.scheduler);
    render(
      wrap(
        <ChatThread {...makeThreadProps({ pendingQuestion: "q", store })} />,
      ),
    );
    act(() => {
      store.append("Unsupported draft");
      frames.frame();
    });
    act(() => {
      store.replace("Verified text");
      frames.frame();
    });
    const answer = screen.getByTestId("streaming-answer");
    expect(answer).toHaveTextContent("Verified text");
    expect(answer).not.toHaveTextContent("Unsupported draft");
    expect(answer).toHaveAttribute("aria-busy", "true");

    act(() => {
      store.replace("Final answer [1]", { final: true });
      frames.frame();
    });
    expect(answer).toHaveTextContent("Final answer [1]");
    expect(answer).toHaveAttribute("data-stream-state", "final");
    expect(answer).toHaveAttribute("aria-busy", "false");
    // No interactive citation markers while streaming.
    expect(answer.querySelector("button")).toBeNull();
  });

  it("keeps memoised turns when the parent re-renders with equal values", () => {
    const props = makeThreadProps({ thread: makeTurns(5) });
    const { rerender } = render(wrap(<ChatThread {...props} />));
    const before = document.querySelector('li[data-chat-turn="answer-0"]');
    rerender(wrap(<ChatThread {...props} overlays={{ ...props.overlays }} />));
    expect(document.querySelector('li[data-chat-turn="answer-0"]')).toBe(
      before,
    );
  });
});

describe("ChatThread virtualisation (R05-11)", () => {
  // jsdom has no layout: give the scroll container an 800 px viewport so the
  // virtualiser computes a visible range (rows keep the 320 px estimate).
  const original = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "offsetHeight",
  );
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.testid === "chat-thread" ? 800 : 0;
      },
    });
  });
  afterEach(() => {
    if (original) {
      Object.defineProperty(HTMLElement.prototype, "offsetHeight", original);
    }
  });

  it("renders a bounded number of rows for a 2,000-turn thread", () => {
    const props = makeThreadProps({ thread: makeTurns(2000) });
    render(wrap(<ChatThread {...props} />));
    const rows = document.querySelectorAll("li[data-chat-turn]");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThanOrEqual(30);
    expect(screen.getByTestId("chat-thread-virtual")).toBeInTheDocument();
    for (const row of rows) {
      expect(row).toHaveAttribute("data-index");
    }
  });

  it("does not virtualise at or below the threshold", () => {
    render(
      wrap(<ChatThread {...makeThreadProps({ thread: makeTurns(50) })} />),
    );
    expect(document.querySelectorAll("li[data-chat-turn]")).toHaveLength(50);
    expect(screen.queryByTestId("chat-thread-virtual")).toBeNull();
  });

  it("keeps the streaming message outside the virtual rows", () => {
    const props = makeThreadProps({
      thread: makeTurns(60),
      pendingQuestion: "Streaming question",
    });
    render(wrap(<ChatThread {...props} virtualizeMinTurns={10} />));
    expect(screen.getByText("Streaming question")).toBeInTheDocument();
    const rows = document.querySelectorAll("li[data-chat-turn]").length;
    expect(rows).toBeGreaterThan(0);
    expect(rows).toBeLessThan(60);
  });
});

describe("ChatThread scrolling and older history (R05-11)", () => {
  it("follows streamed text only while the user is at the bottom", () => {
    const frames = manualFrames();
    const store = createStreamingTextStore(frames.scheduler);
    const props = makeThreadProps({
      thread: makeTurns(10),
      pendingQuestion: "q",
      store,
    });
    const smooth = vi.fn();
    Object.defineProperty(window.HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: smooth,
    });
    render(wrap(<ChatThread {...props} />));
    const container = screen.getByTestId("chat-thread");
    sizeContainer(container);

    // The user scrolls up to read: new tokens must not move the view.
    container.scrollTop = 300;
    fireEvent.scroll(container);
    act(() => {
      store.append("hello");
      frames.frame();
    });
    expect(container.scrollTop).toBe(300);

    // Back at the bottom: the view follows, without smooth scrolling.
    container.scrollTop = container.scrollHeight - container.clientHeight;
    fireEvent.scroll(container);
    act(() => {
      store.append(" world");
      frames.frame();
    });
    expect(container.scrollTop).toBe(container.scrollHeight);
    expect(smooth).not.toHaveBeenCalled();
  });

  it("loads older pages at the top and keeps the scroll position", async () => {
    function Harness() {
      const [thread, setThread] = useState(makeTurns(5, 100));
      const [hasOlder, setHasOlder] = useState(true);
      const props = makeThreadProps({
        thread,
        hasOlderMessages: hasOlder,
        loadOlderMessages: async () => {
          setThread((current) => [...makeTurns(5, 0), ...current]);
          setHasOlder(false);
          return true;
        },
      });
      return <ChatThread {...props} />;
    }
    render(wrap(<Harness />));
    const container = screen.getByTestId("chat-thread");
    sizeContainer(container);
    expect(document.querySelectorAll("li[data-chat-turn]")).toHaveLength(5);

    container.scrollTop = 40;
    fireEvent.scroll(container);

    await waitFor(() =>
      expect(document.querySelectorAll("li[data-chat-turn]")).toHaveLength(10),
    );
    // Five rows of 100 px were added above: the same content stays in view.
    expect(container.scrollTop).toBe(540);
    const ids = Array.from(
      document.querySelectorAll("li[data-chat-turn]"),
      (row) => row.getAttribute("data-chat-turn"),
    );
    expect(ids[0]).toBe("answer-0");
    expect(ids[9]).toBe("answer-104");
    expect(
      screen.queryByRole("button", { name: /earlier messages/i }),
    ).toBeNull();
  });

  it("offers a button to load earlier messages and shows loading and retry", async () => {
    const loadOlderMessages = vi.fn(async () => false);
    const { rerender } = render(
      wrap(
        <ChatThread
          {...makeThreadProps({
            thread: makeTurns(2),
            hasOlderMessages: true,
            loadOlderMessages,
          })}
        />,
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Load earlier messages" }),
    );
    await waitFor(() => expect(loadOlderMessages).toHaveBeenCalledTimes(1));

    rerender(
      wrap(
        <ChatThread
          {...makeThreadProps({ thread: makeTurns(2), isLoadingOlder: true })}
        />,
      ),
    );
    expect(
      screen.getByRole("button", { name: "Loading earlier messages..." }),
    ).toBeDisabled();

    rerender(
      wrap(
        <ChatThread
          {...makeThreadProps({
            thread: makeTurns(2),
            hasOlderMessages: true,
            olderMessagesError: new Error("x"),
          })}
        />,
      ),
    );
    expect(
      screen.getByRole("button", { name: /Could not load earlier messages/ }),
    ).toBeEnabled();
  });

  it("routes turn actions through the stable handlers", async () => {
    const props = makeThreadProps({ thread: makeTurns(2) });
    render(wrap(<ChatThread {...props} />));
    fireEvent.click(screen.getAllByRole("button", { name: /Explain/i })[0]);
    expect(props.overlays.setOpenTrustPanelMessageId).toHaveBeenCalledWith(
      "answer-0",
    );
    expect(props.session.setSelectedResponseMessageId).toHaveBeenCalledWith(
      "answer-0",
    );
    fireEvent.click(screen.getAllByRole("button", { name: /Share/i })[0]);
    expect(props.overlays.setAnswerShareMessageId).toHaveBeenCalledWith(
      "answer-0",
    );
    fireEvent.click(screen.getAllByRole("button", { name: /helpful/i })[0]);
    expect(props.feedback.feedbackSubmitMutation.mutate).toHaveBeenCalledWith({
      messageId: "answer-0",
      rating: "up",
    });
    fireEvent.click(screen.getAllByRole("button", { name: /Report/i })[0]);
    expect(props.feedback.setFeedbackModalMessageId).toHaveBeenCalledWith(
      "answer-0",
    );
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    expect(props.submit.submitQuestionText).toHaveBeenCalledWith(
      "Question 1",
      false,
    );
  });
});
