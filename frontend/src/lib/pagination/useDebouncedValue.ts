"use client";

import { useEffect, useState } from "react";

export const SEARCH_DEBOUNCE_MS = 300;

/** `value` after it has stopped changing for `delayMs`. */
export function useDebouncedValue<T>(
  value: T,
  delayMs: number = SEARCH_DEBOUNCE_MS,
): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
