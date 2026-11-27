/**
 * Keyboard model for an ARIA tablist (WAI-ARIA APG "Tabs" pattern with
 * automatic activation): Left/Right move between tabs and wrap, Home/End jump
 * to the first/last tab. In right-to-left layouts the arrow keys are swapped
 * so they follow the visual order.
 *
 * Returns the tab id to activate, or null when the key is not handled.
 */
export function nextTabForKey<T extends string>(
  tabIds: readonly T[],
  activeId: T,
  key: string,
  direction: "ltr" | "rtl" = "ltr",
): T | null {
  if (tabIds.length === 0) return null;
  const current = Math.max(0, tabIds.indexOf(activeId));
  const last = tabIds.length - 1;
  const forward = direction === "rtl" ? "ArrowLeft" : "ArrowRight";
  const backward = direction === "rtl" ? "ArrowRight" : "ArrowLeft";

  switch (key) {
    case forward:
      return tabIds[current === last ? 0 : current + 1];
    case backward:
      return tabIds[current === 0 ? last : current - 1];
    case "Home":
      return tabIds[0];
    case "End":
      return tabIds[last];
    default:
      return null;
  }
}
