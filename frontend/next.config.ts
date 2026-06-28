import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// Only validate at `next build`. NEXT_PHASE is set by Next.js before loading
// this config; it equals 'phase-production-build' during builds and
// 'phase-production-server' during `next start`, so this guard prevents the
// module-resolution crash that occurs when next.config.compiled.js tries to
// require('./src/lib/runtime-config') at server startup (Node can't load .ts).
if (process.env.NEXT_PHASE === "phase-production-build") {
  const errors: string[] = [];
  for (const key of ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_APP_URL"] as const) {
    const val = (process.env[key] ?? "").trim();
    if (!val) {
      errors.push(`${key} is required and must be an absolute http(s) URL.`);
    } else {
      try {
        const { protocol } = new URL(val);
        if (protocol !== "http:" && protocol !== "https:") {
          errors.push(`${key} must use http:// or https://.`);
        }
      } catch {
        errors.push(`${key} must be a valid absolute URL.`);
      }
    }
  }
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

const nextConfig: NextConfig = {};

export default withNextIntl(nextConfig);
