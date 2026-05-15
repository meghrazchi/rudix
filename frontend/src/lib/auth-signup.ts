import { z } from "zod";

import { isApiClientError } from "@/lib/api/errors";
import { apiRequest } from "@/lib/api/request";
import type { AppRole, AuthenticatedSession } from "@/lib/auth-session";
import { getAuthClientConfig, getLoginProviderLabel } from "@/lib/auth-login";

const APP_ROLES: AppRole[] = ["owner", "admin", "member", "viewer"];

export const signupFormSchema = z
  .object({
    fullName: z
      .string()
      .trim()
      .min(1, "Full name is required")
      .min(2, "Full name must be at least 2 characters"),
    email: z
      .string()
      .trim()
      .min(1, "Email is required")
      .email("Enter a valid email address"),
    password: z
      .string()
      .min(1, "Password is required")
      .min(8, "Password must be at least 8 characters"),
    workspaceMode: z.enum(["create", "join"]),
    workspaceName: z.string().trim().optional(),
    inviteCode: z.string().trim().optional(),
    acceptTerms: z.boolean(),
  })
  .superRefine((value, context) => {
    if (
      value.workspaceMode === "create" &&
      !(value.workspaceName && value.workspaceName.length >= 2)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["workspaceName"],
        message: "Workspace name must be at least 2 characters",
      });
    }

    if (
      value.workspaceMode === "join" &&
      !(value.inviteCode && value.inviteCode.length >= 4)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["inviteCode"],
        message: "Invite code is required to join a workspace",
      });
    }

    if (!value.acceptTerms) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["acceptTerms"],
        message: "You must accept the terms to create an account",
      });
    }
  });

export type SignupFormValues = z.infer<typeof signupFormSchema>;

export type SignupErrorKind =
  | "duplicate_email"
  | "weak_password"
  | "invite_only"
  | "provider_error"
  | "network_failure"
  | "not_configured"
  | "unknown";

export class SignupFlowError extends Error {
  readonly kind: SignupErrorKind;
  readonly safeMessage: string;

  constructor(kind: SignupErrorKind, safeMessage: string) {
    super(safeMessage);
    this.name = "SignupFlowError";
    this.kind = kind;
    this.safeMessage = safeMessage;
  }
}

export type SignupNextStep = "onboarding" | "dashboard";

export type SignupResult = {
  session: AuthenticatedSession;
  nextStep: SignupNextStep;
};

type SignupClientConfig = {
  signupUrl: string | null;
  signupSsoUrl: string | null;
  inviteOnly: boolean;
  localFallbackEnabled: boolean;
  localFallbackPassword: string | null;
  defaultOrganizationId: string | null;
  defaultOrganizationName: string | null;
  defaultRole: AppRole;
  defaultAccessToken: string | null;
  defaultRefreshToken: string | null;
  defaultUserId: string | null;
};

type AuthSignupResponse = {
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
  onboarding_required?: boolean | null;
  next_step?: string | null;
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

function deriveUserIdFromEmail(email: string): string {
  const local = email.split("@")[0]?.trim().toLowerCase() ?? "user";
  const sanitized = local.replace(/[^a-z0-9._-]/g, "-").replace(/-+/g, "-");
  return sanitized.length > 0 ? sanitized : "user";
}

function toSignupConfig(): SignupClientConfig {
  const baseConfig = getAuthClientConfig();

  return {
    signupUrl: trimToNull(process.env.NEXT_PUBLIC_AUTH_SIGNUP_URL),
    signupSsoUrl:
      trimToNull(process.env.NEXT_PUBLIC_AUTH_SIGNUP_SSO_URL) ??
      baseConfig.ssoUrl,
    inviteOnly: trimToNull(process.env.NEXT_PUBLIC_AUTH_INVITE_ONLY) === "true",
    localFallbackEnabled:
      trimToNull(process.env.NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_FALLBACK) ===
        "true" ||
      (trimToNull(process.env.NEXT_PUBLIC_AUTH_SIGNUP_URL) === null &&
        baseConfig.localFallbackEnabled),
    localFallbackPassword:
      trimToNull(process.env.NEXT_PUBLIC_AUTH_SIGNUP_LOCAL_PASSWORD) ??
      baseConfig.localFallbackPassword,
    defaultOrganizationId: baseConfig.defaultOrganizationId,
    defaultOrganizationName: baseConfig.defaultOrganizationName,
    defaultRole: baseConfig.defaultRole,
    defaultAccessToken: baseConfig.defaultAccessToken,
    defaultRefreshToken: baseConfig.defaultRefreshToken,
    defaultUserId: baseConfig.defaultUserId,
  };
}

function decideNextStep(payload: {
  nextStepRaw?: string | null;
  onboardingRequired?: boolean | null;
  hasOrganizationId: boolean;
  workspaceMode: SignupFormValues["workspaceMode"];
}): SignupNextStep {
  const normalizedNextStep = trimToNull(payload.nextStepRaw)?.toLowerCase();
  if (normalizedNextStep === "onboarding") {
    return "onboarding";
  }
  if (normalizedNextStep === "dashboard") {
    return "dashboard";
  }

  if (payload.onboardingRequired === true) {
    return "onboarding";
  }

  if (payload.workspaceMode === "create") {
    return "onboarding";
  }

  if (!payload.hasOrganizationId) {
    return "onboarding";
  }

  return "dashboard";
}

function responseToSignupResult(
  response: AuthSignupResponse,
  values: SignupFormValues,
  config: SignupClientConfig,
): SignupResult {
  const organizationId =
    trimToNull(response.organization_id) ??
    trimToNull(response.organizationId) ??
    config.defaultOrganizationId;

  const session: AuthenticatedSession = {
    userId:
      trimToNull(response.user_id) ??
      trimToNull(response.userId) ??
      trimToNull(response.sub) ??
      config.defaultUserId ??
      deriveUserIdFromEmail(values.email),
    email: trimToNull(response.email) ?? values.email,
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

  return {
    session,
    nextStep: decideNextStep({
      nextStepRaw: response.next_step,
      onboardingRequired: response.onboarding_required,
      hasOrganizationId: Boolean(session.organizationId),
      workspaceMode: values.workspaceMode,
    }),
  };
}

function buildLocalSignupResult(
  values: SignupFormValues,
  config: SignupClientConfig,
): SignupResult {
  const organizationId =
    values.workspaceMode === "join" ? config.defaultOrganizationId : null;

  return {
    session: {
      userId: config.defaultUserId ?? deriveUserIdFromEmail(values.email),
      email: values.email,
      role: config.defaultRole,
      organizationId,
      organizationName: organizationId ? config.defaultOrganizationName : null,
      accessToken: config.defaultAccessToken,
      refreshToken: config.defaultRefreshToken,
    },
    nextStep: decideNextStep({
      onboardingRequired: null,
      nextStepRaw: null,
      hasOrganizationId: Boolean(organizationId),
      workspaceMode: values.workspaceMode,
    }),
  };
}

function toSignupFlowError(error: unknown): SignupFlowError {
  if (error instanceof SignupFlowError) {
    return error;
  }

  if (isApiClientError(error)) {
    if (error.status === 409 || error.code === "email_already_exists") {
      return new SignupFlowError(
        "duplicate_email",
        "An account with this email already exists.",
      );
    }

    if (
      error.status === 400 ||
      error.status === 422 ||
      error.code === "weak_password"
    ) {
      return new SignupFlowError(
        "weak_password",
        "Choose a stronger password with at least 8 characters.",
      );
    }

    if (
      error.status === 403 ||
      error.status === 423 ||
      error.code === "invite_only" ||
      error.code === "signup_blocked"
    ) {
      return new SignupFlowError(
        "invite_only",
        "Signup is currently restricted. You need an invitation to continue.",
      );
    }

    if (error.status === 502 || error.code === "provider_error") {
      return new SignupFlowError(
        "provider_error",
        "Identity provider is unavailable right now. Please try again later.",
      );
    }

    if (error.status === 0 || error.status === 503) {
      return new SignupFlowError(
        "network_failure",
        "Unable to create your account right now. Check your connection and try again.",
      );
    }
  }

  return new SignupFlowError("unknown", "Signup failed. Please try again.");
}

export async function startSignupSession(
  values: SignupFormValues,
): Promise<SignupResult> {
  const parsed = signupFormSchema.parse(values);
  const config = toSignupConfig();

  if (config.signupUrl) {
    try {
      const response = await apiRequest<AuthSignupResponse>(config.signupUrl, {
        method: "POST",
        json: {
          full_name: parsed.fullName,
          email: parsed.email,
          password: parsed.password,
          workspace_mode: parsed.workspaceMode,
          workspace_name:
            parsed.workspaceMode === "create" ? parsed.workspaceName : null,
          invite_code:
            parsed.workspaceMode === "join" ? parsed.inviteCode : null,
          accept_terms: parsed.acceptTerms,
        },
        attachAuth: false,
        attachOrganizationId: false,
        retry: false,
      });

      return responseToSignupResult(response, parsed, config);
    } catch (error) {
      throw toSignupFlowError(error);
    }
  }

  if (!config.localFallbackEnabled) {
    throw new SignupFlowError(
      "not_configured",
      "Signup is not configured for this environment.",
    );
  }

  if (config.inviteOnly) {
    throw new SignupFlowError(
      "invite_only",
      "Signup is currently restricted. You need an invitation to continue.",
    );
  }

  if (
    parsed.email.toLowerCase().startsWith("existing@") ||
    parsed.email.toLowerCase().startsWith("duplicate@")
  ) {
    throw new SignupFlowError(
      "duplicate_email",
      "An account with this email already exists.",
    );
  }

  if (parsed.password.toLowerCase().includes("weak")) {
    throw new SignupFlowError(
      "weak_password",
      "Choose a stronger password with at least 8 characters.",
    );
  }

  if (parsed.email.toLowerCase().startsWith("provider@")) {
    throw new SignupFlowError(
      "provider_error",
      "Identity provider is unavailable right now. Please try again later.",
    );
  }

  if (
    config.localFallbackPassword &&
    parsed.password !== config.localFallbackPassword
  ) {
    throw new SignupFlowError(
      "weak_password",
      "Choose a stronger password with at least 8 characters.",
    );
  }

  return buildLocalSignupResult(parsed, config);
}

export function getSignupProviderLabel(): string {
  return getLoginProviderLabel();
}

export function getSignupSsoStartHref(nextPath: string): string | null {
  const signupSsoUrl = toSignupConfig().signupSsoUrl;
  if (!signupSsoUrl) {
    return null;
  }

  try {
    const baseOrigin =
      typeof window !== "undefined"
        ? window.location.origin
        : "http://localhost";
    const parsed = new URL(signupSsoUrl, baseOrigin);
    if (!parsed.searchParams.has("next")) {
      parsed.searchParams.set("next", nextPath);
    }

    if (
      signupSsoUrl.startsWith("http://") ||
      signupSsoUrl.startsWith("https://")
    ) {
      return parsed.toString();
    }

    const query = parsed.searchParams.toString();
    return `${parsed.pathname}${query ? `?${query}` : ""}`;
  } catch {
    return signupSsoUrl;
  }
}
