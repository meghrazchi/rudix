/**
 * Returns a screen-reader-only text span's CSS class string.
 * Prefer the Tailwind `sr-only` class directly; use this for dynamic
 * aria-live content injected outside the React tree.
 */
export const SR_ONLY_CLASS =
  "absolute w-px h-px p-0 -m-px overflow-hidden whitespace-nowrap border-0 clip-[rect(0,0,0,0)]";

/**
 * Announces a message via an existing aria-live region.
 * The region must have id="a11y-announcer" in the DOM.
 */
export function announce(
  message: string,
  priority: "polite" | "assertive" = "polite",
): void {
  const announcer = document.getElementById(
    priority === "assertive" ? "a11y-announcer-assertive" : "a11y-announcer",
  );
  if (!announcer) return;
  // Clear then set to ensure re-announcement of the same string.
  announcer.textContent = "";
  requestAnimationFrame(() => {
    announcer.textContent = message;
  });
}
