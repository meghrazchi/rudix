import type { SupportedLocale } from "./routing";

export type MessageCatalogue = Record<string, unknown>;

export async function loadMessages(
  locale: SupportedLocale,
): Promise<MessageCatalogue> {
  return (await import(`./messages/${locale}.json`))
    .default as MessageCatalogue;
}

/**
 * Keep only the listed top-level namespaces (R07-02). Each root layout passes
 * the result to its single `NextIntlClientProvider`; nested providers do not
 * merge messages, so the list must be the full union the subtree needs.
 */
export function pickMessages(
  messages: MessageCatalogue,
  namespaces: readonly string[],
): MessageCatalogue {
  const picked: MessageCatalogue = {};
  for (const namespace of namespaces) {
    if (Object.prototype.hasOwnProperty.call(messages, namespace)) {
      picked[namespace] = messages[namespace];
    }
  }
  return picked;
}
