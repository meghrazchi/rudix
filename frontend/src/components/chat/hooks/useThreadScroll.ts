import { useCallback, useLayoutEffect, useRef, type RefObject } from "react";

/** Within this many pixels of the end the user counts as "at the bottom". */
export const AT_BOTTOM_THRESHOLD_PX = 48;
/** Scrolling this close to the top loads the next older history page. */
export const LOAD_OLDER_THRESHOLD_PX = 80;

type Anchor = { height: number; top: number; firstTurnId: string | null };

/**
 * Scroll policy of the chat thread (R05-11):
 *  - jump (no smooth scrolling) to the bottom when the session changes or the
 *    user sends a question;
 *  - follow new content (streamed text, a finished turn) only while the user
 *    is at the bottom, so reading older turns is never interrupted;
 *  - when an older page is prepended, keep the visible content in place.
 */
export function useThreadScroll({
  containerRef,
  activeSessionId,
  turnCount,
  firstTurnId,
  pendingQuestion,
  canLoadOlder,
  loadOlder,
}: {
  containerRef: RefObject<HTMLDivElement | null>;
  activeSessionId: string | null;
  turnCount: number;
  firstTurnId: string | null;
  pendingQuestion: string | null;
  canLoadOlder: boolean;
  loadOlder: () => Promise<boolean>;
}) {
  const atBottomRef = useRef(true);
  const anchorRef = useRef<Anchor | null>(null);
  const scrollToEndRef = useRef<(() => void) | null>(null);
  const latestRef = useRef({ canLoadOlder, loadOlder, firstTurnId });
  useLayoutEffect(() => {
    latestRef.current = { canLoadOlder, loadOlder, firstTurnId };
  });

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    scrollToEndRef.current?.();
    el.scrollTop = el.scrollHeight;
    atBottomRef.current = true;
  }, [containerRef]);

  const followIfAtBottom = useCallback(() => {
    if (atBottomRef.current) scrollToBottom();
  }, [scrollToBottom]);

  const loadOlderAnchored = useCallback(async (): Promise<boolean> => {
    const el = containerRef.current;
    const { loadOlder: load, firstTurnId: first } = latestRef.current;
    anchorRef.current = el
      ? { height: el.scrollHeight, top: el.scrollTop, firstTurnId: first }
      : null;
    const loaded = await load();
    if (!loaded) anchorRef.current = null;
    return loaded;
  }, [containerRef]);

  const onScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    atBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <=
      AT_BOTTOM_THRESHOLD_PX;
    if (
      el.scrollTop <= LOAD_OLDER_THRESHOLD_PX &&
      latestRef.current.canLoadOlder &&
      anchorRef.current === null
    ) {
      void loadOlderAnchored();
    }
  }, [containerRef, loadOlderAnchored]);

  const registerScrollToEnd = useCallback((scrollToEnd: () => void) => {
    scrollToEndRef.current = scrollToEnd;
    return () => {
      if (scrollToEndRef.current === scrollToEnd) scrollToEndRef.current = null;
    };
  }, []);

  // A different session always opens at its newest message.
  useLayoutEffect(() => {
    anchorRef.current = null;
    scrollToBottom();
  }, [activeSessionId, scrollToBottom]);

  // The user's own question always brings the view to the bottom.
  useLayoutEffect(() => {
    if (pendingQuestion) scrollToBottom();
  }, [pendingQuestion, scrollToBottom]);

  useLayoutEffect(() => {
    const el = containerRef.current;
    const anchor = anchorRef.current;
    if (el && anchor && anchor.firstTurnId !== firstTurnId) {
      // Older turns were prepended: keep the same content under the viewport.
      el.scrollTop = el.scrollHeight - anchor.height + anchor.top;
      anchorRef.current = null;
      return;
    }
    followIfAtBottom();
  }, [containerRef, turnCount, firstTurnId, followIfAtBottom]);

  return {
    onScroll,
    followIfAtBottom,
    loadOlderAnchored,
    registerScrollToEnd,
    isAtBottom: () => atBottomRef.current,
  };
}
