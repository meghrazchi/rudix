import { describe, expect, it } from "vitest";

import { createAdminLandingTranslations } from "./admin-landing-translations";
import { SUPPORTED_LOCALES } from "@/i18n/routing";

describe("admin landing translations", () => {
  it.each(SUPPORTED_LOCALES)(
    "provides complete translations for %s",
    (locale) => {
      const translations = createAdminLandingTranslations(locale);

      expect(translations.title.trim()).not.toBe("");
      expect(translations.intro.trim()).not.toBe("");
      expect(translations.restrictedDescription.trim()).not.toBe("");
      expect(translations.text("Usage Analytics").trim()).not.toBe("");
      expect(translations.text("SCIM Provisioning").trim()).not.toBe("");
    },
  );

  it.each(["de", "es", "fr", "fa", "ar"] as const)(
    "does not expose English admin titles in %s",
    (locale) => {
      const translations = createAdminLandingTranslations(locale);
      expect(translations.title).not.toBe("Admin Landing");
      expect(translations.text("Usage Analytics")).not.toBe("Usage Analytics");
      expect(translations.text("Security Center")).not.toBe("Security Center");
    },
  );
});
