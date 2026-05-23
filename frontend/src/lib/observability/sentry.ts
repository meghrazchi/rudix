import {
  redactObservabilityRecord,
  redactObservabilityValue,
} from "@/lib/observability/redaction";
import type {
  FrontendBreadcrumb,
  FrontendObservabilityContext,
  ObservabilityLevel,
} from "@/lib/observability/types";

const SENTRY_VERSION = "7";
const SENTRY_CLIENT = "rudix-frontend/0.1.0";
const MAX_BREADCRUMBS = 50;

type SentryTransportConfig = {
  storeUrl: string;
  publicKey: string;
  environment: string;
  release: string | null;
  sampleRate: number;
};

const breadcrumbBuffer: FrontendBreadcrumb[] = [];

let sentryConfigCache: SentryTransportConfig | null | undefined;

function trimToNull(value: string | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function parseRate(value: string | undefined): number {
  if (!value) {
    return 1;
  }
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    return 1;
  }
  return Math.max(0, Math.min(1, parsed));
}

function parseSentryConfig(): SentryTransportConfig | null {
  const dsn = trimToNull(process.env.NEXT_PUBLIC_SENTRY_DSN);
  if (!dsn) {
    return null;
  }

  try {
    const url = new URL(dsn);
    const publicKey = trimToNull(url.username);
    const path = url.pathname.replace(/\/+$/, "");
    const splitIndex = path.lastIndexOf("/");
    const projectId = splitIndex >= 0 ? path.slice(splitIndex + 1) : "";
    const prefixPath = splitIndex > 0 ? path.slice(0, splitIndex) : "";

    if (!publicKey || !projectId) {
      return null;
    }

    const storeUrl = `${url.protocol}//${url.host}${prefixPath}/api/${projectId}/store/`;
    const environment =
      trimToNull(process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT) ??
      trimToNull(process.env.NODE_ENV) ??
      "development";
    const release = trimToNull(process.env.NEXT_PUBLIC_SENTRY_RELEASE);

    return {
      storeUrl,
      publicKey,
      environment,
      release,
      sampleRate: parseRate(process.env.NEXT_PUBLIC_SENTRY_ERROR_SAMPLE_RATE),
    };
  } catch {
    return null;
  }
}

function getSentryConfig(): SentryTransportConfig | null {
  if (sentryConfigCache !== undefined) {
    return sentryConfigCache;
  }
  sentryConfigCache = parseSentryConfig();
  return sentryConfigCache;
}

function shouldSample(sampleRate: number): boolean {
  if (sampleRate >= 1) {
    return true;
  }
  if (sampleRate <= 0) {
    return false;
  }
  return Math.random() <= sampleRate;
}

function createEventId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID().replace(/-/g, "");
  }
  return Math.random().toString(16).slice(2).padEnd(32, "0").slice(0, 32);
}

function toUnixTimestampSeconds(input: number): number {
  return Math.floor(input / 1_000);
}

function toSentryLevel(
  level: ObservabilityLevel,
): "info" | "warning" | "error" {
  if (level === "warning") {
    return "warning";
  }
  if (level === "error") {
    return "error";
  }
  return "info";
}

function normalizeError(input: unknown): Error {
  if (input instanceof Error) {
    return input;
  }

  if (typeof input === "string") {
    return new Error(input);
  }

  return new Error("Unknown frontend exception");
}

function buildTags(
  context: FrontendObservabilityContext | undefined,
): Record<string, string> {
  const tags: Record<string, string> = {};

  if (context?.feature) {
    tags.feature = context.feature;
  }
  if (context?.route) {
    tags.route = context.route;
  }
  if (context?.requestId) {
    tags.request_id = context.requestId;
  }
  if (context?.traceId) {
    tags.trace_id = context.traceId;
  }

  if (context?.tags) {
    for (const [key, value] of Object.entries(context.tags)) {
      if (value === null || value === undefined) {
        continue;
      }
      tags[key] = String(value);
    }
  }

  return tags;
}

function buildBreadcrumbPayload(): Array<Record<string, unknown>> {
  return breadcrumbBuffer.map((entry) => ({
    category: entry.category,
    message: entry.message,
    level: toSentryLevel(entry.level ?? "info"),
    timestamp: toUnixTimestampSeconds(entry.timestamp ?? Date.now()),
    data: redactObservabilityRecord(entry.data),
  }));
}

async function sendSentryStoreEvent(
  payload: Record<string, unknown>,
): Promise<void> {
  const config = getSentryConfig();
  if (!config || !shouldSample(config.sampleRate)) {
    return;
  }

  const url = `${config.storeUrl}?sentry_key=${encodeURIComponent(config.publicKey)}&sentry_version=${SENTRY_VERSION}&sentry_client=${encodeURIComponent(SENTRY_CLIENT)}`;
  await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    keepalive: true,
  });
}

export function isFrontendMonitoringEnabled(): boolean {
  return getSentryConfig() !== null;
}

export function pushFrontendBreadcrumb(breadcrumb: FrontendBreadcrumb): void {
  const next = {
    ...breadcrumb,
    timestamp: breadcrumb.timestamp ?? Date.now(),
  };

  breadcrumbBuffer.push(next);
  if (breadcrumbBuffer.length > MAX_BREADCRUMBS) {
    breadcrumbBuffer.splice(0, breadcrumbBuffer.length - MAX_BREADCRUMBS);
  }
}

export function resetFrontendBreadcrumbsForTesting(): void {
  breadcrumbBuffer.length = 0;
  sentryConfigCache = undefined;
}

export async function captureFrontendException(
  errorInput: unknown,
  context?: FrontendObservabilityContext,
): Promise<void> {
  const config = getSentryConfig();
  if (!config) {
    return;
  }

  const error = normalizeError(errorInput);
  const now = Date.now();

  const event: Record<string, unknown> = {
    event_id: createEventId(),
    platform: "javascript",
    level: toSentryLevel(context?.level ?? "error"),
    logger: "rudix.frontend",
    timestamp: toUnixTimestampSeconds(now),
    environment: config.environment,
    release: config.release ?? undefined,
    message: clampErrorMessage(error.message),
    exception: {
      values: [
        {
          type: error.name || "Error",
          value: clampErrorMessage(error.message),
        },
      ],
    },
    tags: buildTags(context),
    extra: {
      context: redactObservabilityRecord(context?.extra),
      error_name: error.name,
    },
    breadcrumbs: {
      values: buildBreadcrumbPayload(),
    },
  };

  if (typeof error.stack === "string" && error.stack.trim().length > 0) {
    event.extra = {
      ...(event.extra as Record<string, unknown>),
      stack: clampErrorMessage(error.stack),
    };
  }

  try {
    await sendSentryStoreEvent(
      redactObservabilityValue(event) as Record<string, unknown>,
    );
  } catch {
    // Monitoring failures must never break user-facing behavior.
  }
}

function clampErrorMessage(message: string): string {
  if (message.length <= 600) {
    return message;
  }
  return `${message.slice(0, 600)}…`;
}
