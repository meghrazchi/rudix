import { apiRequest } from "@/lib/api/request";
import { readSessionFromStorage } from "@/lib/auth-session";
import {
  hasCurrentConsent,
  readConsentRecord,
  type ConsentDecisions,
} from "@/lib/consent";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

declare global {
  interface Window {
    _paq?: Array<unknown[]>;
  }
}

export type AnalyticsSurface = "public" | "app" | "admin";

export type AnalyticsFeatureArea =
  | "documents"
  | "chat"
  | "evaluations"
  | "settings"
  | "connectors"
  | "public"
  | "dashboard"
  | "admin";

export type AnalyticsEventName =
  | "activation.signup_completed"
  | "activation.organization_created"
  | "activation.first_upload"
  | "activation.first_indexed_document"
  | "activation.first_question"
  | "activation.first_cited_answer"
  | "feature.documents.viewed"
  | "feature.documents.uploaded"
  | "feature.documents.indexed"
  | "feature.dashboard.viewed"
  | "feature.chat.viewed"
  | "feature.chat.question_submitted"
  | "feature.chat.answer_rendered"
  | "feature.chat.citation_opened"
  | "feature.chat.retrieval_diagnostics_viewed"
  | "feature.evaluations.viewed"
  | "feature.settings.viewed"
  | "feature.connectors.viewed"
  | "feature.public_page.viewed";

export type AnalyticsEventPayload = {
  surface: AnalyticsSurface;
  route?: string;
  pageKey?: string;
  featureArea?: AnalyticsFeatureArea;
  entityId?: string;
  entityType?: string;
  status?: string;
  method?: string;
  count?: number;
  citationCount?: number;
  hasCitations?: boolean;
  locale?: string;
  source?: string;
  dedupeKey?: string;
};

type StoredAnalyticsRecord = {
  key: string;
  recordedAt: number;
};

type MatomoConfig = {
  url: string;
  siteId: string;
};

type TrackOptions = {
  dedupeOnce?: boolean;
  sendToBackend?: boolean;
};

const ANALYTICS_STORAGE_KEY = "rudix.analytics.v1";
const ANALYTICS_BACKEND_EVENT_VERSION = 1;

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function getMatomoConfig(): MatomoConfig | null {
  const config = getFrontendRuntimeConfig();
  if (!config.features.analyticsEnabled) {
    return null;
  }

  if (!config.analytics.matomoUrl || !config.analytics.matomoSiteId) {
    return null;
  }

  return {
    url: config.analytics.matomoUrl,
    siteId: config.analytics.matomoSiteId,
  };
}

function readStoredRecords(): StoredAnalyticsRecord[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(ANALYTICS_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed.filter((item): item is StoredAnalyticsRecord => {
      if (typeof item !== "object" || item === null) return false;
      const candidate = item as Record<string, unknown>;
      return (
        typeof candidate.key === "string" &&
        candidate.key.length > 0 &&
        typeof candidate.recordedAt === "number"
      );
    });
  } catch {
    return [];
  }
}

function persistStoredRecords(records: StoredAnalyticsRecord[]): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(ANALYTICS_STORAGE_KEY, JSON.stringify(records));
  } catch {
    // Ignore storage failures.
  }
}

function rememberOnce(key: string): boolean {
  if (typeof window === "undefined") {
    return true;
  }

  const records = readStoredRecords();
  if (records.some((record) => record.key === key)) {
    return false;
  }

  const nextRecords = [...records, { key, recordedAt: Date.now() }].slice(-200);
  persistStoredRecords(nextRecords);
  return true;
}

function canTrack(): boolean {
  return (
    hasCurrentConsent() && getFrontendRuntimeConfig().features.analyticsEnabled
  );
}

function normalizePathname(value: string | undefined): string | null {
  const trimmed = trimToNull(value);
  if (!trimmed) {
    return null;
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function safeName(value: string | null | undefined): string {
  return trimToNull(value) ?? "";
}

function sanitizePayload(
  payload: AnalyticsEventPayload,
): Record<string, unknown> {
  return {
    surface: payload.surface,
    route: normalizePathname(payload.route),
    page_key: trimToNull(payload.pageKey),
    feature_area: payload.featureArea ?? null,
    entity_id: trimToNull(payload.entityId),
    entity_type: trimToNull(payload.entityType),
    status: trimToNull(payload.status),
    method: trimToNull(payload.method),
    count: payload.count ?? null,
    citation_count: payload.citationCount ?? null,
    has_citations: payload.hasCitations ?? null,
    locale: trimToNull(payload.locale),
    source: trimToNull(payload.source),
    dedupe_key: trimToNull(payload.dedupeKey),
  };
}

function eventKey(
  eventName: AnalyticsEventName,
  payload: AnalyticsEventPayload,
): string {
  return [
    eventName,
    payload.surface,
    normalizePathname(payload.route) ?? "",
    trimToNull(payload.pageKey) ?? "",
    trimToNull(payload.entityId) ?? "",
    trimToNull(payload.dedupeKey) ?? "",
  ].join("|");
}

function resolvePageViewEventName(
  surface: AnalyticsSurface,
  featureArea: AnalyticsFeatureArea,
): AnalyticsEventName {
  if (surface === "public") {
    return "feature.public_page.viewed";
  }

  switch (featureArea) {
    case "documents":
      return "feature.documents.viewed";
    case "dashboard":
      return "feature.dashboard.viewed";
    case "chat":
      return "feature.chat.viewed";
    case "evaluations":
      return "feature.evaluations.viewed";
    case "settings":
      return "feature.settings.viewed";
    case "connectors":
      return "feature.connectors.viewed";
    default:
      return surface === "admin"
        ? "feature.settings.viewed"
        : "feature.public_page.viewed";
  }
}

function sendToMatomo(
  eventName: AnalyticsEventName,
  payload: AnalyticsEventPayload,
): void {
  const config = getMatomoConfig();
  if (!config || typeof window === "undefined") {
    return;
  }

  const tracker = window._paq ?? [];
  window._paq = tracker;
  const [category, ...rest] = eventName.split(".");
  const action = rest.join(".");
  const name =
    safeName(payload.pageKey) ||
    safeName(payload.route) ||
    safeName(payload.featureArea);
  tracker.push(["trackEvent", category, action, name]);
}

async function sendToBackend(
  eventName: AnalyticsEventName,
  payload: AnalyticsEventPayload,
  schemaVersion = ANALYTICS_BACKEND_EVENT_VERSION,
): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }

  const session = readSessionFromStorage();
  if (!session?.organizationId) {
    return;
  }

  await apiRequest("/analytics/events", {
    method: "POST",
    retry: false,
    json: {
      event_name: eventName,
      schema_version: schemaVersion,
      ...sanitizePayload(payload),
    },
  });
}

export async function trackAnalyticsEvent(
  eventName: AnalyticsEventName,
  payload: AnalyticsEventPayload,
  options?: TrackOptions,
): Promise<void> {
  if (!canTrack()) {
    return;
  }

  const dedupeOnce = options?.dedupeOnce ?? false;
  const dedupeKey =
    payload.dedupeKey ?? (dedupeOnce ? eventKey(eventName, payload) : null);

  if (dedupeKey && !rememberOnce(dedupeKey)) {
    return;
  }

  sendToMatomo(eventName, payload);

  if (options?.sendToBackend === false) {
    return;
  }

  try {
    await sendToBackend(eventName, payload);
  } catch {
    // Fire-and-forget analytics must never block the UI.
  }
}

export async function trackPageView(params: {
  pageKey: string;
  route: string;
  surface: AnalyticsSurface;
  featureArea: AnalyticsFeatureArea;
  locale?: string;
}): Promise<void> {
  await trackAnalyticsEvent(
    resolvePageViewEventName(params.surface, params.featureArea),
    {
      pageKey: params.pageKey,
      route: params.route,
      surface: params.surface,
      featureArea: params.featureArea,
      locale: params.locale,
    },
    { dedupeOnce: true, sendToBackend: params.surface !== "public" },
  );
}

export async function trackActivationEvent(
  eventName:
    | "activation.signup_completed"
    | "activation.organization_created"
    | "activation.first_upload"
    | "activation.first_indexed_document"
    | "activation.first_question"
    | "activation.first_cited_answer",
  payload: Omit<AnalyticsEventPayload, "surface"> & {
    surface: AnalyticsSurface;
  },
): Promise<void> {
  await trackAnalyticsEvent(eventName, payload, { dedupeOnce: true });
}

export async function trackFeatureEvent(
  eventName: AnalyticsEventName,
  payload: Omit<AnalyticsEventPayload, "surface"> & {
    surface: AnalyticsSurface;
  },
): Promise<void> {
  await trackAnalyticsEvent(eventName, payload);
}

export async function trackOnboardingEvent(
  eventName:
    | "onboarding_step_complete"
    | "onboarding_step_skipped"
    | "onboarding_dismissed"
    | "onboarding_tour_started"
    | "onboarding_tour_completed"
    | "onboarding_reset"
    | "onboarding_sample_docs_loaded",
  params?: Record<string, string | number | boolean>,
): Promise<void> {
  if (!canTrack()) {
    return;
  }

  const surface: AnalyticsSurface = "app";
  const payload: AnalyticsEventPayload = {
    surface,
    route: "/organization-onboarding",
    pageKey: "organization-onboarding",
    featureArea: "settings",
    source: eventName,
  };

  if (eventName === "onboarding_sample_docs_loaded") {
    await trackFeatureEvent("feature.settings.viewed", {
      ...payload,
      source: eventName,
    });
    return;
  }

  if (eventName === "onboarding_tour_completed") {
    await trackFeatureEvent("feature.settings.viewed", payload);
    return;
  }

  void params;
  await trackFeatureEvent("feature.settings.viewed", payload);
}

export function hasAnalyticsConsent(): boolean {
  return canTrack();
}

export function readAnalyticsConsentDecisions(): ConsentDecisions | null {
  return readConsentRecord()?.decisions ?? null;
}
