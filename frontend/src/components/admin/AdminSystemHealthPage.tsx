"use client";

import { useQuery } from "@tanstack/react-query";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { getHealth, getReadiness } from "@/lib/api/health";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { useAuthSession } from "@/lib/use-auth-session";

type HealthPanelProps = {
  title: string;
  loading: boolean;
  status: string | null;
  failedDependencies: string[];
  error: string | null;
  onRetry: () => void;
};

function HealthPanel({
  title,
  loading,
  status,
  failedDependencies,
  error,
  onRetry,
}: HealthPanelProps) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
      {loading ? <p className="mt-2 text-sm text-[#68647b]">Loading health status...</p> : null}
      {!loading && error ? (
        <div className="mt-2 space-y-2">
          <p className="text-sm text-rose-700">{error}</p>
          <button
            type="button"
            onClick={onRetry}
            className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-50"
          >
            Retry
          </button>
        </div>
      ) : null}
      {!loading && !error ? (
        <div className="mt-3 space-y-2 text-sm text-[#4d4963]">
          <p>
            Status:{" "}
            <span className="font-semibold uppercase tracking-wide text-[#2a2640]">{status ?? "unknown"}</span>
          </p>
          {failedDependencies.length > 0 ? (
            <p>
              Failed dependencies:{" "}
              <span className="font-semibold text-rose-700">{failedDependencies.join(", ")}</span>
            </p>
          ) : (
            <p className="text-emerald-700">All reported dependencies are healthy.</p>
          )}
        </div>
      ) : null}
    </article>
  );
}

export function AdminSystemHealthPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);

  const healthQuery = useQuery({
    queryKey: queryKeys.health.status,
    queryFn: getHealth,
    enabled: isAdminUser,
  });

  const readinessQuery = useQuery({
    queryKey: queryKeys.health.readiness,
    queryFn: getReadiness,
    enabled: isAdminUser,
  });

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin health restricted"
          description="Only owner and admin roles can access system health."
          compact={false}
        />
      </section>
    );
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Admin</p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">System health</h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          Validate runtime and readiness checks from the active backend deployment.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <HealthPanel
          title="API health"
          loading={healthQuery.isLoading}
          status={healthQuery.data?.status ?? null}
          failedDependencies={healthQuery.data?.failed_dependencies ?? []}
          error={healthQuery.isError ? getApiErrorMessage(healthQuery.error) : null}
          onRetry={() => {
            void healthQuery.refetch();
          }}
        />
        <HealthPanel
          title="Readiness"
          loading={readinessQuery.isLoading}
          status={readinessQuery.data?.status ?? null}
          failedDependencies={readinessQuery.data?.failed_dependencies ?? []}
          error={readinessQuery.isError ? getApiErrorMessage(readinessQuery.error) : null}
          onRetry={() => {
            void readinessQuery.refetch();
          }}
        />
      </div>
    </section>
  );
}
