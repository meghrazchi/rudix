// Plain ES module (no TypeScript) so next.config.ts can import it at
// `next start`, where src/*.ts cannot be loaded. Keep in sync with
// `toDeploymentEnvironment` in src/lib/runtime-config.ts.

const PRODUCTION_LIKE_ENVIRONMENTS = new Set(["staging", "production"]);

/**
 * Lower-cased first non-empty trimmed deployment-environment value.
 * @param {Record<string, string | undefined>} env
 * @returns {string | null}
 */
export function resolveDeploymentEnvironment(env) {
  for (const key of [
    "NEXT_PUBLIC_DEPLOYMENT_ENV",
    "NEXT_PUBLIC_ENVIRONMENT",
    "NEXT_PUBLIC_SENTRY_ENVIRONMENT",
  ]) {
    const value = (env[key] ?? "").trim();
    if (value) return value.toLowerCase();
  }
  return null;
}

/**
 * True for staging and production deployments.
 * @param {Record<string, string | undefined>} env
 * @returns {boolean}
 */
export function isProductionLikeEnvironment(env) {
  const resolved = resolveDeploymentEnvironment(env);
  return resolved !== null && PRODUCTION_LIKE_ENVIRONMENTS.has(resolved);
}
