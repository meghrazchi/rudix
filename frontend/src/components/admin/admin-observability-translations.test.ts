import { describe, expect, it } from "vitest";
import { SUPPORTED_LOCALES } from "@/i18n/routing";
import { getAdminObservabilityTranslations } from "./admin-observability-translations";

describe("admin observability translations", () => {
  it.each(SUPPORTED_LOCALES)(
    "provides complete translations for %s",
    (locale) => {
      const translations = getAdminObservabilityTranslations(locale);
      expect(Object.keys(translations).length).toBeGreaterThan(50);
      expect(
        Object.values(translations).every((value) => value.trim().length > 0),
      ).toBe(true);
    },
  );

  it.each(["de", "es", "fr", "fa", "ar"] as const)(
    "does not fall back to English headings for %s",
    (locale) => {
      const translations = getAdminObservabilityTranslations(locale);
      expect(translations.intro).not.toContain("API health");
      expect(translations.providerHealth).not.toBe("Provider health");
    },
  );
});
