// Plain ES module (no TypeScript) so next.config.ts can import it during
// `next build`, where src/*.ts cannot be loaded.

import { isProductionLikeEnvironment } from "./deployment-env.mjs";

function isLoopbackPublicHost(host) {
  const normalized = host.toLowerCase().replace(/^\[|\]$/g, "");
  return (
    normalized === "localhost" ||
    normalized.endsWith(".localhost") ||
    normalized === "::1" ||
    normalized === "0.0.0.0" ||
    normalized.startsWith("127.")
  );
}

const DEV_ONLY_FLAGS = [
  "NEXT_PUBLIC_AUTH_LOCAL_FALLBACK",
  "NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK",
  // Makes /admin/error-probe throw on purpose (route boundary e2e, R07-08).
  "NEXT_PUBLIC_E2E_ERROR_PROBE",
];

const DEV_ONLY_SECRETS = [
  "NEXT_PUBLIC_AUTH_LOCAL_PASSWORD",
  "NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_PASSWORD",
  "NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN",
  "NEXT_PUBLIC_AUTH_DEFAULT_REFRESH_TOKEN",
];

/**
 * Validate build-time public configuration. Never echoes variable values.
 * @param {Record<string, string | undefined>} env
 * @returns {string[]} human-readable errors (empty when valid)
 */
export function validateBuildEnvironment(env) {
  const errors = [];
  const isProductionLike = isProductionLikeEnvironment(env);

  for (const key of ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_APP_URL"]) {
    const val = (env[key] ?? "").trim();
    if (!val) {
      errors.push(`${key} is required and must be an absolute http(s) URL.`);
    } else {
      try {
        const { protocol, hostname } = new URL(val);
        if (protocol !== "http:" && protocol !== "https:") {
          errors.push(`${key} must use http:// or https://.`);
        }
        if (isProductionLike && protocol !== "https:") {
          errors.push(
            `${key} must use https:// when NEXT_PUBLIC_DEPLOYMENT_ENV is staging or production.`,
          );
        }
        if (isProductionLike && isLoopbackPublicHost(hostname)) {
          errors.push(
            `${key} must not point to localhost when NEXT_PUBLIC_DEPLOYMENT_ENV is staging or production.`,
          );
        }
      } catch {
        errors.push(`${key} must be a valid absolute URL.`);
      }
    }
  }

  if (isProductionLike) {
    for (const key of DEV_ONLY_FLAGS) {
      if ((env[key] ?? "").trim().toLowerCase() === "true") {
        errors.push(
          `${key} is development-only and must not be enabled in staging or production builds.`,
        );
      }
    }
    for (const key of DEV_ONLY_SECRETS) {
      if ((env[key] ?? "").trim()) {
        errors.push(
          `${key} is development-only and must be empty in staging or production builds.`,
        );
      }
    }
  }
  return errors;
}
