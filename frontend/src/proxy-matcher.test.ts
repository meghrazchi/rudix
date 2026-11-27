import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/middleware", () => ({ default: () => () => null }));

import { config } from "./proxy";

// The matcher is a path-to-regexp pattern; for these literal paths it behaves
// like an anchored regular expression.
const matcher = new RegExp(`^${config.matcher[0]}$`);

describe("proxy matcher", () => {
  it.each([
    "/robots.txt",
    "/sitemap.xml",
    "/llms.txt",
    "/icon.svg",
    "/fonts/pelak/Pelak-Regular.ttf",
    "/images/chat-sample-2.png",
    "/brand/rudix-mark.svg",
    "/api/health",
    "/_next/static/chunk.js",
  ])("skips locale handling for %s", (path) => {
    expect(matcher.test(path)).toBe(false);
  });

  it.each([
    "/",
    "/en",
    "/fa/pricing",
    "/de/solutions/legal",
    "/dashboard",
    "/chat/shared/abc_DEF-123",
  ])("runs locale handling for %s", (path) => {
    expect(matcher.test(path)).toBe(true);
  });
});
