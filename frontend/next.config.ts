import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

import { validateBuildEnvironment } from "./config/build-env-validation.mjs";
import { buildSecurityHeaders } from "./config/security-headers.mjs";

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

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: buildSecurityHeaders(process.env, {
          isDev: process.env.NODE_ENV !== "production",
        }),
      },
    ];
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
