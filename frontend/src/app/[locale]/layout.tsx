import { NextIntlClientProvider } from "next-intl";
import { notFound } from "next/navigation";

import { LocaleDocumentAttributes } from "@/components/i18n/LocaleDocumentAttributes";
import { isValidLocale } from "@/i18n/routing";
import { loadMessages } from "@/i18n/messages";
import { buildPublicOrganizationJsonLd } from "@/lib/public-site/structured-data";

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

  const messages = await loadMessages(locale);
  const organizationJsonLd = buildPublicOrganizationJsonLd();

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(organizationJsonLd).replace(/</g, "\\u003c"),
        }}
      />
      <LocaleDocumentAttributes locale={locale}>
        {children}
      </LocaleDocumentAttributes>
    </NextIntlClientProvider>
  );
}
