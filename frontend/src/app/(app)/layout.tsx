import { getLocale, getMessages } from "next-intl/server";

import { RootDocument } from "@/components/layout/RootDocument";
import { ProtectedAppLayout } from "@/components/layout/ProtectedAppLayout";
import { pickMessages } from "@/i18n/messages";
import { APP_NAMESPACES } from "@/i18n/namespaces";
import type { SupportedLocale } from "@/i18n/routing";
import { ROOT_METADATA } from "@/lib/root-metadata";

// Root layout of the signed-in app (R07-01). The locale comes from the
// NEXT_LOCALE cookie (src/i18n/request.ts), so these routes render per
// request. Navigating to or from `app/[locale]` is a full page load.
export const metadata = ROOT_METADATA;

export default async function AuthenticatedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = (await getLocale()) as SupportedLocale;
  const messages = pickMessages(await getMessages(), APP_NAMESPACES);

  return (
    <RootDocument locale={locale} messages={messages}>
      <ProtectedAppLayout>{children}</ProtectedAppLayout>
    </RootDocument>
  );
}
