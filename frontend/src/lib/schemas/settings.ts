import { z } from "zod";

export const PROFILE_UI_STORAGE_KEY = "rudix.settings.profile-ui.v1";

export const LANGUAGE_OPTIONS = [
  { value: "en", label: "English (United States)" },
  { value: "de", label: "German (Germany)" },
  { value: "fr", label: "French (France)" },
  { value: "es", label: "Spanish" },
  { value: "ja", label: "Japanese" },
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
