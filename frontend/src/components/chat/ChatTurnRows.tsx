import { useLayoutEffect, type ReactNode } from "react";

import { useVirtualizer } from "@tanstack/react-virtual";

/** Gap between turns; matches `space-y-12` of the plain list. */
export const TURN_GAP_PX = 48;
export const ESTIMATED_TURN_HEIGHT_PX = 320;
export const TURN_OVERSCAN = 4;

/**
 * Virtualised list of completed turns (R05-11), used above
 * NEXT_PUBLIC_CHAT_VIRTUALIZE_MIN_TURNS. Only the rows near the viewport are
 * mounted; each row is measured after render (`measureElement`), so answers
 * of any height work.
 */
export function ChatTurnRows({
  count,
  scrollElement,
  getItemKey,
  renderTurn,
  registerScrollToEnd,
}: {
  count: number;
  scrollElement: HTMLDivElement | null;
  getItemKey: (index: number) => string;
  renderTurn: (
    index: number,
    measureRef: (element: Element | null) => void,
  ) => ReactNode;
  registerScrollToEnd: (scrollToEnd: () => void) => () => void;
}) {
  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => scrollElement,
    estimateSize: () => ESTIMATED_TURN_HEIGHT_PX,
    overscan: TURN_OVERSCAN,
    gap: TURN_GAP_PX,
    getItemKey,
  });

  useLayoutEffect(
    () =>
      registerScrollToEnd(() => {
        if (count > 0) virtualizer.scrollToIndex(count - 1, { align: "end" });
      }),
    [count, registerScrollToEnd, virtualizer],
  );

  const items = virtualizer.getVirtualItems();
  return (
    <div
      className="relative mx-auto w-full max-w-3xl"
      style={{ height: virtualizer.getTotalSize() }}
      data-testid="chat-thread-virtual"
    >
      <ul
        className="absolute top-0 left-0 flex w-full flex-col gap-12"
        style={{ transform: `translateY(${items[0]?.start ?? 0}px)` }}
      >
        {items.map((item) =>
          renderTurn(item.index, virtualizer.measureElement),
        )}
      </ul>
    </div>
  );
}
