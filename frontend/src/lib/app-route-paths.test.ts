import { describe, expect, it } from "vitest";
import {
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
