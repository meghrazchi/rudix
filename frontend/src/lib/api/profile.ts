import { apiRequest } from "@/lib/api/request";
import {
  userProfileSchema,
  userPreferencesSchema,
  type UserProfile,
  type UserPreferences,
  type UpdateProfileFormValues,
  type UpdatePreferencesFormValues,
} from "@/lib/schemas/settings";

function trimToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

// ── Capability flags ──────────────────────────────────────────────────────────

export type ProfileCapabilities = {
  meEnabled: boolean;
  preferencesEnabled: boolean;
  signOutAllDevicesEnabled: boolean;
  deleteAccountEnabled: boolean;
  avatarEnabled: boolean;
  changePasswordEnabled: boolean;
};

export class ProfileEndpointUnavailableError extends Error {
  readonly endpointKey: keyof ProfileCapabilities;

  constructor(endpointKey: keyof ProfileCapabilities) {
    super("Profile endpoint is not configured");
    this.name = "ProfileEndpointUnavailableError";
    this.endpointKey = endpointKey;
  }
}

export function isProfileEndpointUnavailableError(
  error: unknown,
): error is ProfileEndpointUnavailableError {
  return error instanceof ProfileEndpointUnavailableError;
}

function getProfileEndpoints() {
  return {
    meUrl: trimToNull(process.env.NEXT_PUBLIC_PROFILE_ME_URL),
    preferencesUrl: trimToNull(process.env.NEXT_PUBLIC_PROFILE_PREFERENCES_URL),
    signOutAllUrl: trimToNull(process.env.NEXT_PUBLIC_PROFILE_SIGN_OUT_ALL_URL),
    deleteAccountUrl: trimToNull(
      process.env.NEXT_PUBLIC_PROFILE_DELETE_ACCOUNT_URL,
    ),
    avatarUrl: trimToNull(process.env.NEXT_PUBLIC_PROFILE_AVATAR_URL),
    changePasswordUrl: trimToNull(
      process.env.NEXT_PUBLIC_SECURITY_CHANGE_PASSWORD_URL,
    ),
  };
}

export function getProfileCapabilities(): ProfileCapabilities {
  const e = getProfileEndpoints();
  return {
    meEnabled: e.meUrl !== null,
    preferencesEnabled: e.preferencesUrl !== null,
    signOutAllDevicesEnabled: e.signOutAllUrl !== null,
    deleteAccountEnabled: e.deleteAccountUrl !== null,
    avatarEnabled: e.avatarUrl !== null,
    changePasswordEnabled: e.changePasswordUrl !== null,
  };
}

// ── Normalization ─────────────────────────────────────────────────────────────

type RawRecord = Record<string, unknown>;

function toRaw(payload: unknown): RawRecord {
  return typeof payload === "object" &&
    payload !== null &&
    !Array.isArray(payload)
    ? (payload as RawRecord)
    : {};
}

function normalizeUserProfile(payload: unknown): UserProfile {
  const r = toRaw(payload);
  const raw = {
    id: typeof r.id === "string" ? r.id : "",
    email: typeof r.email === "string" ? r.email : "",
    name: typeof r.name === "string" ? r.name : ((r.email as string) ?? ""),
    avatarUrl:
      typeof r.avatar_url === "string" && r.avatar_url.trim().length > 0
        ? r.avatar_url.trim()
        : typeof r.avatarUrl === "string" && r.avatarUrl.trim().length > 0
          ? r.avatarUrl.trim()
          : null,
    createdAt:
      typeof r.created_at === "string" && r.created_at.trim().length > 0
        ? r.created_at.trim()
        : null,
  };
  return userProfileSchema.parse(raw);
}

function normalizeUserPreferences(payload: unknown): UserPreferences {
  const r = toRaw(payload);
  const raw = {
    language: typeof r.language === "string" ? r.language : undefined,
    timezone: typeof r.timezone === "string" ? r.timezone : undefined,
    dateFormat:
      typeof r.date_format === "string"
        ? r.date_format
        : typeof r.dateFormat === "string"
          ? r.dateFormat
          : undefined,
    theme: r.theme,
    landingPage:
      typeof r.landing_page === "string"
        ? r.landing_page
        : typeof r.landingPage === "string"
          ? r.landingPage
          : undefined,
    keyboardShortcutHints:
      typeof r.keyboard_shortcut_hints === "boolean"
        ? r.keyboard_shortcut_hints
        : typeof r.keyboardShortcutHints === "boolean"
          ? r.keyboardShortcutHints
          : undefined,
    emailNotifications:
      typeof r.email_notifications === "boolean"
        ? r.email_notifications
        : typeof r.emailNotifications === "boolean"
          ? r.emailNotifications
          : undefined,
    digestFrequency: r.digest_frequency ?? r.digestFrequency,
  };
  const result = userPreferencesSchema.safeParse(raw);
  return result.success ? result.data : {};
}

// ── Outgoing payload mapping (snake_case for backend) ─────────────────────────

function toUpdateProfilePayload(
  values: UpdateProfileFormValues,
): Record<string, unknown> {
  return { name: values.name };
}

function toUpdatePreferencesPayload(
  values: UpdatePreferencesFormValues,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  if (values.language !== undefined) payload.language = values.language;
  if (values.timezone !== undefined) payload.timezone = values.timezone;
  if (values.dateFormat !== undefined) payload.date_format = values.dateFormat;
  if (values.theme !== undefined) payload.theme = values.theme;
  if (values.landingPage !== undefined)
    payload.landing_page = values.landingPage;
  if (values.keyboardShortcutHints !== undefined)
    payload.keyboard_shortcut_hints = values.keyboardShortcutHints;
  if (values.emailNotifications !== undefined)
    payload.email_notifications = values.emailNotifications;
  if (values.digestFrequency !== undefined)
    payload.digest_frequency = values.digestFrequency;
  return payload;
}

// ── API functions ─────────────────────────────────────────────────────────────

export async function getMe(): Promise<UserProfile> {
  const { meUrl } = getProfileEndpoints();
  if (!meUrl) throw new ProfileEndpointUnavailableError("meEnabled");
  const payload = await apiRequest<unknown>(meUrl, {
    method: "GET",
    retry: false,
  });
  return normalizeUserProfile(payload);
}

export async function updateMe(
  values: UpdateProfileFormValues,
): Promise<UserProfile> {
  const { meUrl } = getProfileEndpoints();
  if (!meUrl) throw new ProfileEndpointUnavailableError("meEnabled");
  const payload = await apiRequest<unknown>(meUrl, {
    method: "PATCH",
    json: toUpdateProfilePayload(values),
    retry: false,
  });
  return normalizeUserProfile(payload);
}

export async function getMyPreferences(): Promise<UserPreferences> {
  const { preferencesUrl } = getProfileEndpoints();
  if (!preferencesUrl)
    throw new ProfileEndpointUnavailableError("preferencesEnabled");
  const payload = await apiRequest<unknown>(preferencesUrl, {
    method: "GET",
    retry: false,
  });
  return normalizeUserPreferences(payload);
}

export async function updateMyPreferences(
  values: UpdatePreferencesFormValues,
): Promise<UserPreferences> {
  const { preferencesUrl } = getProfileEndpoints();
  if (!preferencesUrl)
    throw new ProfileEndpointUnavailableError("preferencesEnabled");
  const payload = await apiRequest<unknown>(preferencesUrl, {
    method: "PATCH",
    json: toUpdatePreferencesPayload(values),
    retry: false,
  });
  return normalizeUserPreferences(payload);
}

export async function signOutAllDevices(): Promise<void> {
  const { signOutAllUrl } = getProfileEndpoints();
  if (!signOutAllUrl)
    throw new ProfileEndpointUnavailableError("signOutAllDevicesEnabled");
  await apiRequest(signOutAllUrl, { method: "POST", retry: false });
}

export async function deletePersonalAccount(): Promise<void> {
  const { deleteAccountUrl } = getProfileEndpoints();
  if (!deleteAccountUrl)
    throw new ProfileEndpointUnavailableError("deleteAccountEnabled");
  await apiRequest(deleteAccountUrl, { method: "DELETE", retry: false });
}

export async function uploadAvatar(file: File): Promise<UserProfile> {
  const { avatarUrl } = getProfileEndpoints();
  if (!avatarUrl) throw new ProfileEndpointUnavailableError("avatarEnabled");
  const form = new FormData();
  form.append("file", file);
  const payload = await apiRequest<unknown>(avatarUrl, {
    method: "POST",
    body: form,
    retry: false,
  });
  return normalizeUserProfile(payload);
}

export async function removeAvatar(): Promise<void> {
  const { avatarUrl } = getProfileEndpoints();
  if (!avatarUrl) throw new ProfileEndpointUnavailableError("avatarEnabled");
  await apiRequest(avatarUrl, { method: "DELETE", retry: false });
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
  confirmNewPassword: string,
): Promise<void> {
  const { changePasswordUrl } = getProfileEndpoints();
  if (!changePasswordUrl)
    throw new ProfileEndpointUnavailableError("changePasswordEnabled");
  await apiRequest(changePasswordUrl, {
    method: "POST",
    json: {
      current_password: currentPassword,
      new_password: newPassword,
      confirm_new_password: confirmNewPassword,
    },
    retry: false,
  });
}
