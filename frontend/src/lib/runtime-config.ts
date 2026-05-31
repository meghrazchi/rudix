const DEFAULT_API_URL = "http://localhost:8000/api/v1";
const DEFAULT_APP_URL = "http://localhost:3000";

export type FrontendAuthProvider = "app" | "clerk" | "other";

export type FrontendFeatureFlags = {
  developerMode: boolean;
  feedback: boolean;
  exports: boolean;
  unavailableBackendEndpoints: boolean;
  collectionsEnabled: boolean;
};

export type FrontendRuntimeConfig = {
  apiUrl: string;
  appUrl: string;
  authProvider: FrontendAuthProvider;
  authProviderRaw: string;
  features: FrontendFeatureFlags;
};

export type FrontendRuntimeConfigValidation = {
  config: FrontendRuntimeConfig;
  errors: string[];
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

export function parseFrontendRuntimeConfig(
  env: NodeJS.ProcessEnv = process.env,
): FrontendRuntimeConfigValidation {
  const errors: string[] = [];
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

  if (apiUrl.error) {
    errors.push(apiUrl.error);
  }
  if (appUrl.error) {
    errors.push(appUrl.error);
  }

  const authProvider = toAuthProvider(env.NEXT_PUBLIC_AUTH_PROVIDER);

  return {
    config: {
      apiUrl: apiUrl.value,
      appUrl: appUrl.value,
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
      },
    },
    errors,
  };
}

export function getFrontendRuntimeConfig(
  env: NodeJS.ProcessEnv = process.env,
): FrontendRuntimeConfig {
  return parseFrontendRuntimeConfig(env).config;
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
