import type { SupportedLocale } from "./routing";

export async function loadMessages(
  locale: SupportedLocale,
): Promise<Record<string, unknown>> {
  return (await import(`./messages/${locale}.json`)).default as Record<
    string,
    unknown
  >;
}
