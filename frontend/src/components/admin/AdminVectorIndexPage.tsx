"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { isApiClientError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { useRealtimeAwareInterval } from "@/lib/realtime/polling";
import {
  getVectorIndexStatus,
  progressFraction,
  type VectorIndexStatus,
} from "@/lib/api/vector-index";
import { canViewAdminUsage } from "@/lib/dashboard";
import { extractRequestIdFromError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";

// Poll only while a generation is building or verifying (R06-08).
export const VECTOR_INDEX_POLL_MS = 15_000;

export function vectorIndexRefetchInterval(
  data: VectorIndexStatus | undefined,
): number | false {
  return data?.building ? VECTOR_INDEX_POLL_MS : false;
}

function formatDate(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toLocaleString();
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold tracking-wide text-[#68647b] uppercase">
        {label}
      </dt>
      <dd className="mt-1 text-sm font-semibold break-all text-[#2a2640]">
        {value}
      </dd>
    </div>
  );
}

function StatusCard({ status }: { status: VectorIndexStatus }) {
  const t = useTranslations("adminVectorIndex");
  const active = status.active;
  const building = status.building ?? null;
  const progress = status.progress ?? null;
  const percent = Math.round(progressFraction(progress) * 100);
  const activatedAt = formatDate(active?.activated_at);
  const startedAt = formatDate(building?.started_at);

  return (
    <div className="space-y-4">
      {status.legacy_mode ? (
        <p
          role="note"
          className="rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-sm text-indigo-900"
        >
          {t("legacyNotice")}
        </p>
      ) : null}

      <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="mb-4 text-lg font-bold text-[#2a2640]">
          {t("active.title")}
        </h2>
        {active ? (
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label={t("active.model")} value={active.embedding_model} />
            <Field
              label={t("active.dimensions")}
              value={String(active.vector_size)}
            />
            <Field
              label={t("active.generation")}
              value={
                active.generation === null
                  ? t("active.legacyGeneration")
                  : String(active.generation)
              }
            />
            {activatedAt ? (
              <Field label={t("active.activatedAt")} value={activatedAt} />
            ) : null}
          </dl>
        ) : (
          <EmptyState
            compact
            title={t("active.notAdoptedTitle")}
            description={t("active.notAdoptedDescription")}
          />
        )}
      </article>

      <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="mb-4 text-lg font-bold text-[#2a2640]">
          {t("building.title")}
        </h2>
        {building ? (
          <div className="space-y-4">
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Field
                label={t("building.model")}
                value={building.embedding_model}
              />
              <Field
                label={t("building.state")}
                value={t(`building.states.${building.state}`)}
              />
              {startedAt ? (
                <Field label={t("building.startedAt")} value={startedAt} />
              ) : null}
            </dl>
            <div>
              <div className="mb-1 flex justify-between text-xs text-[#68647b]">
                <span>{t("building.progressLabel")}</span>
                <span>
                  {t("building.progressValue", {
                    done: progress?.documents_done ?? 0,
                    total: progress?.documents_total ?? 0,
                    percent,
                  })}
                </span>
              </div>
              <div
                role="progressbar"
                aria-label={t("building.progressLabel")}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent}
                className="h-2 w-full overflow-hidden rounded-full bg-[#ece9f8]"
              >
                <div
                  className="h-full rounded-full bg-[#5d58a8] transition-all"
                  style={{ width: `${percent}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-[#68647b]">
                {t("building.servingNote")}
              </p>
            </div>
          </div>
        ) : (
          <EmptyState
            compact
            title={t("building.noneTitle")}
            description={t("building.noneDescription")}
          />
        )}
      </article>
    </div>
  );
}

export function AdminVectorIndexPage() {
  const t = useTranslations("adminVectorIndex");
  const { state } = useAuthSession();
  const isAdminUser = canViewAdminUsage(state.session?.role);

  const statusInterval = useRealtimeAwareInterval(
    (query: {
      state: { data?: Parameters<typeof vectorIndexRefetchInterval>[0] };
    }) => vectorIndexRefetchInterval(query.state.data),
    { covered: false },
  );
  const statusQuery = useQuery({
    queryKey: queryKeys.admin.vectorIndexStatus,
    queryFn: getVectorIndexStatus,
    enabled: isAdminUser,
    refetchInterval: statusInterval,
    refetchIntervalInBackground: false,
  });

  const error = statusQuery.error;
  const forbidden =
    !isAdminUser || (isApiClientError(error) && error.status === 403);

  if (forbidden) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("access.restrictedTitle")}
          description={t("access.restrictedDescription")}
          requestId={error ? extractRequestIdFromError(error) : null}
          compact={false}
        />
      </section>
    );
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {t("header.eyebrow")}
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          {t("header.title")}
        </h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          {t("header.description")}
        </p>
      </header>

      {statusQuery.isLoading ? (
        <LoadingState compact title={t("states.loading")} />
      ) : error ? (
        <ErrorState
          title={t("states.errorTitle")}
          error={error}
          onRetry={() => void statusQuery.refetch()}
          retryLabel={t("states.retry")}
        />
      ) : statusQuery.data ? (
        <StatusCard status={statusQuery.data} />
      ) : (
        <EmptyState title={t("states.emptyTitle")} />
      )}
    </section>
  );
}
