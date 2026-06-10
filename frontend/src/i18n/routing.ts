import { defineRouting } from "next-intl/routing";

export const SUPPORTED_LOCALES = ["en", "de", "es", "fr"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: SupportedLocale = "en";
export const LOCALE_COOKIE_NAME = "NEXT_LOCALE";

export const routing = defineRouting({
  locales: SUPPORTED_LOCALES,
  defaultLocale: DEFAULT_LOCALE,
  localePrefix: "always",
});

export function isValidLocale(value: unknown): value is SupportedLocale {
  return (
    typeof value === "string" &&
    (SUPPORTED_LOCALES as readonly string[]).includes(value)
  );
}

export function resolveLocale(
  cookieValue: string | undefined,
  acceptLanguageHeader: string | undefined,
): SupportedLocale {
  if (isValidLocale(cookieValue)) {
    return cookieValue;
  }

  if (acceptLanguageHeader) {
    const detected = parseAcceptLanguage(acceptLanguageHeader);
    if (detected) {
      return detected;
    }
  }

  return DEFAULT_LOCALE;
}

function parseAcceptLanguage(
  header: string,
): SupportedLocale | undefined {
  const entries = header
    .split(",")
    .map((entry) => {
      const [tag, q] = entry.trim().split(";q=");
      const quality = q ? parseFloat(q) : 1.0;
      return { tag: (tag ?? "").trim().toLowerCase(), quality };
    })
    .sort((a, b) => b.quality - a.quality);

  for (const { tag } of entries) {
    const lang = tag.split("-")[0] ?? tag;
    if (isValidLocale(lang)) {
      return lang;
    }
  }
  return undefined;
}
