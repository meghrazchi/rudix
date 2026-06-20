import type { Metadata } from "next";
import { getLocale, getMessages } from "next-intl/server";
import { NextIntlClientProvider } from "next-intl";

import { AppQueryProvider } from "@/components/providers/AppQueryProvider";
import { ConsentProvider } from "@/components/consent/ConsentProvider";
import { CookieConsentBanner } from "@/components/consent/CookieConsentBanner";
import { getFrontendRuntimeConfigErrors } from "@/lib/runtime-config";
import { getHtmlLang } from "@/lib/i18n-format";
import type { SupportedLocale } from "@/i18n/routing";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Rudix",
    template: "%s | Rudix",
  },
  description: "Rudix enterprise RAG platform",
  icons: {
    icon: "/brand/rudix-mark.svg",
    shortcut: "/brand/rudix-mark.svg",
    apple: "/brand/rudix-mark.svg",
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const runtimeConfigErrors = getFrontendRuntimeConfigErrors();
  const locale = (await getLocale()) as SupportedLocale;
  const messages = await getMessages();

  return (
    <html lang={getHtmlLang(locale)} className="h-full antialiased">
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined"
        />
      </head>
      <body className="flex min-h-full flex-col">
        <NextIntlClientProvider locale={locale} messages={messages}>
          {runtimeConfigErrors.length > 0 ? (
            <ConfigErrorBanner errors={runtimeConfigErrors} />
          ) : (
            <AppQueryProvider>
              <ConsentProvider>
                {children}
                <CookieConsentBanner />
              </ConsentProvider>
            </AppQueryProvider>
          )}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}

function ConfigErrorBanner({ errors }: { errors: string[] }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6 py-10">
      <section className="w-full max-w-2xl rounded-2xl border border-[#dad8ef] bg-white p-8 shadow-sm">
        <p className="mb-2 text-xs font-bold tracking-[0.16em] text-[#5d58a8] uppercase">
          Rudix startup check
        </p>
        <h1 className="text-2xl font-bold text-[#29263f]">
          Frontend configuration is incomplete
        </h1>
        <p className="mt-3 text-sm text-[#5f5b76]">
          Required public environment values are missing or invalid. Update your
          frontend environment file and restart the app.
        </p>
        <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-[#5f5b76]">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      </section>
    </main>
  );
}
