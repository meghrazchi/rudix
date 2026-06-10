import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import {
  DEFAULT_LOCALE,
  isValidLocale,
  LOCALE_COOKIE_NAME,
} from "./routing";

export default getRequestConfig(async ({ requestLocale }) => {
  const urlLocale = await requestLocale;

  let locale: typeof DEFAULT_LOCALE;
  if (isValidLocale(urlLocale)) {
    locale = urlLocale;
  } else {
    const cookieStore = await cookies();
    const cookieValue = cookieStore.get(LOCALE_COOKIE_NAME)?.value;
    locale = isValidLocale(cookieValue) ? cookieValue : DEFAULT_LOCALE;
  }

  return {
    locale,
    messages: (
      await import(`./messages/${locale}.json`)
    ).default as Record<string, unknown>,
  };
});
