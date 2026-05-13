import { z } from "zod";

import { isApiClientError } from "@/lib/api/errors";
import { apiRequest } from "@/lib/api/request";
import type { AppRole } from "@/lib/auth-session";

const DOMAIN_PATTERN = /^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$/i;
const INVITE_ROLES = ["admin", "member", "viewer"] as const;

type InviteRole = (typeof INVITE_ROLES)[number];

const inviteInputSchema = z.object({
  email: z.string().trim(),
  role: z.enum(INVITE_ROLES),
});

export const organizationOnboardingSchema = z
  .object({
    workspaceName: z
      .string()
      .trim()
      .min(2, "Workspace name must be at least 2 characters")
      .max(80, "Workspace name must be 80 characters or fewer"),
    domainAllowlistText: z.string().trim().optional(),
    defaultAccessRole: z.enum(["member", "viewer"]),
    allowSelfServeJoin: z.boolean(),
    invites: z.array(inviteInputSchema).max(20, "You can add up to 20 invites"),
  })
  .superRefine((value, context) => {
    for (const domain of parseDomainAllowlist(value.domainAllowlistText ?? "")) {
      if (!DOMAIN_PATTERN.test(domain)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["domainAllowlistText"],
          message: `Invalid domain in allowlist: ${domain}`,
        });
      }
    }

    const seenEmails = new Set<string>();
    value.invites.forEach((invite, index) => {
      if (!invite.email) {
        return;
      }

      const parsedEmail = z.string().email().safeParse(invite.email);
      if (!parsedEmail.success) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["invites", index, "email"],
          message: "Enter a valid invite email",
        });
        return;
      }

      const normalized = parsedEmail.data.toLowerCase();
      if (seenEmails.has(normalized)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["invites", index, "email"],
          message: "Duplicate invite email",
        });
        return;
      }

      seenEmails.add(normalized);
    });
  });

export type OrganizationOnboardingFormValues = z.infer<typeof organizationOnboardingSchema>;

export type OrganizationOnboardingErrorKind =
  | "workspace_conflict"
  | "invalid_domain"
  | "network_failure"
  | "invite_failure"
  | "not_configured"
  | "unknown";

export class OrganizationOnboardingError extends Error {
  readonly kind: OrganizationOnboardingErrorKind;
  readonly safeMessage: string;

  constructor(kind: OrganizationOnboardingErrorKind, safeMessage: string) {
    super(safeMessage);
    this.name = "OrganizationOnboardingError";
    this.kind = kind;
    this.safeMessage = safeMessage;
  }
}

export type OnboardingInvite = {
  email: string;
  role: InviteRole;
};

export type OnboardingDraft = {
  workspace_name: string;
  domain_allowlist: string[];
  default_access_role: "member" | "viewer";
  allow_self_serve_join: boolean;
  invites: OnboardingInvite[];
};

export type OnboardingCompletionResult = {
  organizationId: string;
  organizationName: string;
  role: AppRole;
};

type OrganizationOnboardingConfig = {
  resumeUrl: string | null;
  saveUrl: string | null;
  completeUrl: string | null;
  localFallbackEnabled: boolean;
};

const ONBOARDING_DRAFT_STORAGE_KEY = "rudix.organization-onboarding.v1";

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function sanitizeInviteRole(value: string | null | undefined): InviteRole {
  const normalized = trimToNull(value)?.toLowerCase();
  if (normalized === "admin" || normalized === "member" || normalized === "viewer") {
    return normalized;
  }

  return "member";
}

function sanitizeAppRole(value: string | null | undefined): AppRole {
  const normalized = trimToNull(value)?.toLowerCase();
  if (normalized === "owner" || normalized === "admin" || normalized === "member" || normalized === "viewer") {
    return normalized;
  }

  return "admin";
}

export function parseDomainAllowlist(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\n,]/)
        .map((token) => token.trim().toLowerCase())
        .filter((token) => token.length > 0),
    ),
  );
}

function serializeDomainAllowlist(domains: string[]): string {
  return domains.join("\n");
}

function normalizeInvites(invites: OrganizationOnboardingFormValues["invites"]): OnboardingInvite[] {
  const sanitized = invites
    .map((invite) => ({
      email: invite.email.trim().toLowerCase(),
      role: sanitizeInviteRole(invite.role),
    }))
    .filter((invite) => invite.email.length > 0);

  const deduped = new Map<string, OnboardingInvite>();
  for (const invite of sanitized) {
    if (!deduped.has(invite.email)) {
      deduped.set(invite.email, invite);
    }
  }

  return Array.from(deduped.values());
}

function toDraftPayload(values: OrganizationOnboardingFormValues): OnboardingDraft {
  return {
    workspace_name: values.workspaceName.trim(),
    domain_allowlist: parseDomainAllowlist(values.domainAllowlistText ?? ""),
    default_access_role: values.defaultAccessRole,
    allow_self_serve_join: values.allowSelfServeJoin,
    invites: normalizeInvites(values.invites),
  };
}

function fromDraftPayload(draft: Partial<OnboardingDraft>): OrganizationOnboardingFormValues {
  return {
    workspaceName: trimToNull(draft.workspace_name) ?? "",
    domainAllowlistText: serializeDomainAllowlist(draft.domain_allowlist ?? []),
    defaultAccessRole: draft.default_access_role === "viewer" ? "viewer" : "member",
    allowSelfServeJoin: draft.allow_self_serve_join ?? true,
    invites:
      draft.invites?.map((invite) => ({
        email: invite.email,
        role: sanitizeInviteRole(invite.role),
      })) ?? [],
  };
}

function getOnboardingConfig(): OrganizationOnboardingConfig {
  return {
    resumeUrl: trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_ONBOARDING_RESUME_URL),
    saveUrl: trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_ONBOARDING_SAVE_URL),
    completeUrl: trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_ONBOARDING_COMPLETE_URL),
    localFallbackEnabled:
      trimToNull(process.env.NEXT_PUBLIC_ORGANIZATION_ONBOARDING_LOCAL_FALLBACK) === "true" ||
      process.env.NODE_ENV !== "production",
  };
}

function saveDraftToStorage(draft: OnboardingDraft): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(ONBOARDING_DRAFT_STORAGE_KEY, JSON.stringify(draft));
}

function readDraftFromStorage(): OnboardingDraft | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.localStorage.getItem(ONBOARDING_DRAFT_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as OnboardingDraft;
  } catch {
    return null;
  }
}

export function clearOnboardingDraft(): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(ONBOARDING_DRAFT_STORAGE_KEY);
}

function toOnboardingError(error: unknown): OrganizationOnboardingError {
  if (error instanceof OrganizationOnboardingError) {
    return error;
  }

  if (isApiClientError(error)) {
    if (error.status === 409 || error.code === "workspace_exists") {
      return new OrganizationOnboardingError(
        "workspace_conflict",
        "Workspace name is already in use. Choose another name.",
      );
    }

    if (error.status === 422 || error.code === "invalid_domain") {
      return new OrganizationOnboardingError(
        "invalid_domain",
        "One or more allowed domains are invalid.",
      );
    }

    if (error.status === 400 || error.code === "invite_invalid") {
      return new OrganizationOnboardingError(
        "invite_failure",
        "Some invite entries are invalid. Review invite emails and roles.",
      );
    }

    if (error.status === 0 || error.status === 503) {
      return new OrganizationOnboardingError(
        "network_failure",
        "Unable to save organization setup right now. Try again shortly.",
      );
    }
  }

  return new OrganizationOnboardingError("unknown", "Organization setup failed. Please try again.");
}

function deriveOrganizationId(workspaceName: string): string {
  const slug = workspaceName
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 40);

  return slug.length > 0 ? `org-${slug}` : "org-rudix";
}

export function createDefaultOnboardingValues(): OrganizationOnboardingFormValues {
  return {
    workspaceName: "",
    domainAllowlistText: "",
    defaultAccessRole: "member",
    allowSelfServeJoin: true,
    invites: [{ email: "", role: "member" }],
  };
}

export async function loadOrganizationOnboardingDraft(): Promise<OrganizationOnboardingFormValues | null> {
  const config = getOnboardingConfig();

  if (config.resumeUrl) {
    try {
      const payload = await apiRequest<Partial<OnboardingDraft>>(config.resumeUrl, {
        method: "GET",
        retry: false,
      });

      const values = fromDraftPayload(payload);
      if (!values.workspaceName && values.invites.length === 0 && !values.domainAllowlistText) {
        return null;
      }

      return values;
    } catch (error) {
      throw toOnboardingError(error);
    }
  }

  const localDraft = readDraftFromStorage();
  if (!localDraft) {
    return null;
  }

  return fromDraftPayload(localDraft);
}

export async function persistOrganizationOnboardingDraft(
  values: OrganizationOnboardingFormValues,
): Promise<void> {
  const parsed = organizationOnboardingSchema.parse(values);
  const draft = toDraftPayload(parsed);
  const config = getOnboardingConfig();

  saveDraftToStorage(draft);

  if (!config.saveUrl) {
    return;
  }

  try {
    await apiRequest<Record<string, unknown>>(config.saveUrl, {
      method: "POST",
      json: draft,
      retry: false,
    });
  } catch (error) {
    throw toOnboardingError(error);
  }
}

export async function completeOrganizationOnboarding(
  values: OrganizationOnboardingFormValues,
): Promise<OnboardingCompletionResult> {
  const parsed = organizationOnboardingSchema.parse(values);
  const draft = toDraftPayload(parsed);
  const config = getOnboardingConfig();

  if (config.completeUrl) {
    try {
      const response = await apiRequest<{
        organization_id?: string | null;
        organization_name?: string | null;
        role?: string | null;
      }>(config.completeUrl, {
        method: "POST",
        json: draft,
        retry: false,
      });

      clearOnboardingDraft();

      return {
        organizationId: trimToNull(response.organization_id) ?? deriveOrganizationId(draft.workspace_name),
        organizationName: trimToNull(response.organization_name) ?? draft.workspace_name,
        role: sanitizeAppRole(response.role),
      };
    } catch (error) {
      throw toOnboardingError(error);
    }
  }

  if (!config.localFallbackEnabled) {
    throw new OrganizationOnboardingError(
      "not_configured",
      "Organization onboarding is not configured for this environment.",
    );
  }

  clearOnboardingDraft();

  return {
    organizationId: deriveOrganizationId(draft.workspace_name),
    organizationName: draft.workspace_name,
    role: "admin",
  };
}
