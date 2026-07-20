"use client";

import { useState } from "react";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  getModelProviderDiagnostics,
  testModelProviderConnection,
  type CapabilitySummary,
  type ProviderCard,
  type ProviderTestStatus,
  type TestProviderResponse,
} from "@/lib/api/model-provider-diagnostics";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

const STATUS_COLORS: Record<ProviderTestStatus, string> = {
  ok: "bg-emerald-100 text-emerald-800",
  configuration_error: "bg-amber-100 text-amber-800",
  unknown_provider: "bg-red-100 text-red-800",
  unreachable: "bg-red-100 text-red-800",
  timeout: "bg-orange-100 text-orange-800",
  error: "bg-red-100 text-red-800",
};

function CapabilityBadges({ cap }: { cap: CapabilitySummary }) {
  const t = useTranslations("adminModelDiagnostics");
  const badges: { label: string; active: boolean }[] = [
    { label: t("capabilities.jsonMode"), active: cap.supports_json_mode },
    { label: t("capabilities.toolCalling"), active: cap.supports_tool_calling },
    { label: t("capabilities.streaming"), active: cap.supports_streaming },
    { label: t("capabilities.embedding"), active: cap.is_embedding_model },
  ];

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {badges.map(({ label, active }) => (
        <span
          key={label}
          className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
            active
              ? "bg-indigo-100 text-indigo-700"
              : "bg-gray-100 text-gray-400 line-through"
          }`}
        >
          {label}
        </span>
      ))}
      {cap.embedding_dimension != null && (
        <span className="inline-flex items-center rounded bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
          {cap.embedding_dimension}d
        </span>
      )}
      {cap.context_window != null && (
        <span className="inline-flex items-center rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
          {t("contextWindow", {
            count: (cap.context_window / 1000).toFixed(0),
          })}
        </span>
      )}
    </div>
  );
}

type TestResultPanelProps = {
  result: TestProviderResponse;
};

function TestResultPanel({ result }: TestResultPanelProps) {
  const t = useTranslations("adminModelDiagnostics");
  const statusClass =
    STATUS_COLORS[result.status] ?? "bg-gray-100 text-gray-700";
  const statusLabel = t(`statuses.${result.status}`);

  return (
    <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
      <div className="flex items-center gap-2">
        <span
          className={`rounded px-2 py-0.5 text-xs font-bold ${statusClass}`}
        >
          {statusLabel}
        </span>
        {result.latency_ms != null && (
          <span className="text-xs text-gray-500">{result.latency_ms} ms</span>
        )}
      </div>
      {result.error_message && (
        <p className="mt-1.5 text-xs text-red-700">{result.error_message}</p>
      )}
    </div>
  );
}

type ProviderCardProps = {
  card: ProviderCard;
  isAdmin: boolean;
  testResult: TestProviderResponse | null;
  isTesting: boolean;
  onTest: (providerKey: "chat" | "embeddings") => void;
};

function ProviderCardPanel({
  card,
  isAdmin,
  testResult,
  isTesting,
  onTest,
}: ProviderCardProps) {
  const t = useTranslations("adminModelDiagnostics");
  const title =
    card.provider_key === "chat"
      ? t("generation")
      : card.provider_key === "embeddings"
        ? t("embeddings")
        : card.provider_key;

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            {t("providerHeading", { name: title })}
          </p>
          <h2 className="mt-0.5 text-lg font-bold text-[#2a2640]">
            {card.model_name || "—"}
          </h2>
          <p className="text-sm text-[#68647b]">{card.provider_type}</p>
        </div>
        <span
          className={`mt-0.5 rounded-full px-3 py-1 text-xs font-bold ${
            card.is_configured
              ? "bg-emerald-100 text-emerald-800"
              : "bg-amber-100 text-amber-800"
          }`}
        >
          {card.is_configured ? t("configured") : t("notConfigured")}
        </span>
      </div>

      <div className="mt-3">
        <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {t("taskAssignments")}
        </p>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {card.task_assignments.map((task) => (
            <span
              key={task}
              className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700"
            >
              {task}
            </span>
          ))}
        </div>
      </div>

      {card.capability != null && (
        <div className="mt-3">
          <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {t("capabilitiesTitle")}
          </p>
          <CapabilityBadges cap={card.capability} />
        </div>
      )}

      {card.reindex_required && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {t("reindexWarning")}
        </div>
      )}

      {!card.is_configured && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {t("credentialsWarning")}
        </div>
      )}

      {isAdmin && (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => onTest(card.provider_key as "chat" | "embeddings")}
            disabled={isTesting}
            className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f8f6ff] disabled:opacity-60"
          >
            {isTesting ? t("testing") : t("testConnection")}
          </button>
          {testResult != null && <TestResultPanel result={testResult} />}
        </div>
      )}
    </div>
  );
}

export function AdminModelDiagnosticsPage() {
  const t = useTranslations("adminModelDiagnostics");
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAuthenticated = state.status === "authenticated";
  const isAdmin = canViewAdminUsage(role);

  const [testResults, setTestResults] = useState<
    Partial<Record<string, TestProviderResponse>>
  >({});
  const [testingKey, setTestingKey] = useState<string | null>(null);

  const diagnosticsQuery = useQuery({
    queryKey: queryKeys.modelProviderDiagnostics.providers,
    queryFn: () => getModelProviderDiagnostics(),
    enabled: isAuthenticated,
  });

  const testMutation = useMutation({
    mutationFn: (providerKey: "chat" | "embeddings") =>
      testModelProviderConnection({ provider_key: providerKey }),
  });

  async function handleTest(providerKey: "chat" | "embeddings") {
    setTestingKey(providerKey);
    try {
      const result = await testMutation.mutateAsync(providerKey);
      setTestResults((prev) => ({ ...prev, [providerKey]: result }));
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [providerKey]: {
          provider_key: providerKey,
          provider_type: "",
          model_name: "",
          status: "error",
          latency_ms: null,
          error_code: "error",
          error_message: getApiErrorMessage(err),
        },
      }));
    } finally {
      setTestingKey(null);
    }
  }

  if (!isAuthenticated) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("restricted")}
          description={t("restrictedDescription")}
          compact={false}
        />
      </section>
    );
  }

  const forbiddenError =
    diagnosticsQuery.isError &&
    isForbiddenError(diagnosticsQuery.error) &&
    diagnosticsQuery.error;

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("unavailable")}
          description={t("unavailableDescription")}
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  if (diagnosticsQuery.isLoading) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <LoadingState
          title={t("loading")}
          description={t("loadingDescription")}
          compact={false}
        />
      </section>
    );
  }

  if (diagnosticsQuery.isError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ErrorState
          title={t("loadError")}
          description={getApiErrorMessage(diagnosticsQuery.error)}
          compact={false}
          requestId={extractRequestIdFromError(diagnosticsQuery.error)}
          onRetry={() => diagnosticsQuery.refetch()}
        />
      </section>
    );
  }

  const providers = diagnosticsQuery.data?.providers ?? [];

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {t("eyebrow")}
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          {t("title")}
        </h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          {t("description")}
          {isAdmin ? ` ${t("adminDescription")}` : ""}
        </p>
      </header>

      {providers.length === 0 ? (
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-[#68647b]">{t("empty")}</p>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          {providers.map((card) => (
            <ProviderCardPanel
              key={card.provider_key}
              card={card}
              isAdmin={isAdmin}
              testResult={testResults[card.provider_key] ?? null}
              isTesting={testingKey === card.provider_key}
              onTest={handleTest}
            />
          ))}
        </div>
      )}
    </section>
  );
}
