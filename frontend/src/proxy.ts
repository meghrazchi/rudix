import createMiddleware from "next-intl/middleware";
import { type NextRequest, NextResponse } from "next/server";

import {
  isAuthenticatedAppPath,
  parseLocalePrefixedAppPath,
} from "./lib/app-route-paths";
import { LOCALE_COOKIE_NAME, resolveLocale, routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

const DEFAULT_SESSION_HINT_COOKIE_NAME = "rudix_session_hint";

// Server-side route gate (R07-09). Read at request time, so it can be switched
// without a rebuild. The gate only checks that the non-secret session-hint
// cookie exists: it never reads tokens, roles or claims. Role and permission
// checks stay in ProtectedAppLayout and the backend.
function isRouteGateEnforced(): boolean {
  return process.env.RUDIX_ROUTE_GATE?.trim().toLowerCase() === "enforce";
}

function sessionHintCookieName(): string {
  return (
    process.env.RUDIX_SESSION_HINT_COOKIE_NAME?.trim() ||
    DEFAULT_SESSION_HINT_COOKIE_NAME
  );
}

// Same rules as normalizeNextPath in lib/auth-session.ts, plus no
// protocol-relative targets.
function normalizeNextPath(path: string): string | null {
  const trimmed = path.trim();
  if (
    !trimmed.startsWith("/") ||
    trimmed.startsWith("//") ||
    trimmed.startsWith("/login")
  ) {
    return null;
  }
  return trimmed;
}

function redirectToLogin(request: NextRequest, locale: string): NextResponse {
  const { pathname, search } = request.nextUrl;
  const next = normalizeNextPath(`${pathname}${search}`);
  const target = new URL(`/${locale}/login`, request.url);
  const query = next ? `?next=${encodeURIComponent(next)}` : "";
  // 307 keeps the method; nothing of the app shell is rendered.
  return NextResponse.redirect(`${target.origin}${target.pathname}${query}`, {
    status: 307,
  });
}

export function proxy(request: NextRequest): NextResponse {
  const localizedAppPath = parseLocalePrefixedAppPath(request.nextUrl.pathname);

  // Authenticated app routes intentionally keep locale state in a cookie, not
  // in the URL. Normalize old/bookmarked locale-prefixed app links.
  if (localizedAppPath) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = localizedAppPath.pathname;
    const response = NextResponse.redirect(redirectUrl);
    response.cookies.set(LOCALE_COOKIE_NAME, localizedAppPath.locale, {
      path: "/",
      sameSite: "lax",
      httpOnly: false,
      maxAge: 60 * 60 * 24 * 365,
    });
    return response;
  }

  if (!isAuthenticatedAppPath(request.nextUrl.pathname)) {
    return intlMiddleware(request) as NextResponse;
  }

  // Cookie-based locale for authenticated app routes (no URL prefix)
  const cookieValue = request.cookies.get(LOCALE_COOKIE_NAME)?.value;
  const acceptLanguage = request.headers.get("accept-language") ?? undefined;
  const locale = resolveLocale(cookieValue, acceptLanguage);

  if (isRouteGateEnforced() && !request.cookies.has(sessionHintCookieName())) {
    return redirectToLogin(request, locale);
  }

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
  // Skip Next internals, API routes, static asset folders, and any path with
  // a file extension (robots.txt, sitemap.xml, llms.txt, icons) so crawlers
  // and browsers get those files directly instead of a locale redirect.
  matcher: [
    "/((?!_next/static|_next/image|brand/|images/|fonts/|api/|.*\\..*).*)",
  ],
};
