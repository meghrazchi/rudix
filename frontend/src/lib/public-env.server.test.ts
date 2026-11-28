// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { publicEnv, publicEnvSource } from "./public-env";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("publicEnv on the server", () => {
  it("returns the build value in build mode", () => {
    vi.stubEnv("NEXT_PUBLIC_GA_ID", "G-RUNTIME");
    expect(publicEnv("NEXT_PUBLIC_GA_ID", "G-BUILD")).toBe("G-BUILD");
  });

  it("reads the runtime environment in request mode", () => {
    vi.stubEnv("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", "request");
    vi.stubEnv("NEXT_PUBLIC_GA_ID", "G-RUNTIME");
    expect(publicEnv("NEXT_PUBLIC_GA_ID", "G-BUILD")).toBe("G-RUNTIME");
    vi.stubEnv("NEXT_PUBLIC_GA_ID", undefined);
    expect(publicEnv("NEXT_PUBLIC_GA_ID", "G-BUILD")).toBe("G-BUILD");
    expect(publicEnvSource()).toBe(process.env);
  });
});
