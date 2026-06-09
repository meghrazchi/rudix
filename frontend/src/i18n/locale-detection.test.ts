import { describe, expect, it } from "vitest";

import {
  DEFAULT_LOCALE,
  isValidLocale,
  resolveLocale,
  SUPPORTED_LOCALES,
} from "./routing";

describe("isValidLocale", () => {
  it("returns true for each supported locale", () => {
    for (const locale of SUPPORTED_LOCALES) {
      expect(isValidLocale(locale)).toBe(true);
    }
  });

  it("returns false for unsupported values", () => {
    expect(isValidLocale("ja")).toBe(false);
    expect(isValidLocale("zh")).toBe(false);
    expect(isValidLocale("")).toBe(false);
    expect(isValidLocale(null)).toBe(false);
    expect(isValidLocale(undefined)).toBe(false);
    expect(isValidLocale(42)).toBe(false);
  });
});

describe("resolveLocale", () => {
  it("returns cookie locale when valid", () => {
    expect(resolveLocale("de", undefined)).toBe("de");
    expect(resolveLocale("fr", "en")).toBe("fr");
    expect(resolveLocale("es", "de,en;q=0.8")).toBe("es");
  });

  it("falls back to Accept-Language header when cookie is missing", () => {
    expect(resolveLocale(undefined, "de-DE,de;q=0.9,en;q=0.8")).toBe("de");
    expect(resolveLocale(undefined, "fr-FR,fr;q=0.9")).toBe("fr");
    expect(resolveLocale(undefined, "es-ES,es;q=0.9,en;q=0.5")).toBe("es");
  });

  it("falls back to Accept-Language when cookie is invalid", () => {
    expect(resolveLocale("ja", "de-DE,de;q=0.9")).toBe("de");
    expect(resolveLocale("zh", "fr")).toBe("fr");
  });

  it("returns default locale when nothing matches", () => {
    expect(resolveLocale(undefined, undefined)).toBe(DEFAULT_LOCALE);
    expect(resolveLocale(undefined, "ja,zh;q=0.8")).toBe(DEFAULT_LOCALE);
    expect(resolveLocale("invalid", "ko,ja")).toBe(DEFAULT_LOCALE);
  });

  it("picks highest quality match from Accept-Language", () => {
    expect(resolveLocale(undefined, "fr;q=0.9,de;q=0.7,en;q=0.5")).toBe("fr");
    expect(resolveLocale(undefined, "en;q=0.9,de;q=0.8")).toBe("en");
  });

  it("handles language-only tags (without region)", () => {
    expect(resolveLocale(undefined, "de,en;q=0.9")).toBe("de");
    expect(resolveLocale(undefined, "fr,en;q=0.9")).toBe("fr");
  });
});

describe("SUPPORTED_LOCALES", () => {
  it("includes exactly en, de, es, fr", () => {
    expect(SUPPORTED_LOCALES).toHaveLength(4);
    expect(SUPPORTED_LOCALES).toContain("en");
    expect(SUPPORTED_LOCALES).toContain("de");
    expect(SUPPORTED_LOCALES).toContain("es");
    expect(SUPPORTED_LOCALES).toContain("fr");
  });

  it("has en as the default locale", () => {
    expect(DEFAULT_LOCALE).toBe("en");
  });
});
