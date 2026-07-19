import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { DEFAULT_LOCALE, isValidLocale, LOCALE_COOKIE_NAME } from "./routing";
import type { SupportedLocale } from "./routing";
import { loadMessages } from "./messages";

export default getRequestConfig(async ({ requestLocale }) => {
  const urlLocale = await requestLocale;

  let locale: SupportedLocale;
  if (isValidLocale(urlLocale)) {
    locale = urlLocale;
  } else {
    const cookieStore = await cookies();
    const cookieValue = cookieStore.get(LOCALE_COOKIE_NAME)?.value;
    locale = isValidLocale(cookieValue) ? cookieValue : DEFAULT_LOCALE;
  }

  return {
    locale,
    messages: await loadMessages(locale),
  };
});
