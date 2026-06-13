import type { SupportedLocale } from "@/i18n/routing";

const LOCALE_DATE_OPTIONS: Record<SupportedLocale, Intl.DateTimeFormatOptions> =
  {
    en: { month: "short", day: "numeric", year: "numeric" },
    de: { day: "numeric", month: "long", year: "numeric" },
    es: { day: "numeric", month: "long", year: "numeric" },
    fr: { day: "numeric", month: "long", year: "numeric" },
  };

const LOCALE_TIME_OPTIONS: Record<SupportedLocale, Intl.DateTimeFormatOptions> =
  {
    en: { hour: "numeric", minute: "2-digit", hour12: true },
    de: { hour: "2-digit", minute: "2-digit", hour12: false },
    es: { hour: "2-digit", minute: "2-digit", hour12: false },
    fr: { hour: "2-digit", minute: "2-digit", hour12: false },
  };

export function formatDate(
  date: Date | string | number,
  locale: SupportedLocale,
): string {
  const d = typeof date === "object" ? date : new Date(date);
  return new Intl.DateTimeFormat(locale, LOCALE_DATE_OPTIONS[locale]).format(d);
}

export function formatDateTime(
  date: Date | string | number,
  locale: SupportedLocale,
): string {
  const d = typeof date === "object" ? date : new Date(date);
  return new Intl.DateTimeFormat(locale, {
    ...LOCALE_DATE_OPTIONS[locale],
    ...LOCALE_TIME_OPTIONS[locale],
  }).format(d);
}

export function formatRelativeTime(
  date: Date | string | number,
  locale: SupportedLocale,
): string {
  const d = typeof date === "object" ? date : new Date(date);
  const now = Date.now();
  const diffMs = d.getTime() - now;
  const diffSec = Math.round(diffMs / 1000);
  const diffMin = Math.round(diffSec / 60);
  const diffHr = Math.round(diffMin / 60);
  const diffDay = Math.round(diffHr / 24);

  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });

  if (Math.abs(diffSec) < 60) return rtf.format(diffSec, "second");
  if (Math.abs(diffMin) < 60) return rtf.format(diffMin, "minute");
  if (Math.abs(diffHr) < 24) return rtf.format(diffHr, "hour");
  if (Math.abs(diffDay) < 30) return rtf.format(diffDay, "day");

  return formatDate(d, locale);
}

export function formatNumber(
  value: number,
  locale: SupportedLocale,
  options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(locale, options).format(value);
}

export function formatPercent(
  value: number,
  locale: SupportedLocale,
  fractionDigits = 1,
): string {
  return new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

const FILE_SIZE_UNITS: Array<[string, number]> = [
  ["TB", 1024 ** 4],
  ["GB", 1024 ** 3],
  ["MB", 1024 ** 2],
  ["KB", 1024],
];

export function formatFileSize(bytes: number, locale: SupportedLocale): string {
  for (const [unit, threshold] of FILE_SIZE_UNITS) {
    if (bytes >= threshold) {
      return `${formatNumber(bytes / threshold, locale, { maximumFractionDigits: 1 })} ${unit}`;
    }
  }
  return `${formatNumber(bytes, locale)} B`;
}

export function getHtmlLang(locale: SupportedLocale): string {
  const langMap: Record<SupportedLocale, string> = {
    en: "en-US",
    de: "de-DE",
    es: "es-ES",
    fr: "fr-FR",
  };
  return langMap[locale];
}

export function buildHreflangAlternates(
  pathname: string,
  origin: string,
): Array<{ hreflang: string; href: string }> {
  return [
    ...SUPPORTED_LOCALES_FOR_HREFLANG.map((locale) => ({
      hreflang: getHtmlLang(locale),
      href: `${origin}${pathname}`,
    })),
    { hreflang: "x-default", href: `${origin}${pathname}` },
  ];
}

const SUPPORTED_LOCALES_FOR_HREFLANG: SupportedLocale[] = [
  "en",
  "de",
  "es",
  "fr",
];
