const DEFAULT_API_URL = "http://localhost:8000/api/v1";
const DEFAULT_APP_URL = "http://localhost:3000";
const PRODUCTION_LIKE_ENVIRONMENTS = new Set(["staging", "production"]);
const RUDIX_STAGING_APP_URL = "https://staging.getrudix.com";
const RUDIX_STAGING_API_URL = "https://api-staging.getrudix.com/api/v1";
const RUDIX_PRODUCTION_APP_URL = "https://getrudix.com";
const RUDIX_PRODUCTION_API_URL = "https://api.getrudix.com/api/v1";

export type FrontendAuthProvider = "app" | "clerk" | "other";
export type FrontendDeploymentEnvironment =
  | "development"
  | "test"
  | "staging"
  | "production"
  | "other";

export type FrontendFeatureFlags = {
  developerMode: boolean;
  feedback: boolean;
  exports: boolean;
  unavailableBackendEndpoints: boolean;
  collectionsEnabled: boolean;
  analyticsEnabled: boolean;
};

export type FrontendAnalyticsConfig = {
  matomoUrl: string | null;
  matomoSiteId: string | null;
};

export type FrontendRuntimeConfig = {
  apiUrl: string;
  appUrl: string;
  deploymentEnvironment: FrontendDeploymentEnvironment;
  deploymentEnvironmentRaw: string;
  authProvider: FrontendAuthProvider;
  authProviderRaw: string;
  analytics: FrontendAnalyticsConfig;
  features: FrontendFeatureFlags;
};

export type FrontendRuntimeConfigValidation = {
  config: FrontendRuntimeConfig;
  errors: string[];
};

export type FrontendRuntimeConfigParseOptions = {
  publicOrigin?: string | null;
};

type PublicUrlFallback = {
  apiUrl: string;
  appUrl: string;
  deploymentEnvironment: Extract<
    FrontendDeploymentEnvironment,
    "staging" | "production"
  >;
};

function trimToNull(value: string | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function parseBooleanFlag(
  value: string | undefined,
  fallback: boolean,
): boolean {
  const normalized = trimToNull(value)?.toLowerCase();
  if (!normalized) {
    return fallback;
  }
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  return fallback;
}

function toAuthProvider(value: string | undefined): {
  normalized: FrontendAuthProvider;
  raw: string;
} {
  const normalized = trimToNull(value)?.toLowerCase();
  if (!normalized) {
    return { normalized: "other", raw: "" };
  }
  if (normalized === "app" || normalized === "clerk") {
    return { normalized, raw: normalized };
  }
  return {
    normalized: "other",
    raw: normalized,
  };
}

function normalizeBaseUrl(url: string): string {
  return url.replace(/\/$/, "");
}

function getBrowserOrigin(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return trimToNull(window.location?.origin);
}

function isLoopbackPublicHost(host: string): boolean {
  const normalized = host.toLowerCase().replace(/^\[|\]$/g, "");
  return (
    normalized === "localhost" ||
    normalized.endsWith(".localhost") ||
    normalized === "::1" ||
    normalized === "0.0.0.0" ||
    normalized.startsWith("127.")
  );
}

function isLoopbackPublicUrl(value: string): boolean {
  try {
    return isLoopbackPublicHost(new URL(value).hostname);
  } catch {
    return false;
  }
}

function inferRudixPublicUrlFallback(
  publicOrigin: string | null | undefined,
): PublicUrlFallback | null {
  const origin = trimToNull(publicOrigin ?? undefined);
  if (!origin) {
    return null;
  }

  try {
    const parsed = new URL(origin);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      return null;
    }

    const hostname = parsed.hostname.toLowerCase();
    if (isLoopbackPublicHost(hostname)) {
      return null;
    }

    if (hostname === "staging.getrudix.com") {
      return {
        apiUrl: RUDIX_STAGING_API_URL,
        appUrl: RUDIX_STAGING_APP_URL,
        deploymentEnvironment: "staging",
      };
    }

    if (hostname === "getrudix.com" || hostname === "www.getrudix.com") {
      return {
        apiUrl: RUDIX_PRODUCTION_API_URL,
        appUrl: RUDIX_PRODUCTION_APP_URL,
        deploymentEnvironment: "production",
      };
    }
  } catch {
    return null;
  }

  return null;
}

function toDeploymentEnvironment(env: NodeJS.ProcessEnv): {
  normalized: FrontendDeploymentEnvironment;
  raw: string;
} {
  const raw =
    trimToNull(env.NEXT_PUBLIC_DEPLOYMENT_ENV) ??
    trimToNull(env.NEXT_PUBLIC_ENVIRONMENT) ??
    trimToNull(env.NEXT_PUBLIC_SENTRY_ENVIRONMENT) ??
    "";
  const normalized = raw.toLowerCase();

  if (
    normalized === "development" ||
    normalized === "test" ||
    normalized === "staging" ||
    normalized === "production"
  ) {
    return { normalized, raw: normalized };
  }

  return { normalized: "other", raw: normalized };
}

function parseRequiredHttpUrl(
  env: NodeJS.ProcessEnv,
  key: "NEXT_PUBLIC_API_URL" | "NEXT_PUBLIC_APP_URL",
  fallback: string,
): { value: string; error: string | null } {
  const raw = trimToNull(env[key]);
  if (!raw) {
    return {
      value: fallback,
      error: `${key} is required and must be an absolute http(s) URL.`,
    };
  }

  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return {
        value: fallback,
        error: `${key} must use http:// or https://.`,
      };
    }
  } catch {
    return {
      value: fallback,
      error: `${key} must be a valid absolute URL.`,
    };
  }

  return { value: normalizeBaseUrl(raw), error: null };
}

function validateProductionLikeUrl(
  key: "NEXT_PUBLIC_API_URL" | "NEXT_PUBLIC_APP_URL",
  value: string,
  deploymentEnvironment: FrontendDeploymentEnvironment,
): string[] {
  if (!PRODUCTION_LIKE_ENVIRONMENTS.has(deploymentEnvironment)) {
    return [];
  }

  const errors: string[] = [];
  const parsed = new URL(value);
  const hostname = parsed.hostname.toLowerCase();

  if (parsed.protocol !== "https:") {
    errors.push(
      `${key} must use https:// when NEXT_PUBLIC_DEPLOYMENT_ENV is staging or production.`,
    );
  }

  if (isLoopbackPublicHost(hostname)) {
    errors.push(
      `${key} must not point to localhost when NEXT_PUBLIC_DEPLOYMENT_ENV is staging or production.`,
    );
  }

  return errors;
}

export function parseFrontendRuntimeConfig(
  env: NodeJS.ProcessEnv = process.env,
  options: FrontendRuntimeConfigParseOptions = {},
): FrontendRuntimeConfigValidation {
  const errors: string[] = [];
  const deploymentEnvironment = toDeploymentEnvironment(env);
  const publicUrlFallback = inferRudixPublicUrlFallback(options.publicOrigin);
  const apiUrl = parseRequiredHttpUrl(
    env,
    "NEXT_PUBLIC_API_URL",
    DEFAULT_API_URL,
  );
  const appUrl = parseRequiredHttpUrl(
    env,
    "NEXT_PUBLIC_APP_URL",
    DEFAULT_APP_URL,
  );
  const resolvedApiUrl =
    publicUrlFallback && isLoopbackPublicUrl(apiUrl.value)
      ? publicUrlFallback.apiUrl
      : apiUrl.value;
  const resolvedAppUrl =
    publicUrlFallback && isLoopbackPublicUrl(appUrl.value)
      ? publicUrlFallback.appUrl
      : appUrl.value;
  const usingPublicUrlFallback =
    publicUrlFallback !== null &&
    (resolvedApiUrl !== apiUrl.value || resolvedAppUrl !== appUrl.value);
  const resolvedDeploymentEnvironment = usingPublicUrlFallback
    ? publicUrlFallback.deploymentEnvironment
    : deploymentEnvironment.normalized;
  const resolvedDeploymentEnvironmentRaw = usingPublicUrlFallback
    ? publicUrlFallback.deploymentEnvironment
    : deploymentEnvironment.raw;
  const apiUrlError =
    apiUrl.error && resolvedApiUrl === apiUrl.value ? apiUrl.error : null;
  const appUrlError =
    appUrl.error && resolvedAppUrl === appUrl.value ? appUrl.error : null;

  if (apiUrlError) {
    errors.push(apiUrlError);
  }
  if (appUrlError) {
    errors.push(appUrlError);
  }
  if (!apiUrlError) {
    errors.push(
      ...validateProductionLikeUrl(
        "NEXT_PUBLIC_API_URL",
        resolvedApiUrl,
        resolvedDeploymentEnvironment,
      ),
    );
  }
  if (!appUrlError) {
    errors.push(
      ...validateProductionLikeUrl(
        "NEXT_PUBLIC_APP_URL",
        resolvedAppUrl,
        resolvedDeploymentEnvironment,
      ),
    );
  }

  const authProvider = toAuthProvider(env.NEXT_PUBLIC_AUTH_PROVIDER);

  return {
    config: {
      apiUrl: resolvedApiUrl,
      appUrl: resolvedAppUrl,
      deploymentEnvironment: resolvedDeploymentEnvironment,
      deploymentEnvironmentRaw: resolvedDeploymentEnvironmentRaw,
      authProvider: authProvider.normalized,
      authProviderRaw: authProvider.raw,
      features: {
        developerMode: parseBooleanFlag(
          env.NEXT_PUBLIC_FEATURE_DEVELOPER_MODE,
          false,
        ),
        feedback: parseBooleanFlag(
          env.NEXT_PUBLIC_CHAT_FEEDBACK_ENABLED,
          false,
        ),
        exports: parseBooleanFlag(
          env.NEXT_PUBLIC_FEATURE_EXPORTS_ENABLED,
          true,
        ),
        unavailableBackendEndpoints: parseBooleanFlag(
          env.NEXT_PUBLIC_FEATURE_UNAVAILABLE_BACKEND_ENDPOINTS,
          true,
        ),
        collectionsEnabled: parseBooleanFlag(
          env.NEXT_PUBLIC_FEATURE_COLLECTIONS_ENABLED,
          true,
        ),
        analyticsEnabled: parseBooleanFlag(
          env.NEXT_PUBLIC_ANALYTICS_ENABLED,
          true,
        ),
      },
      analytics: {
        matomoUrl: trimToNull(env.NEXT_PUBLIC_MATOMO_URL),
        matomoSiteId: trimToNull(env.NEXT_PUBLIC_MATOMO_SITE_ID),
      },
    },
    errors,
  };
}

export function getFrontendRuntimeConfig(
  env: NodeJS.ProcessEnv = process.env,
): FrontendRuntimeConfig {
  return parseFrontendRuntimeConfig(env, {
    publicOrigin: getBrowserOrigin(),
  }).config;
}

export function getFrontendRuntimeConfigErrors(
  env: NodeJS.ProcessEnv = process.env,
): string[] {
  return parseFrontendRuntimeConfig(env).errors;
}

export function assertFrontendRuntimeConfigForBuild(
  env: NodeJS.ProcessEnv = process.env,
): void {
  const errors = getFrontendRuntimeConfigErrors(env);
  if (errors.length === 0) {
    return;
  }

  throw new Error(
    [
      "Invalid frontend runtime configuration.",
      ...errors.map((error) => `- ${error}`),
      "Update frontend/.env.local (or deployment env) and rebuild.",
    ].join("\n"),
  );
}
