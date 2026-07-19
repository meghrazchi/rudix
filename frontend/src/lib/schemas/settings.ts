import { z } from "zod";

// ── User profile (GET/PATCH /api/v1/me) ───────────────────────────────────────

export const userProfileSchema = z.object({
  id: z.string(),
  email: z.string().email(),
  name: z.string(),
  avatarUrl: z.string().nullable().optional(),
  createdAt: z.string().nullable().optional(),
});

export type UserProfile = z.infer<typeof userProfileSchema>;

export const updateProfileFormSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(200),
});

export type UpdateProfileFormValues = z.infer<typeof updateProfileFormSchema>;

// ── User preferences (GET/PATCH /api/v1/me/preferences) ──────────────────────

export const userPreferencesSchema = z.object({
  language: z.string().optional(),
  timezone: z.string().optional(),
  dateFormat: z.string().optional(),
  theme: z.enum(["light", "dark", "system"]).optional(),
  landingPage: z.string().optional(),
  keyboardShortcutHints: z.boolean().optional(),
  emailNotifications: z.boolean().optional(),
  digestFrequency: z.enum(["daily", "weekly", "never"]).optional(),
});

export type UserPreferences = z.infer<typeof userPreferencesSchema>;

export const updatePreferencesFormSchema = userPreferencesSchema;
export type UpdatePreferencesFormValues = z.infer<
  typeof updatePreferencesFormSchema
>;

// ── Organization profile form ─────────────────────────────────────────────────

export const orgProfileFormSchema = z.object({
  name: z.string().trim().min(1, "Organization name is required").max(200),
  slug: z
    .string()
    .trim()
    .min(2)
    .max(64)
    .regex(
      /^[a-z0-9][a-z0-9-]*[a-z0-9]$/,
      "Slug must be lowercase alphanumeric with hyphens",
    )
    .optional(),
  primary_domain: z.string().trim().nullable().optional(),
  support_email: z
    .string()
    .trim()
    .email("Must be a valid email")
    .nullable()
    .optional()
    .or(z.literal("").transform(() => null)),
  description: z.string().max(1000).nullable().optional(),
});

export type OrgProfileFormValues = z.infer<typeof orgProfileFormSchema>;

// ── Organization settings form ────────────────────────────────────────────────

export const orgSettingsFormSchema = z.object({
  default_member_role: z.enum(["member", "viewer"]),
  invite_only: z.boolean(),
  allowed_email_domains: z.array(z.string().trim().min(1)).default([]),
  default_document_visibility: z.enum(["public", "private"]),
  default_collection: z.string().nullable().optional(),
  retention_days: z.number().int().positive().nullable().optional(),
  source_download: z.enum(["all", "admins", "none"]),
  evaluation_access: z.boolean(),
  agentic_access: z.boolean(),
  mcp_access: z.boolean(),
  analytics_enabled: z.boolean().optional(),
});

export type OrgSettingsFormValues = z.infer<typeof orgSettingsFormSchema>;

// ── Ingestion defaults form ───────────────────────────────────────────────────

export const ingestionDefaultsFormSchema = z.object({
  allowed_file_types: z.array(z.string().trim().min(1)).default([]),
  max_upload_size_mb: z.number().positive().nullable().optional(),
  max_page_count: z.number().int().positive().nullable().optional(),
  duplicate_handling: z.enum(["allow", "skip", "replace"]),
  auto_index: z.boolean(),
  reindex_policy: z.enum(["on_update", "manual"]),
  retry_policy: z.enum(["never", "once", "three_times"]),
  default_metadata_tags: z.array(z.string().trim().min(1)).default([]),
});

export type IngestionDefaultsFormValues = z.infer<
  typeof ingestionDefaultsFormSchema
>;

// ── Login / security policy form ─────────────────────────────────────────────

export const loginPolicyFormSchema = z.object({
  domain_allowlist: z.array(z.string().trim().min(1)).default([]),
  session_timeout_hours: z.number().positive().nullable().optional(),
  sso_required: z.boolean(),
  invite_only: z.boolean(),
  mfa_required: z.boolean(),
});

export type LoginPolicyFormValues = z.infer<typeof loginPolicyFormSchema>;

// ── Billing contact form ──────────────────────────────────────────────────────

export const billingContactFormSchema = z.object({
  email: z
    .string()
    .trim()
    .email("Must be a valid email")
    .nullable()
    .optional()
    .or(z.literal("").transform(() => null)),
  name: z.string().trim().max(200).nullable().optional(),
  address_line1: z.string().trim().max(200).nullable().optional(),
  address_line2: z.string().trim().max(200).nullable().optional(),
  city: z.string().trim().max(100).nullable().optional(),
  state: z.string().trim().max(100).nullable().optional(),
  postal_code: z.string().trim().max(20).nullable().optional(),
  country: z.string().trim().max(2).nullable().optional(),
  tax_id: z.string().trim().max(50).nullable().optional(),
});

export type BillingContactFormValues = z.infer<typeof billingContactFormSchema>;

// ── Team invite form ──────────────────────────────────────────────────────────

export const inviteTeamMemberFormSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Email is required")
    .email("Must be a valid email"),
  role: z.enum(["admin", "member", "viewer"]),
});

export type InviteTeamMemberFormValues = z.infer<
  typeof inviteTeamMemberFormSchema
>;

export const updateTeamMemberRoleFormSchema = z.object({
  role: z.enum(["admin", "member", "viewer"]),
});

export type UpdateTeamMemberRoleFormValues = z.infer<
  typeof updateTeamMemberRoleFormSchema
>;

// ── Safe error mapping ────────────────────────────────────────────────────────

export type SettingsErrorState =
  | { kind: "none" }
  | { kind: "forbidden" }
  | { kind: "rate_limited" }
  | { kind: "unavailable" }
  | { kind: "error"; message: string };

export function toSettingsErrorState(error: unknown): SettingsErrorState {
  if (error == null) return { kind: "none" };

  if (typeof error !== "object") {
    return {
      kind: "error",
      message: "Something went wrong. Please try again.",
    };
  }

  const asObj = error as Record<string, unknown>;
  const name = typeof asObj.name === "string" ? asObj.name : "";

  if (name === "ApiClientError") {
    const status = typeof asObj.status === "number" ? asObj.status : 0;
    const userMessage =
      typeof asObj.userMessage === "string"
        ? asObj.userMessage
        : "Something went wrong. Please try again.";
    if (status === 403) return { kind: "forbidden" };
    if (status === 429) return { kind: "rate_limited" };
    return { kind: "error", message: userMessage };
  }

  if (
    name === "OrganizationEndpointUnavailableError" ||
    name === "BillingEndpointUnavailableError" ||
    name === "TeamEndpointUnavailableError" ||
    name === "SecurityEndpointUnavailableError" ||
    name === "ProfileEndpointUnavailableError"
  ) {
    return { kind: "unavailable" };
  }

  return { kind: "error", message: "Something went wrong. Please try again." };
}

// ── Existing UI preferences ───────────────────────────────────────────────────

export const PROFILE_UI_STORAGE_KEY = "rudix.settings.profile-ui.v1";

export const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "de", label: "Deutsch" },
  { value: "es", label: "Español" },
  { value: "fr", label: "Français" },
  { value: "ar", label: "العربية" },
  { value: "fa", label: "فارسی" },
] as const satisfies { value: string; label: string }[];

export const TIMEZONE_OPTIONS = [
  { value: "", label: "Browser default" },
  { value: "America/New_York", label: "(UTC-5) Eastern Time" },
  { value: "America/Chicago", label: "(UTC-6) Central Time" },
  { value: "America/Denver", label: "(UTC-7) Mountain Time" },
  { value: "America/Los_Angeles", label: "(UTC-8) Pacific Time" },
  { value: "America/Anchorage", label: "(UTC-9) Alaska Time" },
  { value: "Pacific/Honolulu", label: "(UTC-10) Hawaii Time" },
  { value: "Europe/London", label: "(UTC+0) London" },
  { value: "Europe/Paris", label: "(UTC+1) Paris / Berlin" },
  { value: "Europe/Helsinki", label: "(UTC+2) Helsinki / Kyiv" },
  { value: "Europe/Moscow", label: "(UTC+3) Moscow" },
  { value: "Asia/Dubai", label: "(UTC+4) Dubai" },
  { value: "Asia/Kolkata", label: "(UTC+5:30) Mumbai / Delhi" },
  { value: "Asia/Dhaka", label: "(UTC+6) Dhaka" },
  { value: "Asia/Bangkok", label: "(UTC+7) Bangkok" },
  { value: "Asia/Singapore", label: "(UTC+8) Singapore" },
  { value: "Asia/Tokyo", label: "(UTC+9) Tokyo" },
  { value: "Australia/Sydney", label: "(UTC+11) Sydney" },
  { value: "Pacific/Auckland", label: "(UTC+13) Auckland" },
] as const satisfies { value: string; label: string }[];

export const DATE_FORMAT_OPTIONS = [
  { value: "MMM D, YYYY", label: "Jan 1, 2025" },
  { value: "MM/DD/YYYY", label: "01/01/2025" },
  { value: "DD/MM/YYYY", label: "01/01/2025 (EU)" },
  { value: "YYYY-MM-DD", label: "2025-01-01 (ISO)" },
] as const satisfies { value: string; label: string }[];

export const LANDING_PAGE_OPTIONS = [
  { value: "/dashboard", label: "Dashboard" },
  { value: "/documents", label: "Documents" },
  { value: "/chat", label: "Chat" },
  { value: "/evaluations", label: "Evaluations" },
] as const satisfies { value: string; label: string }[];

export const THEME_OPTIONS = ["light", "dark", "system"] as const;
export type ThemeOption = (typeof THEME_OPTIONS)[number];

export const profileUiPreferencesSchema = z.object({
  language: z.string().min(1),
  timezone: z.string(),
  dateFormat: z.string().min(1),
  theme: z.enum(THEME_OPTIONS),
  landingPage: z.string().min(1),
  keyboardShortcutHints: z.boolean(),
});

export type ProfileUiPreferences = z.infer<typeof profileUiPreferencesSchema>;

export function createDefaultProfileUiPreferences(): ProfileUiPreferences {
  return {
    language: "en",
    timezone: "",
    dateFormat: "MMM D, YYYY",
    theme: "light",
    landingPage: "/dashboard",
    keyboardShortcutHints: true,
  };
}

export function loadProfileUiPreferences(): ProfileUiPreferences {
  if (typeof window === "undefined") {
    return createDefaultProfileUiPreferences();
  }
  const raw = window.localStorage.getItem(PROFILE_UI_STORAGE_KEY);
  if (!raw) {
    return createDefaultProfileUiPreferences();
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    const result = profileUiPreferencesSchema.safeParse(parsed);
    return result.success ? result.data : createDefaultProfileUiPreferences();
  } catch {
    return createDefaultProfileUiPreferences();
  }
}

export function saveProfileUiPreferences(prefs: ProfileUiPreferences): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(PROFILE_UI_STORAGE_KEY, JSON.stringify(prefs));
}
