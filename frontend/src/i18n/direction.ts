export type LocaleDirection = "ltr" | "rtl";

/** Languages whose scripts are conventionally rendered right-to-left. */
export const RTL_LANGUAGE_CODES = [
  "ar",
  "fa",
  "he",
  "ur",
  "ps",
  "sd",
  "ug",
  "yi",
] as const;

const RTL_LANGUAGE_SET = new Set<string>(RTL_LANGUAGE_CODES);

export function getLanguageCode(locale: string): string {
  return locale.trim().toLowerCase().split(/[-_]/, 1)[0] ?? "";
}

export function getLocaleDirection(locale: string): LocaleDirection {
  return RTL_LANGUAGE_SET.has(getLanguageCode(locale)) ? "rtl" : "ltr";
}

export function isRtlLocale(locale: string): boolean {
  return getLocaleDirection(locale) === "rtl";
}
