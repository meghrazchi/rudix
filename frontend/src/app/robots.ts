import type { MetadataRoute } from "next";

import { resolvePublicSiteBaseUrl } from "@/lib/public-site/links";
import { AUTHENTICATED_APP_ROUTE_SEGMENTS } from "@/lib/app-route-paths";

const PRIVATE_PATH_PREFIXES = AUTHENTICATED_APP_ROUTE_SEGMENTS.map(
  (segment) => `/${segment}`,
);

// Thin, duplicate-content utility pages under the locale-prefixed public
// route group (login/signup/onboarding flows, error pages) — not marketing
// content, shouldn't be indexed.
const PUBLIC_UTILITY_PATH_PATTERNS = [
  "/*/login",
  "/*/signup",
  "/*/demo",
  "/*/onboarding",
  "/*/organization-onboarding",
  "/*/accept-invite",
  "/*/sso/callback",
  "/*/403",
  "/*/forbidden",
];

// Explicit allow rules for known AI crawlers/assistants (2026), in addition
// to the wildcard `*` rule below which already covers them implicitly.
// Explicit entries remove any ambiguity/default-deny risk some crawlers
// apply when no user-agent-specific rule matches, and make the intent
// (maximum AI visibility, not an opt-out of training) legible to auditors.
const AI_CRAWLER_USER_AGENTS = [
  "GPTBot",
  "OAI-SearchBot",
  "ChatGPT-User",
  "ClaudeBot",
  "anthropic-ai",
  "Claude-SearchBot",
  "Claude-User",
  "PerplexityBot",
  "Perplexity-User",
  "Google-Extended",
  "CCBot",
  "Applebot-Extended",
  "Amazonbot",
  "Meta-ExternalAgent",
];

export default function robots(): MetadataRoute.Robots {
  const baseUrl = resolvePublicSiteBaseUrl();
  const disallow = [...PRIVATE_PATH_PREFIXES, ...PUBLIC_UTILITY_PATH_PATTERNS];

  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow,
      },
      {
        userAgent: AI_CRAWLER_USER_AGENTS,
        allow: "/",
        disallow,
      },
    ],
    sitemap: new URL("/sitemap.xml", baseUrl).toString(),
  };
}
