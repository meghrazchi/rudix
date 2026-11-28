import { readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";
import {
  AUTHENTICATED_APP_ROUTE_SEGMENTS,
  isAuthenticatedAppPath,
  parseLocalePrefixedAppPath,
} from "@/lib/app-route-paths";

describe("authenticated app route paths", () => {
  it("recognizes reports as an unprefixed authenticated route", () => {
    expect(isAuthenticatedAppPath("/reports")).toBe(true);
    expect(isAuthenticatedAppPath("/reports/answer-quality")).toBe(true);
  });

  it("normalizes locale-prefixed report paths", () => {
    expect(parseLocalePrefixedAppPath("/en/reports/answer-quality")).toEqual({
      locale: "en",
      pathname: "/reports/answer-quality",
    });
  });

  it("does not strip locales from public routes", () => {
    expect(parseLocalePrefixedAppPath("/en/pricing")).toBeNull();
  });
});

describe("authenticated app route segments (R07-09)", () => {
  it("covers every route directory under src/app/(app)", () => {
    const appDir = path.resolve(__dirname, "../app/(app)");
    const routeSegments = readdirSync(appDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      // Route groups, private folders and dynamic segments are not URL prefixes.
      .filter((name) => !/^[([_@]/.test(name));

    expect(routeSegments.length).toBeGreaterThan(0);
    for (const segment of routeSegments) {
      expect(AUTHENTICATED_APP_ROUTE_SEGMENTS).toContain(segment);
      expect(isAuthenticatedAppPath(`/${segment}`)).toBe(true);
    }
  });

  it("treats /knowledge as an authenticated app path", () => {
    expect(isAuthenticatedAppPath("/knowledge")).toBe(true);
    expect(parseLocalePrefixedAppPath("/de/knowledge")).toEqual({
      locale: "de",
      pathname: "/knowledge",
    });
  });
});
