// Plain ES module so next.config.ts can import it at `next start`.
// The CSP is report-only in 0.2.0 (enforcement is planned for R03-08); see
// docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md "Security headers".

import { isProductionLikeEnvironment } from "./deployment-env.mjs";

const GA_SCRIPT_HOSTS = ["https://www.googletagmanager.com"];
const GA_IMG_HOSTS = [
  "https://www.google-analytics.com",
  "https://*.google-analytics.com",
  "https://www.googletagmanager.com",
];
const GA_CONNECT_HOSTS = [
  "https://www.google-analytics.com",
  "https://*.google-analytics.com",
  "https://*.analytics.google.com",
  "https://www.googletagmanager.com",
];

/**
 * Origin of an http(s) URL, or null when missing or invalid.
 * @param {string | undefined} value
 * @returns {string | null}
 */
function originOf(value) {
  const raw = (value ?? "").trim();
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.origin;
  } catch {
    return null;
  }
}

/**
 * ws/wss origin matching an http(s) origin.
 * @param {string} origin
 * @returns {string}
 */
function websocketOrigin(origin) {
  return origin.replace(/^http/, "ws");
}

/**
 * Report URI only when it is a valid absolute http(s) URL without spaces
 * or semicolons (which would corrupt the policy).
 * @param {string | undefined} value
 * @returns {string | null}
 */
function reportUriOf(value) {
  const raw = (value ?? "").trim();
  if (!raw || /[\s;,]/.test(raw)) return null;
  return originOf(raw) ? raw : null;
}

/**
 * @param {string[]} sources
 * @returns {string}
 */
function joinSources(sources) {
  return [...new Set(sources)].join(" ");
}

/**
 * Build the report-only Content-Security-Policy value.
 * @param {Record<string, string | undefined>} env
 * @param {{ isDev: boolean }} options
 * @returns {string}
 */
export function buildContentSecurityPolicy(env, { isDev }) {
  const apiOrigin = originOf(env.NEXT_PUBLIC_API_URL);
  const matomoOrigin = originOf(env.NEXT_PUBLIC_MATOMO_URL);
  const gaEnabled = Boolean((env.NEXT_PUBLIC_GA_ID ?? "").trim());
  const sentryHost = sentryOrigin(env.NEXT_PUBLIC_SENTRY_DSN);
  const optional = (value) => (value ? [value] : []);

  const scriptSrc = [
    "'self'",
    "'unsafe-inline'",
    ...(isDev ? ["'unsafe-eval'"] : []),
    ...(gaEnabled ? GA_SCRIPT_HOSTS : []),
    ...optional(matomoOrigin),
  ];
  const imgSrc = [
    "'self'",
    "data:",
    "blob:",
    ...optional(apiOrigin),
    ...(gaEnabled ? GA_IMG_HOSTS : []),
    ...optional(matomoOrigin),
  ];
  const connectSrc = [
    "'self'",
    ...(apiOrigin ? [apiOrigin, websocketOrigin(apiOrigin)] : []),
    ...optional(sentryHost),
    ...(gaEnabled ? GA_CONNECT_HOSTS : []),
    ...optional(matomoOrigin),
    ...(isDev ? ["ws:"] : []),
  ];

  const directives = [
    "default-src 'self'",
    `script-src ${joinSources(scriptSrc)}`,
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    `img-src ${joinSources(imgSrc)}`,
    `connect-src ${joinSources(connectSrc)}`,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ];
  const reportUri = reportUriOf(env.NEXT_PUBLIC_CSP_REPORT_URI);
  if (reportUri) directives.push(`report-uri ${reportUri}`);
  return directives.join("; ");
}

/**
 * Origin events are sent to for the Sentry DSN (src/lib/observability/sentry.ts
 * posts to the DSN's own protocol and host), or null. Defaults to https.
 * @param {string | undefined} dsn
 * @returns {string | null}
 */
function sentryOrigin(dsn) {
  const raw = (dsn ?? "").trim();
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (!url.host) return null;
    const protocol = url.protocol === "http:" ? "http:" : "https:";
    return `${protocol}//${url.host}`;
  } catch {
    return null;
  }
}

/**
 * Security headers applied to every frontend response.
 * @param {Record<string, string | undefined>} env
 * @param {{ isDev: boolean }} options
 * @returns {{ key: string; value: string }[]}
 */
export function buildSecurityHeaders(env, { isDev }) {
  const headers = [
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    {
      key: "Permissions-Policy",
      value: "camera=(), microphone=(), geolocation=()",
    },
    // Enforced now: frame-ancestors inside a report-only CSP does not block.
    { key: "X-Frame-Options", value: "DENY" },
    {
      key: "Content-Security-Policy-Report-Only",
      value: buildContentSecurityPolicy(env, { isDev }),
    },
  ];
  if (isProductionLikeEnvironment(env)) {
    headers.push({
      key: "Strict-Transport-Security",
      value: "max-age=31536000",
    });
  }
  return headers;
}
