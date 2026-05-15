import { z } from "zod";

import { isApiClientError } from "@/lib/api/errors";
import { apiRequest } from "@/lib/api/request";
import type { AppRole, AuthenticatedSession } from "@/lib/auth-session";

const APP_ROLES: AppRole[] = ["owner", "admin", "member", "viewer"];

export const loginFormSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
  password: z
    .string()
    .min(1, "Password is required")
    .min(8, "Password must be at least 8 characters"),
});

export type LoginFormValues = z.infer<typeof loginFormSchema>;

export type LoginErrorKind =
  | "invalid_credentials"
  | "locked_account"
  | "network_failure"
  | "not_configured"
  | "unknown";

export class LoginFlowError extends Error {
  readonly kind: LoginErrorKind;
  readonly safeMessage: string;

  constructor(kind: LoginErrorKind, safeMessage: string) {
    super(safeMessage);
    this.name = "LoginFlowError";
    this.kind = kind;
    this.safeMessage = safeMessage;
  }
}

export type AuthClientConfig = {
  providerName: string | null;
  loginUrl: string | null;
  ssoUrl: string | null;
  forgotPasswordUrl: string | null;
  localFallbackEnabled: boolean;
  localFallbackPassword: string | null;
  defaultOrganizationId: string | null;
  defaultOrganizationName: string | null;
  defaultRole: AppRole;
  defaultUserId: string | null;
  defaultAccessToken: string | null;
  defaultRefreshToken: string | null;
};

type AuthLoginResponse = {
  access_token?: string | null;
  token?: string | null;
  refresh_token?: string | null;
  refreshToken?: string | null;
  user_id?: string | null;
  userId?: string | null;
  sub?: string | null;
  email?: string | null;
  role?: string | null;
  organization_id?: string | null;
  organizationId?: string | null;
  organization_name?: string | null;
  organizationName?: string | null;
};

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function toRole(value: string | null | undefined, fallback: AppRole): AppRole {
  const normalized = trimToNull(value)?.toLowerCase();
  if (!normalized) {
    return fallback;
  }

  if ((APP_ROLES as string[]).includes(normalized)) {
    return normalized as AppRole;
  }

  return fallback;
}

function normalizeProviderName(value: string | null): string {
  return (value ?? "app").trim().toLowerCase();
}

function deriveUserIdFromEmail(email: string): string {
  const local = email.split("@")[0]?.trim().toLowerCase() ?? "user";
  const sanitized = local.replace(/[^a-z0-9._-]/g, "-").replace(/-+/g, "-");
  if (sanitized.length > 0) {
    return sanitized;
  }
  return "user";
}

export function getAuthClientConfig(): AuthClientConfig {
  const defaultRole = toRole(
    process.env.NEXT_PUBLIC_AUTH_DEFAULT_ROLE,
    "member",
  );
  const providerName = trimToNull(process.env.NEXT_PUBLIC_AUTH_PROVIDER);
  const normalizedProvider = normalizeProviderName(providerName);
  const configuredLoginUrl = trimToNull(process.env.NEXT_PUBLIC_AUTH_LOGIN_URL);

  return {
    providerName,
    loginUrl:
      configuredLoginUrl ?? (normalizedProvider === "app" ? "/auth/login" : null),
    ssoUrl: trimToNull(process.env.NEXT_PUBLIC_AUTH_SSO_URL),
    forgotPasswordUrl: trimToNull(
      process.env.NEXT_PUBLIC_AUTH_FORGOT_PASSWORD_URL,
    ),
    localFallbackEnabled:
      trimToNull(process.env.NEXT_PUBLIC_AUTH_LOCAL_FALLBACK) === "true" ||
      (configuredLoginUrl === null &&
        process.env.NODE_ENV !== "production"),
    localFallbackPassword: trimToNull(
      process.env.NEXT_PUBLIC_AUTH_LOCAL_PASSWORD,
    ),
    defaultOrganizationId: trimToNull(
      process.env.NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_ID,
    ),
    defaultOrganizationName: trimToNull(
      process.env.NEXT_PUBLIC_AUTH_DEFAULT_ORGANIZATION_NAME,
    ),
    defaultRole,
    defaultUserId: trimToNull(process.env.NEXT_PUBLIC_AUTH_DEFAULT_USER_ID),
    defaultAccessToken: trimToNull(
      process.env.NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN,
    ),
    defaultRefreshToken: trimToNull(
      process.env.NEXT_PUBLIC_AUTH_DEFAULT_REFRESH_TOKEN,
    ),
  };
}

function responseToSession(
  response: AuthLoginResponse,
  email: string,
  config: AuthClientConfig,
): AuthenticatedSession {
  const organizationId =
    trimToNull(response.organization_id) ??
    trimToNull(response.organizationId) ??
    config.defaultOrganizationId;

  return {
    userId:
      trimToNull(response.user_id) ??
      trimToNull(response.userId) ??
      trimToNull(response.sub) ??
      config.defaultUserId ??
      deriveUserIdFromEmail(email),
    email: trimToNull(response.email) ?? email,
    role: toRole(response.role, config.defaultRole),
    organizationId,
    organizationName:
      trimToNull(response.organization_name) ??
      trimToNull(response.organizationName) ??
      (organizationId ? config.defaultOrganizationName : null),
    accessToken:
      trimToNull(response.access_token) ??
      trimToNull(response.token) ??
      config.defaultAccessToken,
    refreshToken:
      trimToNull(response.refresh_token) ??
      trimToNull(response.refreshToken) ??
      config.defaultRefreshToken,
  };
}

function buildLocalSession(
  email: string,
  config: AuthClientConfig,
): AuthenticatedSession {
  const userId = config.defaultUserId ?? deriveUserIdFromEmail(email);
  const organizationId = config.defaultOrganizationId;

  return {
    userId,
    email,
    role: config.defaultRole,
    organizationId,
    organizationName: organizationId ? config.defaultOrganizationName : null,
    accessToken: config.defaultAccessToken,
    refreshToken: config.defaultRefreshToken,
  };
}

function ensureSessionHasAccessToken(
  session: AuthenticatedSession,
  config: AuthClientConfig,
): void {
  const provider = normalizeProviderName(config.providerName);
  if (provider !== "app") {
    return;
  }

  if (trimToNull(session.accessToken ?? null)) {
    return;
  }

  throw new LoginFlowError(
    "not_configured",
    "Sign-in is configured but no API access token is available. Set NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN or configure NEXT_PUBLIC_AUTH_LOGIN_URL to return access_token.",
  );
}

function toLoginFlowError(error: unknown): LoginFlowError {
  if (error instanceof LoginFlowError) {
    return error;
  }

  if (isApiClientError(error)) {
    if (error.status === 401) {
      return new LoginFlowError(
        "invalid_credentials",
        "Invalid email or password.",
      );
    }

    if (
      error.status === 423 ||
      error.status === 429 ||
      error.code === "account_locked"
    ) {
      return new LoginFlowError(
        "locked_account",
        "Your account is temporarily locked. Please try again later or contact support.",
      );
    }

    if (error.status === 0 || error.status === 503) {
      return new LoginFlowError(
        "network_failure",
        "Unable to sign in right now. Check your connection and try again.",
      );
    }
  }

  return new LoginFlowError("unknown", "Sign-in failed. Please try again.");
}

export async function startLoginSession(
  values: LoginFormValues,
): Promise<AuthenticatedSession> {
  const parsed = loginFormSchema.parse(values);
  const config = getAuthClientConfig();

  if (config.loginUrl) {
    try {
      const response = await apiRequest<AuthLoginResponse>(config.loginUrl, {
        method: "POST",
        json: {
          email: parsed.email,
          password: parsed.password,
        },
        attachAuth: false,
        attachOrganizationId: false,
        retry: false,
      });

      const session = responseToSession(response, parsed.email, config);
      ensureSessionHasAccessToken(session, config);
      return session;
    } catch (error) {
      throw toLoginFlowError(error);
    }
  }

  if (!config.localFallbackEnabled) {
    throw new LoginFlowError(
      "not_configured",
      "Sign-in is not configured for this environment.",
    );
  }

  const expectedPassword = config.localFallbackPassword;
  if (expectedPassword && parsed.password !== expectedPassword) {
    throw new LoginFlowError(
      "invalid_credentials",
      "Invalid email or password.",
    );
  }

  if (parsed.email.toLowerCase().startsWith("locked@")) {
    throw new LoginFlowError(
      "locked_account",
      "Your account is temporarily locked. Please try again later or contact support.",
    );
  }

  const session = buildLocalSession(parsed.email, config);
  ensureSessionHasAccessToken(session, config);
  return session;
}

export function getSsoStartHref(nextPath: string): string | null {
  const ssoUrl = getAuthClientConfig().ssoUrl;
  if (!ssoUrl) {
    return null;
  }

  try {
    const baseOrigin =
      typeof window !== "undefined"
        ? window.location.origin
        : "http://localhost";
    const parsed = new URL(ssoUrl, baseOrigin);
    if (!parsed.searchParams.has("next")) {
      parsed.searchParams.set("next", nextPath);
    }

    if (ssoUrl.startsWith("http://") || ssoUrl.startsWith("https://")) {
      return parsed.toString();
    }

    const query = parsed.searchParams.toString();
    return `${parsed.pathname}${query ? `?${query}` : ""}`;
  } catch {
    return ssoUrl;
  }
}

export function getForgotPasswordHref(): string | null {
  return getAuthClientConfig().forgotPasswordUrl;
}

export function getLoginProviderLabel(): string {
  const provider = getAuthClientConfig().providerName;
  if (!provider) {
    return "SSO";
  }

  return provider
    .split(/[^a-zA-Z0-9]+/)
    .filter(Boolean)
    .map((token) => token[0]?.toUpperCase() + token.slice(1).toLowerCase())
    .join(" ");
}
