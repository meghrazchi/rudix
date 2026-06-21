"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getFreshnessThresholds,
  patchFreshnessThresholds,
  type FreshnessThresholdsResponse,
} from "@/lib/api/freshness-thresholds";
import { isForbiddenError } from "@/lib/forbidden";

const QUERY_KEY = ["admin", "freshness-thresholds"] as const;

function DaysInput({
  id,
  label,
  description,
  value,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  description: string;
  value: number | null;
  onChange: (v: number | null) => void;
  disabled: boolean;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-semibold text-[#2a2640]" htmlFor={id}>
        {label}
      </label>
      <p className="mb-2 text-xs text-[#6b6895]">{description}</p>
      <input
        id={id}
        type="number"
        min={1}
        max={3650}
        disabled={disabled}
        placeholder="Use system default"
        value={value ?? ""}
        onChange={(e) => {
          const raw = e.target.value;
          if (!raw) {
            onChange(null);
          } else {
            const n = parseInt(raw, 10);
            if (!Number.isNaN(n) && n >= 1 && n <= 3650) onChange(n);
          }
        }}
        className="w-40 rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm text-[#2a2640] focus:ring-2 focus:ring-[#5d58a8] focus:outline-none disabled:opacity-50"
      />
    </div>
  );
}

function Toggle({
  id,
  label,
  description,
  value,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  description: string;
  value: boolean;
  onChange: (v: boolean) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={value}
        disabled={disabled}
        onClick={() => onChange(!value)}
        className={`relative mt-0.5 inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus:ring-2 focus:ring-[#5d58a8] focus:outline-none disabled:opacity-50 ${
          value ? "bg-[#3525cd]" : "bg-[#d7d4e8]"
        }`}
      >
        <span
          className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
            value ? "translate-x-4" : "translate-x-0"
          }`}
        />
      </button>
      <div>
        <label htmlFor={id} className="block text-sm font-semibold text-[#2a2640] cursor-pointer">
          {label}
        </label>
        <p className="text-xs text-[#6b6895]">{description}</p>
      </div>
    </div>
  );
}

function PolicyForm({
  initial,
  onSaved,
}: {
  initial: FreshnessThresholdsResponse;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();

  const [warnStaleAfterDays, setWarnStaleAfterDays] = useState<number | null>(
    initial.warn_stale_after_days,
  );
  const [warnUnreviewedAfterDays, setWarnUnreviewedAfterDays] = useState<number | null>(
    initial.warn_unreviewed_after_days,
  );
  const [autoExcludeDeprecated, setAutoExcludeDeprecated] = useState(
    initial.auto_exclude_deprecated,
  );
  const [autoExcludeExpired, setAutoExcludeExpired] = useState(
    initial.auto_exclude_expired,
  );
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const mutation = useMutation({
    mutationFn: patchFreshnessThresholds,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setSaved(true);
      setSaveError(null);
      setTimeout(() => setSaved(false), 3000);
      onSaved();
    },
    onError: (err: unknown) => {
      setSaveError(getApiErrorMessage(err) ?? "Failed to save thresholds.");
    },
  });

  const isDirty =
    warnStaleAfterDays !== initial.warn_stale_after_days ||
    warnUnreviewedAfterDays !== initial.warn_unreviewed_after_days ||
    autoExcludeDeprecated !== initial.auto_exclude_deprecated ||
    autoExcludeExpired !== initial.auto_exclude_expired;

  function handleSave() {
    setSaveError(null);
    setSaved(false);
    mutation.mutate({
      warn_stale_after_days: warnStaleAfterDays,
      warn_unreviewed_after_days: warnUnreviewedAfterDays,
      auto_exclude_deprecated: autoExcludeDeprecated,
      auto_exclude_expired: autoExcludeExpired,
    });
  }

  const isSaving = mutation.isPending;

  return (
    <form
      data-testid="freshness-threshold-form"
      onSubmit={(e) => {
        e.preventDefault();
        handleSave();
      }}
      className="space-y-6"
    >
      {/* Stale warning threshold */}
      <section className="space-y-4 rounded-xl border border-[#d7d4e8] bg-white p-5">
        <h2 className="text-sm font-bold text-[#2a2640]">Staleness thresholds</h2>
        <DaysInput
          id="warn-stale-days"
          label="Warn stale after (days)"
          description="Days without a review before a document is shown with a 'Stale' warning in answer trust panels. Leave blank to use per-document settings or the system default (90 days)."
          value={warnStaleAfterDays}
          onChange={setWarnStaleAfterDays}
          disabled={isSaving}
        />
        <DaysInput
          id="warn-unreviewed-days"
          label="Warn unreviewed after (days)"
          description="Days since last review before an 'Unreviewed' warning fires on answers citing that document. Leave blank for the system default (180 days)."
          value={warnUnreviewedAfterDays}
          onChange={setWarnUnreviewedAfterDays}
          disabled={isSaving}
        />
      </section>

      {/* Exclusion policy */}
      <section className="space-y-4 rounded-xl border border-[#d7d4e8] bg-white p-5">
        <h2 className="text-sm font-bold text-[#2a2640]">Retrieval exclusion policy</h2>
        <Toggle
          id="auto-exclude-deprecated"
          label="Exclude deprecated sources from retrieval"
          description="When enabled, deprecated, archived, and superseded documents are removed from retrieved evidence. When all sources are excluded, the system falls back with a warning."
          value={autoExcludeDeprecated}
          onChange={setAutoExcludeDeprecated}
          disabled={isSaving}
        />
        <Toggle
          id="auto-exclude-expired"
          label="Exclude expired sources from retrieval"
          description="When enabled, documents past their expiry date are removed from retrieved evidence."
          value={autoExcludeExpired}
          onChange={setAutoExcludeExpired}
          disabled={isSaving}
        />
      </section>

      {saveError ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700"
        >
          {saveError}
        </p>
      ) : null}

      {saved ? (
        <p
          role="status"
          className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-700"
        >
          Freshness thresholds saved.
        </p>
      ) : null}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!isDirty || isSaving}
          className="rounded-lg bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[#2a1faa] focus:ring-2 focus:ring-[#5d58a8] focus:ring-offset-2 focus:outline-none disabled:opacity-40"
          data-testid="save-freshness-thresholds"
        >
          {isSaving ? "Saving…" : "Save thresholds"}
        </button>
        {initial.updated_at ? (
          <span className="text-xs text-[#9d98b5]">
            Last updated{" "}
            {new Date(initial.updated_at).toLocaleDateString(undefined, {
              year: "numeric",
              month: "short",
              day: "numeric",
            })}
          </span>
        ) : (
          <span className="text-xs text-[#9d98b5]">No overrides set — using defaults</span>
        )}
      </div>
    </form>
  );
}

export function AdminFreshnessThresholdPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: getFreshnessThresholds,
    staleTime: 30_000,
  });

  if (isLoading) return <LoadingState />;
  if (isForbiddenError(error)) return <ForbiddenState />;
  if (error || !data) return <ErrorState message={getApiErrorMessage(error) ?? undefined} />;

  return (
    <div className="mx-auto max-w-2xl space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-bold text-[#1b1b24]">Source Freshness Thresholds</h1>
        <p className="mt-1 text-sm text-[#6b6895]">
          Configure when answer trust panels show freshness warnings and which sources are
          excluded from retrieval by default. These settings apply to all answers in your
          organisation and override per-document thresholds where set.
        </p>
      </div>

      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <strong>Note:</strong> Changes take effect immediately for new chat answers. Existing
        saved trust-metadata snapshots are not retroactively updated.
      </div>

      <PolicyForm initial={data} onSaved={() => {}} />
    </div>
  );
}
