import { describe, expect, it } from "vitest";

import {
  GLOBAL_ERROR_MESSAGES,
  resolveGlobalErrorLocale,
} from "@/i18n/global-error-messages";
import { SUPPORTED_LOCALES } from "@/i18n/routing";

describe("GLOBAL_ERROR_MESSAGES", () => {
  it.each(SUPPORTED_LOCALES)("has non-empty strings for %s", (locale) => {
    const messages = GLOBAL_ERROR_MESSAGES[locale];
    for (const key of [
      "title",
      "description",
      "retry",
      "home",
      "reference",
    ] as const) {
      expect(messages[key].trim().length).toBeGreaterThan(0);
    }
  });

  it("has no entries for unsupported locales", () => {
    expect(Object.keys(GLOBAL_ERROR_MESSAGES).sort()).toEqual(
      [...SUPPORTED_LOCALES].sort(),
    );
  });
});

describe("resolveGlobalErrorLocale", () => {
  it("prefers the html lang, ignoring the region", () => {
    expect(resolveGlobalErrorLocale("de-DE", "NEXT_LOCALE=fr")).toBe("de");
    expect(resolveGlobalErrorLocale("fa", "")).toBe("fa");
  });

  it("falls back to the NEXT_LOCALE cookie", () => {
    expect(resolveGlobalErrorLocale("", "a=1; NEXT_LOCALE=es; b=2")).toBe("es");
    expect(resolveGlobalErrorLocale(null, "NEXT_LOCALE=ar")).toBe("ar");
  });

  it("falls back to English for unknown or missing values", () => {
    expect(resolveGlobalErrorLocale("xx", "NEXT_LOCALE=zz")).toBe("en");
    expect(resolveGlobalErrorLocale(undefined, undefined)).toBe("en");
  });
});
