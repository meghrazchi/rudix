// Plain ES module so next.config.ts can import it at `next start`.
// The CSP is report-only by default. Enforcement is the NEXT_PUBLIC_CSP_ENFORCE
// flag, to be flipped to "true" after a clean report-only period; see
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

// Known captcha providers. Applied only when NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER
// matches (case-insensitive); unknown providers add nothing.
const CAPTCHA_PROVIDERS = {
  turnstile: {
    script: ["https://challenges.cloudflare.com"],
    frame: ["https://challenges.cloudflare.com"],
    connect: ["https://challenges.cloudflare.com"],
    style: [],
  },
  hcaptcha: {
    script: ["https://hcaptcha.com", "https://*.hcaptcha.com"],
    frame: ["https://hcaptcha.com", "https://*.hcaptcha.com"],
    connect: ["https://hcaptcha.com", "https://*.hcaptcha.com"],
    style: ["https://hcaptcha.com", "https://*.hcaptcha.com"],
  },
  recaptcha: {
    script: ["https://www.google.com", "https://www.gstatic.com"],
    frame: ["https://www.google.com", "https://www.gstatic.com"],
    connect: ["https://www.google.com"],
    style: [],
  },
};

/**
 * Hosts for the configured captcha provider; empty when unknown or unset.
 * @param {string | undefined} provider
 */
function captchaHosts(provider) {
  const key = (provider ?? "").trim().toLowerCase();
  return Object.hasOwn(CAPTCHA_PROVIDERS, key)
    ? CAPTCHA_PROVIDERS[key]
    : { script: [], frame: [], connect: [], style: [] };
}

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
 * Build the Content-Security-Policy value (same value report-only or enforced).
 * @param {Record<string, string | undefined>} env
 * @param {{ isDev: boolean }} options
 * @returns {string}
 */
export function buildContentSecurityPolicy(env, { isDev }) {
  const apiOrigin = originOf(env.NEXT_PUBLIC_API_URL);
  const matomoOrigin = originOf(env.NEXT_PUBLIC_MATOMO_URL);
  const gaEnabled = Boolean((env.NEXT_PUBLIC_GA_ID ?? "").trim());
  const sentryHost = sentryOrigin(env.NEXT_PUBLIC_SENTRY_DSN);
  const captcha = captchaHosts(env.NEXT_PUBLIC_CONTACT_CAPTCHA_PROVIDER);
  // The contact form POSTs with fetch to this URL, so it is a connect-src
  // entry. NEXT_PUBLIC_CONTACT_SUBMIT_EXTERNAL_URL and
  // NEXT_PUBLIC_CONTACT_SCHEDULER_URL are navigations (window.location.assign),
  // not fetches, so they are not listed and form-action stays 'self'.
  const contactSubmitOrigin = originOf(env.NEXT_PUBLIC_CONTACT_SUBMIT_API_URL);
  const optional = (value) => (value ? [value] : []);

  const scriptSrc = [
    "'self'",
    "'unsafe-inline'",
    ...(isDev ? ["'unsafe-eval'"] : []),
    ...(gaEnabled ? GA_SCRIPT_HOSTS : []),
    ...optional(matomoOrigin),
    ...captcha.script,
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
    ...optional(contactSubmitOrigin),
    ...captcha.connect,
    ...(isDev ? ["ws:"] : []),
  ];
  // No iframes are used in the app; frames are only for captcha widgets.
  const frameSrc = captcha.frame.length
    ? ["'self'", ...captcha.frame]
    : ["'none'"];

  const directives = [
    "default-src 'self'",
    `script-src ${joinSources(scriptSrc)}`,
    `style-src ${joinSources(["'self'", "'unsafe-inline'", ...captcha.style])}`,
    "font-src 'self' data:",
    `img-src ${joinSources(imgSrc)}`,
    `connect-src ${joinSources(connectSrc)}`,
    `frame-src ${joinSources(frameSrc)}`,
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
  const enforce =
    (env.NEXT_PUBLIC_CSP_ENFORCE ?? "").trim().toLowerCase() === "true";
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
      key: enforce
        ? "Content-Security-Policy"
        : "Content-Security-Policy-Report-Only",
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
