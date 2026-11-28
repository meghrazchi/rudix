import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";

import { AppQueryProvider } from "@/components/providers/AppQueryProvider";
import { ConsentProvider } from "@/components/consent/ConsentProvider";
import { CookieConsentBanner } from "@/components/consent/CookieConsentBanner";
import { WebVitalsReporter } from "@/components/observability/WebVitalsReporter";
import { getFrontendRuntimeConfigErrors } from "@/lib/runtime-config";
import { getHtmlLang } from "@/lib/i18n-format";
import type { SupportedLocale } from "@/i18n/routing";
import { getLocaleDirection } from "@/i18n/direction";

import "@fontsource-variable/inter";
import "@fontsource-variable/vazirmatn";
import "@/app/globals.css";

type RootDocumentProps = {
  locale: SupportedLocale;
  messages: Record<string, unknown>;
  children: ReactNode;
};

/**
 * The `<html>` document shared by both root layouts (R07-01): `app/[locale]`
 * (prerendered public pages) and `app/(app)` (the signed-in app). It holds
 * the only `NextIntlClientProvider`; callers pass the picked messages.
 */
export function RootDocument({
  locale,
  messages,
  children,
}: RootDocumentProps) {
  const runtimeConfigErrors = getFrontendRuntimeConfigErrors();

  return (
    <html
      lang={getHtmlLang(locale)}
      dir={getLocaleDirection(locale)}
      className="h-full antialiased"
    >
      {/* Rendered by the root layouts, where <head> is the App Router way. */}
      {/* eslint-disable-next-line @next/next/no-head-element */}
      <head>{/* anchor: A2 head */}</head>
      <body className="flex min-h-full flex-col">
        <NextIntlClientProvider locale={locale} messages={messages}>
          {runtimeConfigErrors.length > 0 ? (
            <ConfigErrorBanner errors={runtimeConfigErrors} />
          ) : (
            <AppQueryProvider>
              <ConsentProvider>
                {children}
                <CookieConsentBanner />
                {/* anchor: A2 body */}
                <WebVitalsReporter />
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
