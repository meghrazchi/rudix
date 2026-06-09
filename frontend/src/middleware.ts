import { type NextRequest, NextResponse } from "next/server";

import {
  LOCALE_COOKIE_NAME,
  resolveLocale,
} from "./i18n/routing";

export function middleware(request: NextRequest): NextResponse {
  const cookieValue = request.cookies.get(LOCALE_COOKIE_NAME)?.value;
  const acceptLanguage = request.headers.get("accept-language") ?? undefined;
  const locale = resolveLocale(cookieValue, acceptLanguage);

  const response = NextResponse.next();

  if (cookieValue !== locale) {
    response.cookies.set(LOCALE_COOKIE_NAME, locale, {
      path: "/",
      sameSite: "lax",
      httpOnly: false,
      maxAge: 60 * 60 * 24 * 365,
    });
  }

  return response;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|brand/|api/).*)",
  ],
};
