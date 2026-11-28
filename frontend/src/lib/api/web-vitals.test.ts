import { afterEach, describe, expect, it, vi } from "vitest";

import { postWebVitals } from "@/lib/api/web-vitals";

const samples = [
  { name: "LCP" as const, value: 10, route: "/", rating: "good" as const },
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("postWebVitals", () => {
  it("posts JSON without credentials or Authorization", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchSpy);

    await postWebVitals(samples);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/telemetry\/web-vitals$/);
    expect(init.method).toBe("POST");
    expect(init.keepalive).toBe(true);
    expect(init.credentials).toBe("omit");
    expect(
      Object.keys(init.headers as object).map((k) => k.toLowerCase()),
    ).toEqual(["content-type"]);
    expect(JSON.parse(String(init.body))).toEqual({ samples });
  });

  it("does nothing for an empty batch", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    await postWebVitals([]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("swallows network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(postWebVitals(samples)).resolves.toBeUndefined();
  });
});
