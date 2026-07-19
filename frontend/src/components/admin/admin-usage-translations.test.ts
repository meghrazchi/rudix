import { describe, expect, it } from "vitest";

import { SUPPORTED_LOCALES } from "@/i18n/routing";
import {
  getAdminUsageMetricTitles,
  getAdminUsageTranslations,
} from "./admin-usage-translations";

describe("admin usage translations", () => {
  it.each(SUPPORTED_LOCALES)(
    "provides complete translations for %s",
    (locale) => {
      const translations = getAdminUsageTranslations(locale);
      expect(
        Object.values(translations).every((value) => value.trim().length > 0),
      ).toBe(true);
      expect(getAdminUsageMetricTitles(locale)).toHaveLength(12);
    },
  );

  it.each(["de", "es", "fr", "fa", "ar"] as const)(
    "does not fall back to English headings for %s",
    (locale) => {
      const translations = getAdminUsageTranslations(locale);
      expect(translations.title).not.toBe("Usage & cost dashboard");
      expect(translations.topUsers).not.toBe("Top users by estimated cost");
    },
  );
});
