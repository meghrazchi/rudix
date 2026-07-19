import { NextIntlClientProvider } from "next-intl";
import { notFound } from "next/navigation";

import { isValidLocale } from "@/i18n/routing";
import { loadMessages } from "@/i18n/messages";

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

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      {children}
    </NextIntlClientProvider>
  );
}
