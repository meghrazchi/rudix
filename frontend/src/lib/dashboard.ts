import type { UsageSummaryResponse } from "@/lib/api/admin-usage";
import type { ChatSessionResponse } from "@/lib/api/chat";
import type { AppRole } from "@/lib/auth-session";

export type DashboardRangePreset = "7d" | "30d" | "90d";

export const DASHBOARD_RANGE_PRESETS: Array<{
  value: DashboardRangePreset;
  label: string;
  days: number;
}> = [
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "30d", label: "Last 30 days", days: 30 },
  { value: "90d", label: "Last 90 days", days: 90 },
];

const integerFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0,
});

const percentFormatter = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const millisecondFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0,
});

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatUtcDateOnly(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return value;
}

function extractNumericValue(
  record: Record<string, unknown>,
  keys: string[],
): number | null {
  for (const key of keys) {
    const candidate = asFiniteNumber(record[key]);
    if (candidate !== null) {
      return candidate;
    }
  }
  return null;
}

export function resolveUsageDateRange(
  preset: DashboardRangePreset,
  now: Date = new Date(),
): {
  from: string;
  to: string;
} {
  const selected =
    DASHBOARD_RANGE_PRESETS.find((option) => option.value === preset) ??
    DASHBOARD_RANGE_PRESETS[1];

  const end = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  );
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - (selected.days - 1));

  return {
    from: formatUtcDateOnly(start),
    to: formatUtcDateOnly(end),
  };
}

export function canViewAdminUsage(role: AppRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

export function estimateQuestionsAsked(
  sessions: ChatSessionResponse[],
): number {
  const totalMessages = sessions.reduce(
    (sum, session) => sum + Math.max(0, session.message_count),
    0,
  );
  return Math.ceil(totalMessages / 2);
}

export function formatInteger(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "N/A";
  }
  return integerFormatter.format(value);
}

export function formatPercentage(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "N/A";
  }
  return percentFormatter.format(Math.max(0, Math.min(1, value)));
}

export function formatLatencyMs(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "N/A";
  }
  return `${millisecondFormatter.format(Math.max(0, value))} ms`;
}

export function formatUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "N/A";
  }
  return currencyFormatter.format(Math.max(0, value));
}

export function computeIndexingSuccess(
  totalDocuments: number,
  indexedDocuments: number,
): number | null {
  if (!Number.isFinite(totalDocuments) || totalDocuments <= 0) {
    return null;
  }
  if (!Number.isFinite(indexedDocuments) || indexedDocuments < 0) {
    return null;
  }
  return Math.max(0, Math.min(1, indexedDocuments / totalDocuments));
}

export function extractAverageConfidence(
  usage: UsageSummaryResponse,
): number | null {
  const totals = usage.totals as unknown as Record<string, unknown>;
  const direct = extractNumericValue(totals, [
    "average_confidence",
    "avg_confidence",
    "confidence_avg",
    "confidence_score_avg",
  ]);
  if (direct !== null) {
    return direct;
  }

  const series = usage.series as unknown as Array<Record<string, unknown>>;
  const seriesValues = series
    .map((point) =>
      extractNumericValue(point, [
        "average_confidence",
        "avg_confidence",
        "confidence_avg",
        "confidence_score_avg",
      ]),
    )
    .filter((value): value is number => value !== null);

  if (seriesValues.length === 0) {
    return null;
  }

  return (
    seriesValues.reduce((sum, value) => sum + value, 0) / seriesValues.length
  );
}

export function extractAverageLatencyMs(
  usage: UsageSummaryResponse,
): number | null {
  const totals = usage.totals as unknown as Record<string, unknown>;
  const direct = extractNumericValue(totals, [
    "average_latency_ms",
    "avg_latency_ms",
    "latency_ms_avg",
    "answer_latency_ms_avg",
  ]);
  if (direct !== null) {
    return direct;
  }

  const series = usage.series as unknown as Array<Record<string, unknown>>;
  const seriesValues = series
    .map((point) =>
      extractNumericValue(point, [
        "average_latency_ms",
        "avg_latency_ms",
        "latency_ms_avg",
        "answer_latency_ms_avg",
      ]),
    )
    .filter((value): value is number => value !== null);

  if (seriesValues.length === 0) {
    return null;
  }

  return (
    seriesValues.reduce((sum, value) => sum + value, 0) / seriesValues.length
  );
}
