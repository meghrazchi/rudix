import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

import { validateBuildEnvironment } from "./config/build-env-validation.mjs";
import { resolveRuntimeConfigSource } from "./config/public-runtime-keys.mjs";
import {
  buildSecurityHeaders,
  isContentSecurityPolicyHeader,
} from "./config/security-headers.mjs";

// Only validate at `next build`. NEXT_PHASE is set by Next.js before loading
// this config; it equals 'phase-production-build' during builds and
// 'phase-production-server' during `next start`, so this guard prevents the
// module-resolution crash that occurs when next.config.compiled.js tries to
// require('./src/lib/runtime-config') at server startup (Node can't load .ts).
// Next 16 does not always set NEXT_PHASE while loading this file for
// `next build`, so also detect the `build` subcommand directly.
const isProductionBuild =
  process.env.NEXT_PHASE === "phase-production-build" ||
  process.argv.slice(2).includes("build");

if (isProductionBuild) {
  const errors = validateBuildEnvironment(process.env);
  if (errors.length > 0) {
    throw new Error(
      [
        "Invalid frontend runtime configuration.",
        ...errors.map((e) => `- ${e}`),
        "Update frontend/.env.local (or deployment env) and rebuild.",
      ].join("\n"),
    );
  }
}

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

// When NEXT_PUBLIC_PROXY_TARGET is set, proxy /api/v1/* through the local
// Next.js server so the browser sees same-origin requests (no CORS).
// Set in .env.local when developing against a remote API (e.g. staging).
// Staging/production deployments leave this unset and hit the API directly.
const proxyTarget = (process.env.NEXT_PUBLIC_PROXY_TARGET ?? "").replace(
  /\/$/,
  "",
);

// R08-11: in request mode (NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE=request) the CSP
// depends on runtime values, so src/proxy.ts sets it per response from the
// runtime env and the build-time headers below leave it out.
const runtimeConfigSource = resolveRuntimeConfigSource(
  process.env.NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE,
);

// R08-12: optional CDN origin for /_next/static. Unset keeps same-origin
// assets. assetPrefix is fixed at build, so one image for several
// environments needs one CDN host.
const assetPrefix =
  (process.env.NEXT_PUBLIC_ASSET_PREFIX ?? "").trim().replace(/\/$/, "") ||
  undefined;

// R08-12: optional Cache-Control for public/ folders that are not
// content-hashed (never immutable; validated at build). Unset keeps the
// Next.js default (public, max-age=0). /_next/static is already immutable.
const publicAssetCacheControl = (
  process.env.PUBLIC_ASSET_CACHE_CONTROL ?? ""
).trim();
const PUBLIC_ASSET_PATHS = ["/brand/:path*", "/fonts/:path*", "/images/:path*"];

export function buildHeaderRules(): {
  source: string;
  headers: { key: string; value: string }[];
}[] {
  const securityHeaders = buildSecurityHeaders(process.env, {
    isDev: process.env.NODE_ENV !== "production",
  }).filter(
    (header) =>
      runtimeConfigSource === "build" ||
      !isContentSecurityPolicyHeader(header.key),
  );
  return [
    { source: "/:path*", headers: securityHeaders },
    ...(publicAssetCacheControl
      ? PUBLIC_ASSET_PATHS.map((source) => ({
          source,
          headers: [{ key: "Cache-Control", value: publicAssetCacheControl }],
        }))
      : []),
  ];
}

const nextConfig: NextConfig = {
  // Self-contained server (`node .next/standalone/server.js`) for the Docker
  // runtime image, which no longer installs node_modules. In standalone mode
  // headers() and rewrites() are evaluated once at `next build` and baked into
  // the output, so security headers come from the build environment.
  output: "standalone",
  // A second dev server (the Playwright WebSocket-chat project) needs its own
  // build directory; everything else uses the default.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  ...(assetPrefix && { assetPrefix }),
  images: { formats: ["image/avif", "image/webp"] },
  // Two root layouts (app/[locale], app/(app)): unmatched URLs render
  // app/global-not-found.tsx (R07-01).
  experimental: {
    globalNotFound: true,
  },
  async headers() {
    return buildHeaderRules();
  },
  ...(proxyTarget && {
    async rewrites() {
      return [
        {
          source: "/api/v1/:path*",
          destination: `${proxyTarget}/:path*`,
        },
      ];
    },
  }),
};

export default withNextIntl(nextConfig);
