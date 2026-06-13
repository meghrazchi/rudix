import { NextIntlClientProvider } from "next-intl";
import { notFound } from "next/navigation";

import { isValidLocale } from "@/i18n/routing";

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

  const messages = (await import(`@/i18n/messages/${locale}.json`))
    .default as Record<string, unknown>;

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      {children}
    </NextIntlClientProvider>
  );
}
