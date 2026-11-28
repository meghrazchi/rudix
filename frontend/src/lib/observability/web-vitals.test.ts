import { describe, expect, it, vi } from "vitest";

import {
  MAX_BATCH_SIZE,
  createWebVitalsBatcher,
  toRoutePattern,
  toWebVitalSample,
  type WebVitalSample,
} from "@/lib/observability/web-vitals";

describe("toRoutePattern", () => {
  it.each([
    ["/en", "/[locale]"],
    ["/de/pricing", "/[locale]/pricing"],
    ["/en/solutions/hr", "/[locale]/solutions/hr"],
    ["/", "/"],
    ["", "/"],
    ["/dashboard", "/dashboard"],
    ["/documents/3f2504e0-4f89-41d3-9a0c-0305e82c3301", "/documents/[id]"],
    ["/documents/12345", "/documents/[id]"],
    ["/chat/shared/9f86d081884c7d659a2feaa0c55ad015", "/chat/shared/[id]"],
    ["/chat/shared/abcDEF123456ghiJKL789", "/chat/shared/[id]"],
    ["/organization-onboarding", "/organization-onboarding"],
    ["/documents/some%20name", "/documents/[id]"],
    ["/dashboard?tab=1#x", "/dashboard"],
    ["/fr/accept-invite/42", "/[locale]/accept-invite/[id]"],
  ])("maps %s to %s", (input, expected) => {
    expect(toRoutePattern(input)).toBe(expected);
  });

  it("does not treat a later locale-like segment as the locale", () => {
    expect(toRoutePattern("/docs/en")).toBe("/docs/en");
  });

  it("caps very long paths and stays within the accepted charset", () => {
    const route = toRoutePattern(`/${"a-".repeat(200)}`);
    expect(route.length).toBeLessThanOrEqual(121);
    expect(route).toMatch(/^\/[A-Za-z0-9[\]_/-]{0,120}$/);
  });
});

describe("toWebVitalSample", () => {
  it("builds a sample with a route pattern", () => {
    expect(
      toWebVitalSample(
        {
          name: "LCP",
          value: 1234.5,
          rating: "good",
          navigationType: "navigate",
        },
        "/de/pricing",
      ),
    ).toEqual({
      name: "LCP",
      value: 1234.5,
      route: "/[locale]/pricing",
      rating: "good",
      navigation_type: "navigate",
    });
  });

  it("omits unknown navigation types and defaults unknown ratings", () => {
    expect(
      toWebVitalSample(
        { name: "CLS", value: 0.1, rating: "weird", navigationType: "x" },
        "/dashboard",
      ),
    ).toEqual({
      name: "CLS",
      value: 0.1,
      route: "/dashboard",
      rating: "needs-improvement",
    });
    expect(
      toWebVitalSample({ name: "CLS", value: 0.1 }, "/dashboard")?.rating,
    ).toBe("needs-improvement");
  });

  it("drops unsupported metrics and invalid values", () => {
    expect(toWebVitalSample({ name: "FID", value: 3 }, "/")).toBeNull();
    expect(
      toWebVitalSample({ name: "Next.js-hydration", value: 3 }, "/"),
    ).toBeNull();
    expect(toWebVitalSample({ name: "LCP", value: -1 }, "/")).toBeNull();
    expect(
      toWebVitalSample({ name: "LCP", value: Number.NaN }, "/"),
    ).toBeNull();
  });
});

function sample(index: number): WebVitalSample {
  return { name: "LCP", value: index, route: "/", rating: "good" };
}

describe("createWebVitalsBatcher", () => {
  it("sends nothing until flushed or full", () => {
    const send = vi.fn();
    const batcher = createWebVitalsBatcher(send);
    batcher.add(sample(1));
    batcher.add(sample(2));
    expect(send).not.toHaveBeenCalled();

    batcher.flush();
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0][0]).toHaveLength(2);

    batcher.flush();
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("flushes automatically at the batch limit", () => {
    const send = vi.fn();
    const batcher = createWebVitalsBatcher(send);
    for (let i = 0; i < MAX_BATCH_SIZE; i += 1) {
      batcher.add(sample(i));
    }
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0][0]).toHaveLength(MAX_BATCH_SIZE);
  });

  it("discard drops pending samples", () => {
    const send = vi.fn();
    const batcher = createWebVitalsBatcher(send);
    batcher.add(sample(1));
    batcher.discard();
    batcher.flush();
    expect(send).not.toHaveBeenCalled();
  });
});
