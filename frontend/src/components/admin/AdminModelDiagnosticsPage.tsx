"use client";

import { useState } from "react";

import { useMutation, useQuery } from "@tanstack/react-query";

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

const PROVIDER_KEY_LABELS: Record<string, string> = {
  chat: "Generation",
  embeddings: "Embeddings",
};

const STATUS_COLORS: Record<ProviderTestStatus, string> = {
  ok: "bg-emerald-100 text-emerald-800",
  configuration_error: "bg-amber-100 text-amber-800",
  unknown_provider: "bg-red-100 text-red-800",
  unreachable: "bg-red-100 text-red-800",
  timeout: "bg-orange-100 text-orange-800",
  error: "bg-red-100 text-red-800",
};

const STATUS_LABELS: Record<ProviderTestStatus, string> = {
  ok: "Connected",
  configuration_error: "Not configured",
  unknown_provider: "Unknown provider",
  unreachable: "Unreachable",
  timeout: "Timed out",
  error: "Error",
};

function CapabilityBadges({ cap }: { cap: CapabilitySummary }) {
  const badges: { label: string; active: boolean }[] = [
    { label: "JSON mode", active: cap.supports_json_mode },
    { label: "Tool calling", active: cap.supports_tool_calling },
    { label: "Streaming", active: cap.supports_streaming },
    { label: "Embedding", active: cap.is_embedding_model },
  ];

  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
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
        <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700">
          {cap.embedding_dimension}d
        </span>
      )}
      {cap.context_window != null && (
        <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-blue-50 text-blue-700">
          {(cap.context_window / 1000).toFixed(0)}k ctx
        </span>
      )}
    </div>
  );
}

type TestResultPanelProps = {
  result: TestProviderResponse;
};

function TestResultPanel({ result }: TestResultPanelProps) {
  const statusClass = STATUS_COLORS[result.status] ?? "bg-gray-100 text-gray-700";
  const statusLabel = STATUS_LABELS[result.status] ?? result.status;

  return (
    <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
      <div className="flex items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-bold ${statusClass}`}>
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
  const title = PROVIDER_KEY_LABELS[card.provider_key] ?? card.provider_key;

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            {title} provider
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
          {card.is_configured ? "Configured" : "Not configured"}
        </span>
      </div>

      <div className="mt-3">
        <p className="text-xs font-semibold text-[#6a6780] uppercase tracking-wide">
          Task assignments
        </p>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {card.task_assignments.map((task) => (
            <span
              key={task}
              className="rounded px-2 py-0.5 text-xs font-medium bg-slate-100 text-slate-700"
            >
              {task}
            </span>
          ))}
        </div>
      </div>

      {card.capability != null && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-[#6a6780] uppercase tracking-wide">
            Capabilities
          </p>
          <CapabilityBadges cap={card.capability} />
        </div>
      )}

      {card.reindex_required && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Embedding model dimension does not match the configured vector store
          size. A full re-index is required before this model can be used.
        </div>
      )}

      {!card.is_configured && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Provider credentials are not set in the deployment environment. LLM
          calls will fail until the required environment variables are
          configured.
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
            {isTesting ? "Testing…" : "Test connection"}
          </button>
          {testResult != null && <TestResultPanel result={testResult} />}
        </div>
      )}
    </div>
  );
}

export function AdminModelDiagnosticsPage() {
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
          title="Model diagnostics restricted"
          description="You must be signed in to view model provider diagnostics."
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
          title="Model diagnostics unavailable"
          description="Your role does not have access to model provider diagnostics."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  if (diagnosticsQuery.isLoading) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <LoadingState
          title="Loading provider diagnostics"
          description="Fetching model provider configuration."
          compact={false}
        />
      </section>
    );
  }

  if (diagnosticsQuery.isError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ErrorState
          title="Unable to load provider diagnostics"
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
          Rudix Admin
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          Model provider diagnostics
        </h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          Verify that generation and embedding providers are configured and
          reachable. API keys and base URLs are never displayed here.
          {isAdmin
            ? " Use Test connection to run a live connectivity probe."
            : ""}
        </p>
      </header>

      {providers.length === 0 ? (
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-[#68647b]">No provider configuration found.</p>
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
