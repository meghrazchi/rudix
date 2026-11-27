import { describe, expect, it } from "vitest";

import { nextTabForKey } from "@/lib/tablist-keyboard";

const TABS = ["a", "b", "c"] as const;

describe("nextTabForKey", () => {
  it("moves forward and backward with arrow keys, wrapping at the ends", () => {
    expect(nextTabForKey(TABS, "a", "ArrowRight")).toBe("b");
    expect(nextTabForKey(TABS, "c", "ArrowRight")).toBe("a");
    expect(nextTabForKey(TABS, "b", "ArrowLeft")).toBe("a");
    expect(nextTabForKey(TABS, "a", "ArrowLeft")).toBe("c");
  });

  it("jumps to the first and last tab with Home and End", () => {
    expect(nextTabForKey(TABS, "b", "Home")).toBe("a");
    expect(nextTabForKey(TABS, "b", "End")).toBe("c");
  });

  it("swaps arrow directions in right-to-left layouts", () => {
    expect(nextTabForKey(TABS, "a", "ArrowLeft", "rtl")).toBe("b");
    expect(nextTabForKey(TABS, "a", "ArrowRight", "rtl")).toBe("c");
  });

  it("ignores unrelated keys and empty tab lists", () => {
    expect(nextTabForKey(TABS, "a", "Enter")).toBeNull();
    expect(nextTabForKey([] as string[], "a", "ArrowRight")).toBeNull();
  });
});
