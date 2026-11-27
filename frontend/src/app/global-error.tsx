"use client";

import "@/app/globals.css";

import { useReportRouteError } from "@/components/errors/useReportRouteError";
import { getLocaleDirection } from "@/i18n/direction";
import {
  GLOBAL_ERROR_MESSAGES,
  resolveGlobalErrorLocale,
} from "@/i18n/global-error-messages";
import { getHtmlLang } from "@/lib/i18n-format";

type GlobalErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

// Replaces the root layout when it (or the root provider tree) throws, so it
// renders its own <html> and <body> with no providers or message catalogues.
export default function GlobalError({ error, reset }: GlobalErrorProps) {
  useReportRouteError(error);

  const locale =
    typeof document === "undefined"
      ? resolveGlobalErrorLocale(null, null)
      : resolveGlobalErrorLocale(
          document.documentElement.lang,
          document.cookie,
        );
  const messages = GLOBAL_ERROR_MESSAGES[locale];

  return (
    <html
      lang={getHtmlLang(locale)}
      dir={getLocaleDirection(locale)}
      className="h-full antialiased"
    >
      <body className="flex min-h-full flex-col">
        <main className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6">
          <section className="w-full max-w-xl rounded-2xl border border-[#dad8ef] bg-white p-8 shadow-sm">
            <h1 className="text-2xl font-bold text-[#29263f]">
              {messages.title}
            </h1>
            <p className="mt-3 text-sm text-[#5f5b76]">
              {messages.description}
            </p>
            {error.digest ? (
              <p className="mt-2 text-xs text-[#7a7692]">
                {messages.reference}:{" "}
                <span className="font-mono font-semibold">{error.digest}</span>
              </p>
            ) : null}
            <div className="mt-6 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={reset}
                className="rounded-md bg-[#3346d3] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b3cc0]"
              >
                {messages.retry}
              </button>
              {/* A plain anchor: the router may be what failed. */}
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
              <a
                href="/"
                className="rounded-md border border-[#cbc8e6] px-4 py-2 text-sm font-semibold text-[#342f5c] hover:bg-[#f7f6ff]"
              >
                {messages.home}
              </a>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
