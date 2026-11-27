import { getLocale } from "next-intl/server";

import { RootDocument } from "@/components/layout/RootDocument";
import { NotFoundPage } from "@/components/public/pages/NotFoundPage";
import { loadMessages, pickMessages } from "@/i18n/messages";
import { PUBLIC_NAMESPACES } from "@/i18n/namespaces";
import type { SupportedLocale } from "@/i18n/routing";
import { ROOT_METADATA } from "@/lib/root-metadata";

// With two root layouts (app/[locale], app/(app)) there is no single layout to
// compose a 404 for unmatched URLs from, so Next renders this document instead
// (experimental.globalNotFound). RootDocument imports globals.css and fonts.
// Next adds robots noindex itself. The locale comes from the URL prefix (set
// by the proxy) or the NEXT_LOCALE cookie, as the old root layout did.
export const metadata = ROOT_METADATA;

export default async function GlobalNotFound() {
  const locale = (await getLocale()) as SupportedLocale;
  const messages = pickMessages(await loadMessages(locale), PUBLIC_NAMESPACES);

  return (
    <RootDocument locale={locale} messages={messages}>
      <NotFoundPage />
    </RootDocument>
  );
}
