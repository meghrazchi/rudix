"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale } from "next-intl";
import type { SupportedLocale } from "@/i18n/routing";
import { getAdminObservabilityTranslations } from "./admin-observability-translations";

import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getProviderObservabilitySnapshot,
  type ProviderHealthCard,
  type ProviderObservabilitySnapshot,
  type SloSuggestion,
} from "@/lib/api/provider-observability";
import { queryKeys } from "@/lib/api/query";

type TimeRange = { from: string; to: string };

function formatPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatMs(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(value)} ms`;
}

function formatCount(value: number): string {
  return value.toLocaleString();
}

type CardStatus = "healthy" | "degraded" | "missing";

function resolveCardStatus(card: ProviderHealthCard): CardStatus {
  if (card.total_events === 0) return "missing";
  if (
    (card.failure_rate != null && card.failure_rate > 0.05) ||
    (card.timeout_rate != null && card.timeout_rate > 0.02) ||
    (card.fallback_rate != null && card.fallback_rate > 0.1)
  ) {
    return "degraded";
  }
  return "healthy";
}

function statusBadgeClass(s: CardStatus): string {
  if (s === "healthy") return "bg-emerald-100 text-emerald-800";
  if (s === "degraded") return "bg-rose-100 text-rose-800";
  return "bg-slate-200 text-slate-700";
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm">
      <dt className="text-[#4f4b68]">{label}</dt>
      <dd className="font-semibold text-[#2f2a46]">{value}</dd>
    </div>
  );
}

function SloSuggestionItem({ suggestion }: { suggestion: SloSuggestion }) {
  const t = getAdminObservabilityTranslations(useLocale() as SupportedLocale);
  const metricLabel: Record<string, string> = {
    failure_rate: t.errorRate,
    timeout_rate: t.timedOut,
    fallback_rate: t.fallback,
    avg_latency_ms: t.avgLatency,
    p95_latency_ms: t.p95Latency,
  };
  const label = metricLabel[suggestion.metric] ?? suggestion.metric;
  const current =
    suggestion.unit === "ms"
      ? `${Math.round(suggestion.current_value)} ms`
      : `${(suggestion.current_value * 100).toFixed(1)}%`;
  const threshold =
    suggestion.unit === "ms"
      ? `${Math.round(suggestion.suggested_threshold)} ms`
      : `${(suggestion.suggested_threshold * 100).toFixed(1)}%`;

  return (
    <li className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm">
      <p className="font-semibold text-amber-900">
        {label}: {current}{" "}
        <span className="font-normal text-amber-700">
          (suggested &le; {threshold})
        </span>
      </p>
      <p className="mt-0.5 text-amber-800">{suggestion.rationale}</p>
    </li>
  );
}

function ProviderCard({ card }: { card: ProviderHealthCard }) {
  const locale = useLocale() as SupportedLocale;
  const t = getAdminObservabilityTranslations(locale);
  const cardStatus = resolveCardStatus(card);

  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-bold text-[#2a2640]">
            {card.provider_key}
          </h3>
          <p className="mt-0.5 text-xs text-[#6d6985]">
            {formatCount(card.total_events)} {t.events}
          </p>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${statusBadgeClass(cardStatus)}`}
        >
          {cardStatus === "healthy"
            ? t.healthy
            : cardStatus === "degraded"
              ? t.degraded
              : t.noData}
        </span>
      </div>

      {card.total_events === 0 ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {t.providerMissing}
        </p>
      ) : (
        <dl className="space-y-2">
          <MetricRow
            label={t.failedEvents}
            value={`${formatCount(card.failed_events)} (${formatPct(card.failure_rate)})`}
          />
          <MetricRow
            label={t.timedOut}
            value={`${formatCount(card.timed_out_events)} (${formatPct(card.timeout_rate)})`}
          />
          <MetricRow
            label={t.fallback}
            value={`${formatCount(card.fallback_events)} (${formatPct(card.fallback_rate)})`}
          />
          <MetricRow
            label={t.retryEvents}
            value={`${formatCount(card.retry_events)} (${formatPct(card.retry_rate)})`}
          />
          {card.avg_retry_count != null ? (
            <MetricRow
              label={t.avgRetries}
              value={card.avg_retry_count.toFixed(2)}
            />
          ) : null}
          <MetricRow
            label={t.avgLatency}
            value={formatMs(card.avg_latency_ms)}
          />
          <MetricRow
            label={t.p95Latency}
            value={formatMs(card.p95_latency_ms)}
          />
        </dl>
      )}

      {card.slo_suggestions.length > 0 ? (
        <div className="mt-4">
          <p className="mb-2 text-xs font-semibold tracking-wide text-amber-700 uppercase">
            {t.slo}
          </p>
          <ul className="space-y-2">
            {card.slo_suggestions.map((s) => (
              <SloSuggestionItem key={s.metric} suggestion={s} />
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}

function SnapshotMeta({
  snapshot,
}: {
  snapshot: ProviderObservabilitySnapshot;
}) {
  const t = getAdminObservabilityTranslations(useLocale() as SupportedLocale);
  const dt = new Date(snapshot.generated_at);
  const label = Number.isNaN(dt.getTime())
    ? snapshot.generated_at
    : dt.toLocaleString();
  return (
    <p className="text-xs text-[#6a6780]">
      {t.providerSnapshot} <bdi dir="ltr">{label}</bdi> — {t.range}{" "}
      <bdi dir="ltr">
        {snapshot.range.from} – {snapshot.range.to}
      </bdi>
    </p>
  );
}

export function ProviderHealthSection({ timeRange }: { timeRange: TimeRange }) {
  const t = getAdminObservabilityTranslations(useLocale() as SupportedLocale);
  const query = useQuery({
    queryKey: queryKeys.admin.providerObservability(timeRange),
    queryFn: () => getProviderObservabilitySnapshot(timeRange),
  });

  if (query.isLoading) {
    return (
      <LoadingState
        compact
        className="rounded-2xl border border-[#d7d4e8] bg-white px-5 py-8 shadow-sm"
        title={t.loadingProviders}
      />
    );
  }

  if (query.isError) {
    return (
      <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <ErrorState
          compact
          error={query.error}
          description={getApiErrorMessage(query.error)}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }

  if (!query.data) return null;

  const snapshot = query.data;

  return (
    <section className="space-y-4">
      <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-start justify-between gap-2">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">
              {t.providerHealth}
            </h2>
            <p className="mt-1 text-sm text-[#68647b]">{t.intro}</p>
          </div>
          <button
            type="button"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
            className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {query.isFetching ? t.refreshing : t.refresh}
          </button>
        </div>
        <SnapshotMeta snapshot={snapshot} />
      </div>

      {snapshot.telemetry_missing ? (
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            {t.providerMissing}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {snapshot.providers.map((card) => (
            <ProviderCard key={card.provider_key} card={card} />
          ))}
        </div>
      )}
    </section>
  );
}
