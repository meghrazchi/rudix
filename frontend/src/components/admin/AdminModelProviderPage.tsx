"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  getEffectiveModelProviderPolicy,
  getModelProviderSettings,
  listModelProviderChangeLog,
  resetModelProviderSettings,
  type UpdateModelProviderSettingsRequest,
  updateModelProviderSettings,
} from "@/lib/api/model-provider-settings";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

type DraftSettings = {
  provider: string;
  llm_model: string;
  embedding_model: string;
  max_tokens: string;
  timeout_seconds: string;
  max_retries: string;
  fallback_model: string;
  disabled_models: string;
  change_note: string;
};

const EMPTY_DRAFT: DraftSettings = {
  provider: "",
  llm_model: "",
  embedding_model: "",
  max_tokens: "",
  timeout_seconds: "",
  max_retries: "",
  fallback_model: "",
  disabled_models: "",
  change_note: "",
};

function parseOptionalInt(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseCommaList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function formatCommaList(values: string[]): string {
  return values.join(", ");
}

export function AdminModelProviderPage() {
  const t = useTranslations("adminModelProvider");
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);

  const [draft, setDraft] = useState<DraftSettings | null>(null);
  const [resetNote, setResetNote] = useState("");
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  const settingsQuery = useQuery({
    queryKey: queryKeys.modelProviderSettings.settings,
    queryFn: () => getModelProviderSettings(),
    enabled: isAdminUser,
    retry: (count, err) => {
      // Don't retry 404 — it simply means no org settings exist yet
      if (
        typeof err === "object" &&
        err !== null &&
        "status" in err &&
        (err as { status: number }).status === 404
      ) {
        return false;
      }
      return count < 2;
    },
  });

  const effectivePolicyQuery = useQuery({
    queryKey: queryKeys.modelProviderSettings.effectivePolicy,
    queryFn: () => getEffectiveModelProviderPolicy(),
    enabled: isAdminUser,
  });

  const changeLogQuery = useQuery({
    queryKey: queryKeys.modelProviderSettings.changeLog(),
    queryFn: () => listModelProviderChangeLog({ limit: 10 }),
    enabled: isAdminUser,
  });

  const updateMutation = useMutation({
    mutationFn: (payload: UpdateModelProviderSettingsRequest) =>
      updateModelProviderSettings(payload),
    onSuccess: () => {
      setDraft(null);
      queryClient.invalidateQueries({
        queryKey: queryKeys.modelProviderSettings.all,
      });
    },
  });

  const resetMutation = useMutation({
    mutationFn: (note: string) => resetModelProviderSettings(note || undefined),
    onSuccess: () => {
      setShowResetConfirm(false);
      setResetNote("");
      queryClient.invalidateQueries({
        queryKey: queryKeys.modelProviderSettings.all,
      });
    },
  });

  const forbiddenError =
    effectivePolicyQuery.isError &&
    isForbiddenError(effectivePolicyQuery.error) &&
    effectivePolicyQuery.error;

  if (!isAdminUser) {
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

  if (effectivePolicyQuery.isLoading) {
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

  if (effectivePolicyQuery.isError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ErrorState
          title={t("loadError")}
          description={getApiErrorMessage(effectivePolicyQuery.error)}
          compact={false}
          requestId={extractRequestIdFromError(effectivePolicyQuery.error)}
          onRetry={() => effectivePolicyQuery.refetch()}
        />
      </section>
    );
  }

  const effectivePolicy = effectivePolicyQuery.data;
  const existingSettings = settingsQuery.data ?? null;
  const updateError = updateMutation.error
    ? getApiErrorMessage(updateMutation.error)
    : null;
  const resetError = resetMutation.error
    ? getApiErrorMessage(resetMutation.error)
    : null;

  // Initialise draft from existing settings or blank
  function openEditor() {
    if (existingSettings) {
      setDraft({
        provider: existingSettings.provider ?? "",
        llm_model: existingSettings.llm_model ?? "",
        embedding_model: existingSettings.embedding_model ?? "",
        max_tokens:
          existingSettings.max_tokens != null
            ? String(existingSettings.max_tokens)
            : "",
        timeout_seconds:
          existingSettings.timeout_seconds != null
            ? String(existingSettings.timeout_seconds)
            : "",
        max_retries:
          existingSettings.max_retries != null
            ? String(existingSettings.max_retries)
            : "",
        fallback_model: existingSettings.fallback_model ?? "",
        disabled_models: formatCommaList(existingSettings.disabled_models),
        change_note: "",
      });
    } else {
      setDraft({ ...EMPTY_DRAFT });
    }
  }

  function handleSave() {
    if (!draft) return;
    const payload: UpdateModelProviderSettingsRequest = {};
    if (draft.provider.trim()) payload.provider = draft.provider.trim();
    if (draft.llm_model.trim()) payload.llm_model = draft.llm_model.trim();
    if (draft.embedding_model.trim())
      payload.embedding_model = draft.embedding_model.trim();
    const maxTokens = parseOptionalInt(draft.max_tokens);
    if (maxTokens !== null) payload.max_tokens = maxTokens;
    const timeout = parseOptionalInt(draft.timeout_seconds);
    if (timeout !== null) payload.timeout_seconds = timeout;
    const retries = parseOptionalInt(draft.max_retries);
    if (retries !== null) payload.max_retries = retries;
    if (draft.fallback_model.trim())
      payload.fallback_model = draft.fallback_model.trim();
    payload.disabled_models = parseCommaList(draft.disabled_models);
    if (draft.change_note.trim())
      payload.change_note = draft.change_note.trim();
    updateMutation.mutate(payload);
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {t("eyebrow")}
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          {t("title")}
        </h1>
        <p className="max-w-3xl text-sm text-[#68647b]">{t("description")}</p>
      </header>

      {/* Effective policy summary */}
      {effectivePolicy ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-lg font-bold text-[#2a2640]">
              {t("effectivePolicy")}
            </h2>
            <span
              className={`rounded-full px-3 py-1 text-xs font-bold ${
                effectivePolicy.source === "org_override"
                  ? "bg-indigo-100 text-indigo-800"
                  : "bg-slate-100 text-slate-600"
              }`}
            >
              {effectivePolicy.source === "org_override"
                ? t("orgOverride")
                : t("systemDefault")}
            </span>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
            <PolicyField
              label={t("fields.provider")}
              value={effectivePolicy.provider}
            />
            <PolicyField
              label={t("fields.llmModel")}
              value={effectivePolicy.llm_model}
            />
            <PolicyField
              label={t("fields.embeddingModel")}
              value={effectivePolicy.embedding_model}
            />
            <PolicyField
              label={t("fields.maxTokens")}
              value={
                effectivePolicy.max_tokens != null
                  ? String(effectivePolicy.max_tokens)
                  : "—"
              }
            />
            <PolicyField
              label={t("fields.timeout")}
              value={String(effectivePolicy.timeout_seconds)}
            />
            <PolicyField
              label={t("fields.maxRetries")}
              value={String(effectivePolicy.max_retries)}
            />
            <PolicyField
              label={t("fields.fallbackModel")}
              value={effectivePolicy.fallback_model ?? "—"}
            />
            <PolicyField
              label={t("fields.disabledModels")}
              value={
                effectivePolicy.disabled_models.length > 0
                  ? effectivePolicy.disabled_models.join(", ")
                  : "—"
              }
            />
            <PolicyField
              label={t("fields.keyConfigured")}
              value={effectivePolicy.llm_key_configured ? t("yes") : t("no")}
              highlight={
                effectivePolicy.llm_key_configured ? "success" : "warning"
              }
            />
          </dl>
          {!effectivePolicy.llm_key_configured ? (
            <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {t("missingKeyWarning")}
            </p>
          ) : null}
        </section>
      ) : null}

      {/* Edit / create org overrides */}
      {draft === null ? (
        <div className="flex gap-3">
          <button
            type="button"
            onClick={openEditor}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            {existingSettings ? t("editOverrides") : t("createOverrides")}
          </button>
          {existingSettings ? (
            <button
              type="button"
              onClick={() => setShowResetConfirm(true)}
              className="rounded-lg border border-rose-200 px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50"
            >
              {t("resetDefaults")}
            </button>
          ) : null}
        </div>
      ) : (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">
            {existingSettings ? t("editOverrides") : t("createOverrides")}
          </h2>
          <p className="mt-1 text-sm text-[#68647b]">
            {t("editorDescription")}
          </p>

          {updateError ? (
            <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
              {updateError}
            </div>
          ) : null}

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <SettingsInput
              label={t("fields.provider")}
              placeholder="openai"
              value={draft.provider}
              onChange={(v) => setDraft({ ...draft, provider: v })}
            />
            <SettingsInput
              label={t("fields.llmModel")}
              placeholder="gpt-4o"
              value={draft.llm_model}
              onChange={(v) => setDraft({ ...draft, llm_model: v })}
            />
            <SettingsInput
              label={t("fields.embeddingModel")}
              placeholder="text-embedding-3-small"
              value={draft.embedding_model}
              onChange={(v) => setDraft({ ...draft, embedding_model: v })}
            />
            <SettingsInput
              label={t("fields.maxTokensOptional")}
              placeholder="4096"
              value={draft.max_tokens}
              onChange={(v) => setDraft({ ...draft, max_tokens: v })}
            />
            <SettingsInput
              label={t("fields.timeoutOptional")}
              placeholder="30"
              value={draft.timeout_seconds}
              onChange={(v) => setDraft({ ...draft, timeout_seconds: v })}
            />
            <SettingsInput
              label={t("fields.maxRetriesOptional")}
              placeholder="2"
              value={draft.max_retries}
              onChange={(v) => setDraft({ ...draft, max_retries: v })}
            />
            <SettingsInput
              label={t("fields.fallbackOptional")}
              placeholder="gpt-3.5-turbo"
              value={draft.fallback_model}
              onChange={(v) => setDraft({ ...draft, fallback_model: v })}
            />
            <SettingsInput
              label={t("fields.disabledModelsComma")}
              placeholder="davinci, curie"
              value={draft.disabled_models}
              onChange={(v) => setDraft({ ...draft, disabled_models: v })}
            />
            <div className="sm:col-span-2">
              <SettingsInput
                label={t("fields.changeNote")}
                placeholder={t("changeNotePlaceholder")}
                value={draft.change_note}
                onChange={(v) => setDraft({ ...draft, change_note: v })}
              />
            </div>
          </div>

          <div className="mt-4 flex gap-3">
            <button
              type="button"
              onClick={handleSave}
              disabled={updateMutation.isPending}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:opacity-60"
            >
              {updateMutation.isPending ? t("saving") : t("saveSettings")}
            </button>
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f8f6ff]"
            >
              {t("cancel")}
            </button>
          </div>
        </section>
      )}

      {/* Reset confirmation */}
      {showResetConfirm ? (
        <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5">
          <h2 className="text-base font-bold text-rose-900">
            {t("resetTitle")}
          </h2>
          <p className="mt-1 text-sm text-rose-800">{t("resetDescription")}</p>
          {resetError ? (
            <p className="mt-2 text-sm text-rose-700">{resetError}</p>
          ) : null}
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              value={resetNote}
              onChange={(event) => setResetNote(event.target.value)}
              placeholder={t("resetReasonPlaceholder")}
              className="h-9 flex-1 rounded-lg border border-rose-200 bg-white px-3 text-sm"
            />
            <button
              type="button"
              onClick={() => resetMutation.mutate(resetNote)}
              disabled={resetMutation.isPending}
              className="rounded-lg bg-rose-700 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-800 disabled:opacity-60"
            >
              {resetMutation.isPending ? t("resetting") : t("confirmReset")}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowResetConfirm(false);
                setResetNote("");
              }}
              className="rounded-lg border border-rose-200 bg-white px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50"
            >
              {t("cancel")}
            </button>
          </div>
        </section>
      ) : null}

      {/* Change log */}
      {changeLogQuery.data && changeLogQuery.data.total > 0 ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-lg font-bold text-[#2a2640]">
              {t("changeHistory")}
            </h2>
            <span className="text-sm text-[#6a6780]">
              {t("entries", { count: changeLogQuery.data.total })}
            </span>
          </div>
          <div className="mt-3 divide-y divide-[#f0eeff]">
            {changeLogQuery.data.items.map((entry) => (
              <div
                key={entry.entry_id}
                className="flex flex-col gap-1 py-3 sm:flex-row sm:items-start sm:gap-4"
              >
                <span className="min-w-[6rem] text-xs font-semibold text-[#5d58a8]">
                  v{entry.version_number}
                </span>
                <div className="flex-1 text-sm">
                  {entry.change_note ? (
                    <p className="font-medium text-[#2a2640]">
                      {entry.change_note}
                    </p>
                  ) : null}
                  <p className="text-xs text-[#6a6780]">
                    {new Date(entry.created_at).toLocaleString()}
                    {entry.changed_by_id
                      ? ` · ${t("changedBy", { id: entry.changed_by_id })}`
                      : ""}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}

function PolicyField({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: "success" | "warning";
}) {
  return (
    <div>
      <dt className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </dt>
      <dd
        className={`mt-0.5 text-sm font-semibold ${
          highlight === "success"
            ? "text-emerald-700"
            : highlight === "warning"
              ? "text-amber-700"
              : "text-[#2a2640]"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function SettingsInput({
  label,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="h-9 rounded-lg border border-[#d2cee6] px-3 text-sm font-medium text-[#2a2640] placeholder:font-normal placeholder:text-[#b0aec6]"
      />
    </label>
  );
}
