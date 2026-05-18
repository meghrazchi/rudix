"use client";

import { useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { getHealth, getReadiness, type HealthDependency, type HealthResponse } from "@/lib/api/health";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { useAuthSession } from "@/lib/use-auth-session";

type DependencyKey = "postgresql" | "redis" | "rabbitmq" | "minio" | "qdrant" | "openai";
type DependencyState = "healthy" | "degraded" | "unavailable";

type DependencyDescriptor = {
  key: DependencyKey;
  label: string;
  aliases: string[];
};

const REFRESH_INTERVAL_MS = (() => {
  const raw = process.env.NEXT_PUBLIC_ADMIN_HEALTH_REFRESH_INTERVAL_MS?.trim();
  if (!raw) {
    return 0;
  }
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return parsed;
})();

const DEPENDENCY_DESCRIPTORS: DependencyDescriptor[] = [
  {
    key: "postgresql",
    label: "PostgreSQL",
    aliases: ["postgresql", "postgres", "database", "db"],
  },
  {
    key: "redis",
    label: "Redis",
    aliases: ["redis", "cache"],
  },
  {
    key: "rabbitmq",
    label: "RabbitMQ",
    aliases: ["rabbitmq", "rabbit", "queue", "broker"],
  },
  {
    key: "minio",
    label: "MinIO",
    aliases: ["minio", "object_storage", "storage", "blob"],
  },
  {
    key: "qdrant",
    label: "Qdrant",
    aliases: ["qdrant", "vector_store", "vector", "vectordb"],
  },
  {
    key: "openai",
    label: "OpenAI Config",
    aliases: ["openai", "openai_config", "llm", "provider", "openai_provider"],
  },
];

const SENSITIVE_METADATA_PATTERN = /(token|secret|key|password|credential|authorization|api)/i;

function sanitizeMetadataValue(value: unknown): string {
  if (value == null) {
    return "-";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value.toString() : "-";
  }
  if (typeof value !== "string") {
    return "[redacted]";
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return "-";
  }
  if (trimmed.length > 120) {
    return `${trimmed.slice(0, 117)}...`;
  }
  return trimmed;
}

function sanitizeDependencyMetadata(metadata: HealthDependency["metadata"]): Array<{ key: string; value: string }> {
  const entries = Object.entries(metadata ?? {});
  return entries
    .slice(0, 6)
    .map(([key, value]) => {
      if (SENSITIVE_METADATA_PATTERN.test(key)) {
        return { key, value: "[redacted]" };
      }
      return { key, value: sanitizeMetadataValue(value) };
    });
}

function dependencyCardClass(state: DependencyState): string {
  if (state === "healthy") {
    return "border-emerald-200 bg-emerald-50";
  }
  if (state === "degraded") {
    return "border-rose-200 bg-rose-50";
  }
  return "border-slate-200 bg-slate-50";
}

function dependencyBadgeClass(state: DependencyState): string {
  if (state === "healthy") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (state === "degraded") {
    return "bg-rose-100 text-rose-800";
  }
  return "bg-slate-200 text-slate-700";
}

function normalizeKey(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

function findDependencyFromResponse(
  response: HealthResponse | undefined,
  descriptor: DependencyDescriptor,
): HealthDependency | null {
  if (!response) {
    return null;
  }

  const dependencies = response.dependencies ?? {};
  const normalizedAliasSet = new Set(descriptor.aliases.map((alias) => normalizeKey(alias)));

  for (const [rawKey, dependency] of Object.entries(dependencies)) {
    if (normalizedAliasSet.has(normalizeKey(rawKey))) {
      return dependency;
    }
  }

  return null;
}

function resolveDependencyState(dependency: HealthDependency | null): DependencyState {
  if (!dependency) {
    return "unavailable";
  }
  return dependency.ok ? "healthy" : "degraded";
}

function statusBadgeClass(status: string | null | undefined): string {
  const normalized = status?.toLowerCase() ?? "unknown";
  if (normalized === "ok" || normalized === "healthy" || normalized === "ready") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (normalized === "degraded" || normalized === "error" || normalized === "failed") {
    return "bg-rose-100 text-rose-800";
  }
  return "bg-slate-200 text-slate-700";
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "N/A";
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return value;
  }
  return new Date(parsed).toLocaleString();
}

function formatRefreshIntervalLabel(intervalMs: number): string {
  if (intervalMs <= 0) {
    return "disabled";
  }
  const seconds = Math.round(intervalMs / 1000);
  return `${Math.max(1, seconds)}s`;
}

function HealthSection({
  title,
  response,
  isLoading,
  isError,
  error,
  onRetry,
}: {
  title: string;
  response: HealthResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  if (isLoading) {
    return (
      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
        <LoadingState
          compact
          className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
          title="Loading health status..."
        />
      </section>
    );
  }

  if (isError) {
    return (
      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
        <div className="mt-3">
          <ErrorState
            compact
            error={error}
            description={getApiErrorMessage(error)}
            onRetry={onRetry}
          />
        </div>
      </section>
    );
  }

  const failedDependencies = response?.failed_dependencies ?? [];

  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
        <span
          className={`rounded-full px-2 py-1 text-xs font-semibold uppercase tracking-wide ${statusBadgeClass(
            response?.status,
          )}`}
        >
          {response?.status ?? "unknown"}
        </span>
      </div>
      <p className="mt-2 text-xs text-[#6a6780]">Updated: {formatTimestamp(response?.timestamp)}</p>

      {failedDependencies.length > 0 ? (
        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          Failed dependencies: <span className="font-semibold">{failedDependencies.join(", ")}</span>
        </p>
      ) : (
        <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          All reported dependencies are healthy.
        </p>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {DEPENDENCY_DESCRIPTORS.map((descriptor) => {
          const dependency = findDependencyFromResponse(response, descriptor);
          const state = resolveDependencyState(dependency);
          const metadataEntries = dependency ? sanitizeDependencyMetadata(dependency.metadata) : [];

          return (
            <article
              key={descriptor.key}
              className={`rounded-xl border p-3 ${dependencyCardClass(state)}`}
              aria-label={`${descriptor.label} dependency card`}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-semibold text-[#2a2640]">{descriptor.label}</p>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${dependencyBadgeClass(
                    state,
                  )}`}
                >
                  {state}
                </span>
              </div>
              <p className="mt-2 text-xs text-[#4d4963]">
                {dependency?.detail?.trim() ? dependency.detail : state === "unavailable" ? "Not reported by backend." : "No detail provided."}
              </p>
              {metadataEntries.length > 0 ? (
                <dl className="mt-2 space-y-1 text-[11px] text-[#5f5b72]">
                  {metadataEntries.map((entry) => (
                    <div key={`${descriptor.key}:${entry.key}`} className="flex items-start justify-between gap-2">
                      <dt className="font-semibold">{entry.key}</dt>
                      <dd className="text-right">{entry.value}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function AdminSystemHealthPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);

  const refetchInterval = REFRESH_INTERVAL_MS > 0 ? REFRESH_INTERVAL_MS : (false as const);

  const healthQuery = useQuery<HealthResponse>({
    queryKey: queryKeys.health.status,
    queryFn: getHealth,
    enabled: isAdminUser,
    refetchInterval,
    refetchIntervalInBackground: REFRESH_INTERVAL_MS > 0,
  });

  const readinessQuery = useQuery<HealthResponse>({
    queryKey: queryKeys.health.readiness,
    queryFn: getReadiness,
    enabled: isAdminUser,
    refetchInterval,
    refetchIntervalInBackground: REFRESH_INTERVAL_MS > 0,
  });

  async function refreshAllChecks(): Promise<void> {
    await Promise.all([healthQuery.refetch(), readinessQuery.refetch()]);
  }

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
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Admin</p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">System health</h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Monitor API readiness and core dependency health for operations.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-lg border border-[#d2cee6] bg-[#faf9ff] px-2 py-1 text-xs font-semibold text-[#5f5a74]">
              Auto-refresh: {formatRefreshIntervalLabel(REFRESH_INTERVAL_MS)}
            </span>
            <button
              type="button"
              onClick={() => {
                void refreshAllChecks();
              }}
              disabled={healthQuery.isFetching || readinessQuery.isFetching}
              className="rounded-lg border border-[#cbc5e6] px-3 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {healthQuery.isFetching || readinessQuery.isFetching ? "Refreshing..." : "Refresh checks"}
            </button>
          </div>
        </div>
      </header>

      <div className="grid gap-4">
        <HealthSection
          title="API Health (/health)"
          response={healthQuery.data}
          isLoading={healthQuery.isLoading}
          isError={healthQuery.isError}
          error={healthQuery.error}
          onRetry={() => {
            void healthQuery.refetch();
          }}
        />
        <HealthSection
          title="Readiness (/ready)"
          response={readinessQuery.data}
          isLoading={readinessQuery.isLoading}
          isError={readinessQuery.isError}
          error={readinessQuery.error}
          onRetry={() => {
            void readinessQuery.refetch();
          }}
        />
      </div>
    </section>
  );
}
