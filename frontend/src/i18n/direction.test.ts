import { describe, expect, it } from "vitest";

import { getLanguageCode, getLocaleDirection, isRtlLocale } from "./direction";

describe("locale direction", () => {
  it.each(["ar", "ar-SA", "fa_IR", "he-IL", "ur-PK"])(
    "detects %s as RTL",
    (locale) => {
      expect(getLocaleDirection(locale)).toBe("rtl");
      expect(isRtlLocale(locale)).toBe(true);
    },
  );

  it.each(["en", "de-DE", "es", "fr-FR", ""])("detects %s as LTR", (locale) =>
    expect(getLocaleDirection(locale)).toBe("ltr"),
  );

  it("normalizes region and underscore locale forms", () => {
    expect(getLanguageCode(" FA_ir ")).toBe("fa");
  });
});
