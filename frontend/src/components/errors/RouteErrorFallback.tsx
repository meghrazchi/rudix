"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { useReportRouteError } from "@/components/errors/useReportRouteError";

export type RouteErrorVariant = "page" | "segment";

type RouteErrorFallbackProps = {
  error: Error & { digest?: string };
  reset: () => void;
  /**
   * "page": full screen, for public routes. "segment": an inline card that
   * keeps the app shell and navigation around it.
   */
  variant?: RouteErrorVariant;
};

const LINK_CLASS =
  "rounded-md border border-[#cbc8e6] px-4 py-2 text-sm font-semibold text-[#342f5c] hover:bg-[#f7f6ff]";

export default function RouteErrorFallback({
  error,
  reset,
  variant = "page",
}: RouteErrorFallbackProps) {
  const t = useTranslations("errors");
  const locale = useLocale();
  useReportRouteError(error);

  const card = (
    <section className="w-full max-w-xl rounded-2xl border border-[#dad8ef] bg-white p-8 shadow-sm">
      <h1 className="text-2xl font-bold text-[#29263f]">
        {t("routeBoundary.title")}
      </h1>
      <p className="mt-3 text-sm text-[#5f5b76]">
        {t("routeBoundary.description")}
      </p>
      {error.digest ? (
        <p className="mt-2 text-xs text-[#7a7692]">
          {t("routeBoundary.reference")}:{" "}
          <span className="font-mono font-semibold">{error.digest}</span>
        </p>
      ) : null}
      <div className="mt-6 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={reset}
          className="rounded-md bg-[#3346d3] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b3cc0]"
        >
          {t("routeBoundary.retry")}
        </button>
        {variant === "segment" ? (
          <Link href="/dashboard" className={LINK_CLASS}>
            {t("routeBoundary.backToDashboard")}
          </Link>
        ) : (
          // Public routes always carry a locale prefix; a plain link keeps
          // the next-intl navigation helpers out of every route bundle.
          <Link href={`/${locale}`} className={LINK_CLASS}>
            {t("routeBoundary.backHome")}
          </Link>
        )}
      </div>
    </section>
  );

  if (variant === "segment") {
    return (
      <div role="alert" className="flex justify-center px-4 py-10">
        {card}
      </div>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6">
      {card}
    </main>
  );
}

/** The inline variant, for `error.tsx` files inside the signed-in app. */
export function SegmentRouteError(
  props: Omit<RouteErrorFallbackProps, "variant">,
) {
  return <RouteErrorFallback {...props} variant="segment" />;
}
