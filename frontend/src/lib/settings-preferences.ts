import { z } from "zod";

import { apiRequest } from "@/lib/api/request";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function parseIntegerEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return parsed;
}

function parseBooleanEnv(
  value: string | undefined,
  fallback: boolean,
): boolean {
  if (!value) {
    return fallback;
  }
  const normalized = value.trim().toLowerCase();
  if (
    normalized === "1" ||
    normalized === "true" ||
    normalized === "yes" ||
    normalized === "on"
  ) {
    return true;
  }
  if (
    normalized === "0" ||
    normalized === "false" ||
    normalized === "no" ||
    normalized === "off"
  ) {
    return false;
  }
  return fallback;
}

function clampInteger(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

const SETTINGS_STORAGE_KEY = "rudix.settings.preferences.v1";

const TOP_K_MIN = Math.max(
  1,
  parseIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_MIN, 1),
);
const TOP_K_MAX = Math.max(
  TOP_K_MIN,
  parseIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_MAX, 20),
);
const TOP_K_DEFAULT = clampInteger(
  parseIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_DEFAULT, 5),
  TOP_K_MIN,
  TOP_K_MAX,
);

export const settingsTopKBounds = {
  min: TOP_K_MIN,
  max: TOP_K_MAX,
  defaultValue: TOP_K_DEFAULT,
} as const;

export const ANSWER_DETAIL_LEVELS = ["brief", "standard", "detailed"] as const;
export type AnswerDetailLevel = (typeof ANSWER_DETAIL_LEVELS)[number];

export const settingsPreferencesSchema = z.object({
  defaultTopK: z
    .number()
    .int("Default top-k must be a whole number.")
    .min(TOP_K_MIN, `Default top-k must be at least ${TOP_K_MIN}.`)
    .max(TOP_K_MAX, `Default top-k must be at most ${TOP_K_MAX}.`),
  rerankEnabled: z.boolean(),
  developerMode: z.boolean(),
  answerDetailLevel: z.enum(ANSWER_DETAIL_LEVELS),
  showConfidenceScore: z.boolean(),
  expandCitations: z.boolean(),
  notifications: z.object({
    productUpdates: z.boolean(),
    securityAlerts: z.boolean(),
    documentProcessing: z.boolean(),
    failedIndexing: z.boolean(),
    evaluationCompletion: z.boolean(),
    billingWarnings: z.boolean(),
  }),
});

export type SettingsPreferences = z.infer<typeof settingsPreferencesSchema>;

export type PersistedSettingsPreferences = {
  preferences: SettingsPreferences;
  persistenceScope: "remote" | "local";
};

type SettingsPreferencesPayload = {
  default_top_k?: number;
  defaultTopK?: number;
  top_k?: number;
  rerank_enabled?: boolean;
  rerankEnabled?: boolean;
  developer_mode?: boolean;
  developerMode?: boolean;
  answer_detail_level?: string;
  answerDetailLevel?: string;
  show_confidence_score?: boolean;
  showConfidenceScore?: boolean;
  expand_citations?: boolean;
  expandCitations?: boolean;
  notifications?: {
    product_updates?: boolean;
    productUpdates?: boolean;
    security_alerts?: boolean;
    securityAlerts?: boolean;
    document_processing?: boolean;
    documentProcessing?: boolean;
    failed_indexing?: boolean;
    failedIndexing?: boolean;
    evaluation_completion?: boolean;
    evaluationCompletion?: boolean;
    billing_warnings?: boolean;
    billingWarnings?: boolean;
  } | null;
};

type SettingsPreferencesConfig = {
  loadUrl: string | null;
  saveUrl: string | null;
  localFallbackEnabled: boolean;
};

function toSettingsPreferencesConfig(): SettingsPreferencesConfig {
  return {
    loadUrl: trimToNull(process.env.NEXT_PUBLIC_SETTINGS_PREFERENCES_LOAD_URL),
    saveUrl: trimToNull(process.env.NEXT_PUBLIC_SETTINGS_PREFERENCES_SAVE_URL),
    localFallbackEnabled:
      parseBooleanEnv(
        process.env.NEXT_PUBLIC_SETTINGS_PREFERENCES_LOCAL_FALLBACK,
        false,
      ) || process.env.NODE_ENV !== "production",
  };
}

export function createDefaultSettingsPreferences(): SettingsPreferences {
  const runtimeConfig = getFrontendRuntimeConfig();

  return {
    defaultTopK: TOP_K_DEFAULT,
    rerankEnabled: true,
    developerMode: runtimeConfig.features.developerMode,
    answerDetailLevel: "standard",
    showConfidenceScore: false,
    expandCitations: false,
    notifications: {
      productUpdates: true,
      securityAlerts: true,
      documentProcessing: true,
      failedIndexing: true,
      evaluationCompletion: true,
      billingWarnings: true,
    },
  };
}

function sanitizeBoolean(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  return fallback;
}

function sanitizeNumber(value: unknown, fallback: number): number {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return fallback;
  }
  return Math.trunc(value);
}

function sanitizeAnswerDetailLevel(
  value: unknown,
  fallback: AnswerDetailLevel,
): AnswerDetailLevel {
  if (
    typeof value === "string" &&
    (ANSWER_DETAIL_LEVELS as readonly string[]).includes(value)
  ) {
    return value as AnswerDetailLevel;
  }
  return fallback;
}

function normalizePayloadToPreferences(payload: unknown): SettingsPreferences {
  const defaults = createDefaultSettingsPreferences();
  if (
    typeof payload !== "object" ||
    payload === null ||
    Array.isArray(payload)
  ) {
    return defaults;
  }

  const candidate = payload as SettingsPreferencesPayload;
  const notifications = candidate.notifications ?? {};

  const next: SettingsPreferences = {
    defaultTopK: sanitizeNumber(
      candidate.default_top_k ?? candidate.defaultTopK ?? candidate.top_k,
      defaults.defaultTopK,
    ),
    rerankEnabled: sanitizeBoolean(
      candidate.rerank_enabled ?? candidate.rerankEnabled,
      defaults.rerankEnabled,
    ),
    developerMode: sanitizeBoolean(
      candidate.developer_mode ?? candidate.developerMode,
      defaults.developerMode,
    ),
    answerDetailLevel: sanitizeAnswerDetailLevel(
      candidate.answer_detail_level ?? candidate.answerDetailLevel,
      defaults.answerDetailLevel,
    ),
    showConfidenceScore: sanitizeBoolean(
      candidate.show_confidence_score ?? candidate.showConfidenceScore,
      defaults.showConfidenceScore,
    ),
    expandCitations: sanitizeBoolean(
      candidate.expand_citations ?? candidate.expandCitations,
      defaults.expandCitations,
    ),
    notifications: {
      productUpdates: sanitizeBoolean(
        notifications.product_updates ?? notifications.productUpdates,
        defaults.notifications.productUpdates,
      ),
      securityAlerts: sanitizeBoolean(
        notifications.security_alerts ?? notifications.securityAlerts,
        defaults.notifications.securityAlerts,
      ),
      documentProcessing: sanitizeBoolean(
        notifications.document_processing ?? notifications.documentProcessing,
        defaults.notifications.documentProcessing,
      ),
      failedIndexing: sanitizeBoolean(
        notifications.failed_indexing ?? notifications.failedIndexing,
        defaults.notifications.failedIndexing,
      ),
      evaluationCompletion: sanitizeBoolean(
        notifications.evaluation_completion ??
          notifications.evaluationCompletion,
        defaults.notifications.evaluationCompletion,
      ),
      billingWarnings: sanitizeBoolean(
        notifications.billing_warnings ?? notifications.billingWarnings,
        defaults.notifications.billingWarnings,
      ),
    },
  };

  return settingsPreferencesSchema.parse(next);
}

function toPayload(preferences: SettingsPreferences): Record<string, unknown> {
  return {
    default_top_k: preferences.defaultTopK,
    rerank_enabled: preferences.rerankEnabled,
    developer_mode: preferences.developerMode,
    answer_detail_level: preferences.answerDetailLevel,
    show_confidence_score: preferences.showConfidenceScore,
    expand_citations: preferences.expandCitations,
    notifications: {
      product_updates: preferences.notifications.productUpdates,
      security_alerts: preferences.notifications.securityAlerts,
      document_processing: preferences.notifications.documentProcessing,
      failed_indexing: preferences.notifications.failedIndexing,
      evaluation_completion: preferences.notifications.evaluationCompletion,
      billing_warnings: preferences.notifications.billingWarnings,
    },
  };
}

function saveToLocalStorage(preferences: SettingsPreferences): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(
    SETTINGS_STORAGE_KEY,
    JSON.stringify(toPayload(preferences)),
  );
}

function readFromLocalStorage(): SettingsPreferences | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as unknown;
    return normalizePayloadToPreferences(parsed);
  } catch {
    return null;
  }
}

export async function loadSettingsPreferences(): Promise<SettingsPreferences> {
  const config = toSettingsPreferencesConfig();

  if (config.loadUrl) {
    try {
      const remote = await apiRequest<unknown>(config.loadUrl, {
        method: "GET",
        retry: false,
      });
      const normalized = normalizePayloadToPreferences(remote);
      saveToLocalStorage(normalized);
      return normalized;
    } catch (error) {
      if (!config.localFallbackEnabled) {
        throw error;
      }
    }
  }

  return readFromLocalStorage() ?? createDefaultSettingsPreferences();
}

export async function persistSettingsPreferences(
  preferences: SettingsPreferences,
): Promise<PersistedSettingsPreferences> {
  const config = toSettingsPreferencesConfig();
  const parsed = settingsPreferencesSchema.parse(preferences);
  saveToLocalStorage(parsed);

  if (!config.saveUrl) {
    return {
      preferences: parsed,
      persistenceScope: "local",
    };
  }

  try {
    await apiRequest<Record<string, unknown>>(config.saveUrl, {
      method: "POST",
      json: toPayload(parsed),
      retry: false,
    });
    return {
      preferences: parsed,
      persistenceScope: "remote",
    };
  } catch (error) {
    if (!config.localFallbackEnabled) {
      throw error;
    }
    return {
      preferences: parsed,
      persistenceScope: "local",
    };
  }
}
