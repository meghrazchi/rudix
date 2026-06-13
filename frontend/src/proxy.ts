import createMiddleware from "next-intl/middleware";
import { type NextRequest, NextResponse } from "next/server";

import { LOCALE_COOKIE_NAME, resolveLocale, routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

const APP_ROUTE_RE =
  /^\/(dashboard|chat|admin|documents|collections|connectors|evaluations|rag-pipeline|settings|api)\b/;

export function proxy(request: NextRequest): NextResponse {
  if (!APP_ROUTE_RE.test(request.nextUrl.pathname)) {
    return intlMiddleware(request) as NextResponse;
  }

  // Cookie-based locale for authenticated app routes (no URL prefix)
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
    "/((?!_next/static|_next/image|favicon.ico|brand/|images/|api/).*)",
  ],
};
