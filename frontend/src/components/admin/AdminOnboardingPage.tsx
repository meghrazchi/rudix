"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getOnboardingConfig,
  patchOnboardingConfig,
  resetOnboarding,
} from "@/lib/api/onboarding";
import { ONBOARDING_QUERY_KEY } from "@/lib/onboarding";
import { getApiErrorMessage } from "@/lib/api/errors";
import { LoadingState } from "@/components/states/LoadingState";
import { ErrorState } from "@/components/states/ErrorState";

export function AdminOnboardingPage() {
  const queryClient = useQueryClient();

  const configQuery = useQuery({
    queryKey: ONBOARDING_QUERY_KEY,
    queryFn: getOnboardingConfig,
  });

  const patchMutation = useMutation({
    mutationFn: patchOnboardingConfig,
    onSuccess: (data) => {
      queryClient.setQueryData(ONBOARDING_QUERY_KEY, data);
    },
  });

  const resetMutation = useMutation({
    mutationFn: resetOnboarding,
    onSuccess: (data) => {
      queryClient.setQueryData(ONBOARDING_QUERY_KEY, data);
    },
  });

  if (configQuery.isLoading) {
    return <LoadingState />;
  }

  if (configQuery.isError) {
    return (
      <ErrorState
        error={configQuery.error}
        description={getApiErrorMessage(configQuery.error)}
        onRetry={() => void configQuery.refetch()}
      />
    );
  }

  const config = configQuery.data!;
  const resetAt = config.reset_at
    ? new Date(config.reset_at).toLocaleString()
    : null;

  function handleToggleSampleDocs() {
    patchMutation.mutate({
      sample_docs_enabled: !config.sample_docs_enabled,
    });
  }

  function handleReset() {
    if (
      !window.confirm(
        "Reset onboarding for all users in this organization? They will see the Getting Started checklist again on next load.",
      )
    ) {
      return;
    }
    resetMutation.mutate();
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8 px-4 py-8">
      <div>
        <h1 className="text-xl font-bold text-[#2a2640]">
          Onboarding Settings
        </h1>
        <p className="mt-1 text-sm text-[#6b6895]">
          Control the Getting Started checklist and sample dataset for this
          workspace.
        </p>
      </div>

      {/* Sample dataset toggle */}
      <section className="rounded-xl border border-[#e4e1f2] bg-white p-6">
        <h2 className="mb-1 text-base font-semibold text-[#2a2640]">
          Sample dataset
        </h2>
        <p className="mb-4 text-sm text-[#6b6895]">
          When enabled, new users can load pre-indexed sample documents from the
          Getting Started checklist without uploading files. Ideal for demo and
          evaluation workspaces.
        </p>
        <div className="flex items-center gap-3">
          <button
            type="button"
            role="switch"
            aria-checked={config.sample_docs_enabled}
            onClick={handleToggleSampleDocs}
            disabled={patchMutation.isPending}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none disabled:opacity-50 ${
              config.sample_docs_enabled ? "bg-[#3525cd]" : "bg-[#d7d4e8]"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
                config.sample_docs_enabled ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
          <span className="text-sm font-medium text-[#2a2640]">
            {config.sample_docs_enabled ? "Enabled" : "Disabled"}
          </span>
          {patchMutation.isError ? (
            <span className="text-xs text-rose-600">
              {getApiErrorMessage(patchMutation.error)}
            </span>
          ) : null}
        </div>
      </section>

      {/* Reset onboarding */}
      <section className="rounded-xl border border-[#e4e1f2] bg-white p-6">
        <h2 className="mb-1 text-base font-semibold text-[#2a2640]">
          Reset onboarding
        </h2>
        <p className="mb-1 text-sm text-[#6b6895]">
          Force all users in this organization to see the Getting Started
          checklist again on their next page load — useful after onboarding a
          new cohort or enabling new features.
        </p>
        {resetAt ? (
          <p className="mb-4 text-xs text-[#8b88a0]">Last reset: {resetAt}</p>
        ) : null}
        <button
          type="button"
          onClick={handleReset}
          disabled={resetMutation.isPending}
          className="rounded-lg border border-[#d7d4e8] bg-white px-4 py-2 text-sm font-semibold text-[#3525cd] transition hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {resetMutation.isPending
            ? "Resetting…"
            : "Reset onboarding for all users"}
        </button>
        {resetMutation.isError ? (
          <p className="mt-2 text-xs text-rose-600">
            {getApiErrorMessage(resetMutation.error)}
          </p>
        ) : null}
        {resetMutation.isSuccess ? (
          <p className="mt-2 text-xs text-emerald-600">
            Onboarding reset successfully. Users will see the checklist on next
            load.
          </p>
        ) : null}
      </section>
    </div>
  );
}
