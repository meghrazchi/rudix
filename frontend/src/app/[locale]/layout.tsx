import { notFound } from "next/navigation";
import { setRequestLocale } from "next-intl/server";

import { RootDocument } from "@/components/layout/RootDocument";
import { LocaleDocumentAttributes } from "@/components/i18n/LocaleDocumentAttributes";
import { isValidLocale, SUPPORTED_LOCALES } from "@/i18n/routing";
import { loadMessages, pickMessages } from "@/i18n/messages";
import { PUBLIC_NAMESPACES } from "@/i18n/namespaces";
import { ROOT_METADATA } from "@/lib/root-metadata";
import { buildPublicOrganizationJsonLd } from "@/lib/public-site/structured-data";

// Root layout of the public site (R07-01). The locale is a root parameter, so
// every public page is prerendered once per locale at build time.
export const metadata = ROOT_METADATA;

export const dynamicParams = false;

export function generateStaticParams() {
  return SUPPORTED_LOCALES.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  if (!isValidLocale(locale)) {
    notFound();
  }

  setRequestLocale(locale);

  const messages = pickMessages(await loadMessages(locale), PUBLIC_NAMESPACES);
  const organizationJsonLd = buildPublicOrganizationJsonLd();

  return (
    <RootDocument locale={locale} messages={messages}>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(organizationJsonLd).replace(/</g, "\\u003c"),
        }}
      />
      <LocaleDocumentAttributes locale={locale}>
        {children}
      </LocaleDocumentAttributes>
    </RootDocument>
  );
}
