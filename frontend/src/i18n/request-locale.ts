import { use } from "react";
import { setRequestLocale } from "next-intl/server";

import { isValidLocale } from "./routing";

type LocaleParams = Promise<{ locale: string }>;

/**
 * Static rendering rule (R07-01): every server page and layout under
 * `app/[locale]` sets the request locale before any next-intl server API
 * runs, so next-intl never falls back to `headers()`/`cookies()` and the page
 * stays prerenderable. Layouts and pages can render independently, so the
 * layout's call does not cover the page.
 *
 * Unit tests render page components without route params; then there is no
 * request to configure and this is a no-op.
 */
export function useRequestLocale(params: LocaleParams | undefined): void {
  if (!params) {
    return;
  }
  applyRequestLocale(use(params).locale);
}

/** `useRequestLocale` for async server pages. */
export async function setRequestLocaleFromParams(
  params: LocaleParams | undefined,
): Promise<void> {
  if (!params) {
    return;
  }
  applyRequestLocale((await params).locale);
}

function applyRequestLocale(locale: string): void {
  // The [locale] layout answers 404 for unknown locales (dynamicParams=false).
  if (isValidLocale(locale)) {
    setRequestLocale(locale);
  }
}
