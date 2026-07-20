"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  deleteSSOConfig,
  getSSOConfig,
  testSSOConnection,
  upsertSSOConfig,
  type SSOConfig,
  type TestConnectionResponse,
  type UpsertSSOConfigRequest,
} from "@/lib/api/sso";
import { getApiErrorMessage } from "@/lib/api/errors";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

type InputMode = "url" | "xml";

type Draft = {
  domain: string;
  sso_type: "saml" | "oidc";
  enabled: boolean;
  idp_metadata_url: string;
  idp_metadata_xml: string;
  idp_sso_url: string;
  idp_entity_id: string;
  change_note: string;
  input_mode: InputMode;
};

const EMPTY_DRAFT: Draft = {
  domain: "",
  sso_type: "saml",
  enabled: false,
  idp_metadata_url: "",
  idp_metadata_xml: "",
  idp_sso_url: "",
  idp_entity_id: "",
  change_note: "",
  input_mode: "url",
};

function configToDraft(config: SSOConfig): Draft {
  return {
    domain: config.domain,
    sso_type: config.sso_type,
    enabled: config.enabled,
    idp_metadata_url: config.idp_metadata_url ?? "",
    idp_metadata_xml: "",
    idp_sso_url: config.idp_sso_url ?? "",
    idp_entity_id: config.idp_entity_id ?? "",
    change_note: "",
    input_mode: config.idp_metadata_url ? "url" : "xml",
  };
}

function trimOrNull(value: string): string | null {
  const t = value.trim();
  return t.length > 0 ? t : null;
}

function getFallbackErrorMessage(error: unknown, fallback: string): string {
  const message = getApiErrorMessage(error);
  return message === "Something went wrong while contacting the API."
    ? fallback
    : message;
}

export function AdminSSOPage() {
  const t = useTranslations("adminSso");
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const role = state.session?.role;
  const isAdmin = canViewAdminUsage(role);
  const isOwner = role === "owner";

  const [draft, setDraft] = useState<Draft | null>(null);
  const [testResult, setTestResult] = useState<TestConnectionResponse | null>(
    null,
  );
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const ssoKey = ["sso-config"] as const;

  const configQuery = useQuery({
    queryKey: ssoKey,
    queryFn: getSSOConfig,
    enabled: isAdmin,
    retry: (count, err) => !isForbiddenError(err) && count < 2,
  });

  const upsertMutation = useMutation({
    mutationFn: (payload: UpsertSSOConfigRequest) => upsertSSOConfig(payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(ssoKey, updated);
      setDraft(null);
      setSubmitError(null);
    },
    onError: (err) => {
      setSubmitError(getFallbackErrorMessage(err, t("errors.saveFailed")));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSSOConfig,
    onSuccess: () => {
      queryClient.setQueryData(ssoKey, null);
      setShowDeleteConfirm(false);
      setDraft(null);
    },
    onError: (err) => {
      setSubmitError(getFallbackErrorMessage(err, t("errors.removeFailed")));
    },
  });

  const testMutation = useMutation({
    mutationFn: () =>
      testSSOConnection({
        idp_metadata_url: trimOrNull(draft?.idp_metadata_url ?? ""),
        idp_metadata_xml:
          draft?.input_mode === "xml"
            ? trimOrNull(draft?.idp_metadata_xml ?? "")
            : null,
        idp_sso_url: trimOrNull(draft?.idp_sso_url ?? ""),
      }),
    onSuccess: (result) => {
      setTestResult(result);
      queryClient.invalidateQueries({ queryKey: ssoKey });
    },
    onError: (err) => {
      setSubmitError(getFallbackErrorMessage(err, t("errors.testFailed")));
    },
  });

  if (!isAdmin)
    return (
      <ForbiddenState
        title={t("title")}
        description={t("errors.permissionRequired")}
      />
    );
  if (configQuery.isLoading) return <LoadingState />;
  if (configQuery.isError && isForbiddenError(configQuery.error))
    return (
      <ForbiddenState
        title={t("title")}
        description={t("errors.permissionRequired")}
      />
    );
  if (configQuery.isError)
    return (
      <ErrorState
        error={configQuery.error}
        description={t("errors.loadFailed")}
        onRetry={() => void configQuery.refetch()}
      />
    );

  const config = configQuery.data ?? null;
  const activeDraft = draft ?? (config ? configToDraft(config) : EMPTY_DRAFT);
  const isEditing = draft !== null;

  function handleEdit() {
    setDraft(config ? configToDraft(config) : { ...EMPTY_DRAFT });
    setSubmitError(null);
    setTestResult(null);
  }

  function handleCancel() {
    setDraft(null);
    setSubmitError(null);
    setTestResult(null);
  }

  function setField<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((prev) => ({ ...(prev ?? EMPTY_DRAFT), [key]: value }));
  }

  function handleSave() {
    if (!draft) return;
    const payload: UpsertSSOConfigRequest = {
      domain: draft.domain,
      sso_type: draft.sso_type,
      enabled: draft.enabled,
      idp_metadata_url:
        draft.input_mode === "url" ? trimOrNull(draft.idp_metadata_url) : null,
      idp_metadata_xml:
        draft.input_mode === "xml" ? trimOrNull(draft.idp_metadata_xml) : null,
      idp_sso_url: trimOrNull(draft.idp_sso_url),
      idp_entity_id: trimOrNull(draft.idp_entity_id),
      change_note: trimOrNull(draft.change_note),
    };
    upsertMutation.mutate(payload);
  }

  const isBusy =
    upsertMutation.isPending ||
    deleteMutation.isPending ||
    testMutation.isPending;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-[#2a2640]">{t("title")}</h1>
        <p className="mt-1 text-sm text-[#68647b]">{t("description")}</p>
      </div>

      {config && !isEditing ? (
        <SSOConfigReadView
          config={config}
          isOwner={isOwner}
          onEdit={handleEdit}
          onDeleteClick={() => setShowDeleteConfirm(true)}
        />
      ) : (
        <SSOConfigForm
          draft={activeDraft}
          isOwner={isOwner}
          isBusy={isBusy}
          submitError={submitError}
          testResult={testResult}
          onFieldChange={setField}
          onTest={() => testMutation.mutate()}
          onSave={handleSave}
          onCancel={config ? handleCancel : undefined}
        />
      )}

      {showDeleteConfirm ? (
        <DeleteConfirmModal
          isBusy={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate()}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      ) : null}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SSOConfigReadView({
  config,
  isOwner,
  onEdit,
  onDeleteClick,
}: {
  config: SSOConfig;
  isOwner: boolean;
  onEdit: () => void;
  onDeleteClick: () => void;
}) {
  const t = useTranslations("adminSso");
  return (
    <div className="space-y-4 rounded-xl border border-[#d7d4e8] bg-white p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
              config.enabled
                ? "bg-emerald-100 text-emerald-800"
                : "bg-slate-100 text-slate-600"
            }`}
          >
            {config.enabled ? t("statuses.enabled") : t("statuses.disabled")}
          </span>
          <span className="text-sm font-medium text-[#2a2640]">
            {config.domain}
          </span>
          <span className="text-xs tracking-wide text-[#a09cb8] uppercase">
            {config.sso_type}
          </span>
        </div>
        {isOwner ? (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onEdit}
              className="rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#3525cd] transition hover:bg-[#f5f3ff]"
            >
              {t("actions.edit")}
            </button>
            <button
              type="button"
              onClick={onDeleteClick}
              className="rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-semibold text-rose-600 transition hover:bg-rose-50"
            >
              {t("actions.remove")}
            </button>
          </div>
        ) : null}
      </div>

      <ReadField
        label={t("fields.spEntityId")}
        value={config.sp_entity_id}
        mono
      />
      <ReadField label={t("fields.acsUrl")} value={config.sp_acs_url} mono />
      {config.idp_metadata_url ? (
        <ReadField
          label={t("fields.idpMetadataUrl")}
          value={config.idp_metadata_url}
          mono
        />
      ) : null}
      {config.idp_sso_url ? (
        <ReadField
          label={t("fields.idpSsoUrl")}
          value={config.idp_sso_url}
          mono
        />
      ) : null}
      {config.idp_entity_id ? (
        <ReadField
          label={t("fields.idpEntityId")}
          value={config.idp_entity_id}
          mono
        />
      ) : null}

      {config.last_test_at ? (
        <div className="flex items-center gap-2 text-xs text-[#68647b]">
          <span>{t("lastTest.label")}</span>
          <span
            className={
              config.last_test_result === "success"
                ? "font-semibold text-emerald-700"
                : "font-semibold text-rose-700"
            }
          >
            {config.last_test_result === "success"
              ? t("lastTest.success")
              : t("lastTest.failure")}
          </span>
          <span>
            {t("lastTest.at", {
              date: new Date(config.last_test_at).toLocaleString(),
            })}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function ReadField({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  const t = useTranslations("adminSso");
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div>
      <p className="mb-0.5 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </p>
      <div className="flex items-center gap-2">
        <p
          className={`flex-1 rounded border border-[#e4e1f2] bg-[#f9f8ff] px-3 py-1.5 text-sm break-all text-[#2a2640] ${
            mono ? "font-mono text-xs" : ""
          }`}
        >
          {value}
        </p>
        <button
          type="button"
          onClick={handleCopy}
          className="shrink-0 rounded border border-[#d2cee6] px-2 py-1 text-xs text-[#5d58a8] transition hover:bg-[#f5f3ff]"
        >
          {copied ? t("actions.copied") : t("actions.copy")}
        </button>
      </div>
    </div>
  );
}

function SSOConfigForm({
  draft,
  isOwner,
  isBusy,
  submitError,
  testResult,
  onFieldChange,
  onTest,
  onSave,
  onCancel,
}: {
  draft: Draft;
  isOwner: boolean;
  isBusy: boolean;
  submitError: string | null;
  testResult: TestConnectionResponse | null;
  onFieldChange: <K extends keyof Draft>(key: K, value: Draft[K]) => void;
  onTest: () => void;
  onSave: () => void;
  onCancel?: () => void;
}) {
  const t = useTranslations("adminSso");
  return (
    <div className="space-y-5 rounded-xl border border-[#d7d4e8] bg-white p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField
          label={t("fields.emailDomain")}
          required
          hint={t("hints.emailDomain")}
        >
          <input
            type="text"
            disabled={!isOwner || isBusy}
            value={draft.domain}
            onChange={(e) => onFieldChange("domain", e.target.value)}
            placeholder="company.com"
            className="h-9 w-full rounded-lg border border-[#d2cee6] px-3 text-sm disabled:opacity-50"
          />
        </FormField>

        <FormField label={t("fields.ssoType")}>
          <select
            disabled={!isOwner || isBusy}
            value={draft.sso_type}
            onChange={(e) =>
              onFieldChange("sso_type", e.target.value as "saml" | "oidc")
            }
            className="h-9 w-full rounded-lg border border-[#d2cee6] px-3 text-sm disabled:opacity-50"
          >
            <option value="saml">SAML 2.0</option>
            <option value="oidc">OIDC</option>
          </select>
        </FormField>
      </div>

      <div className="flex items-center gap-3">
        <input
          id="sso-enabled"
          type="checkbox"
          disabled={!isOwner || isBusy}
          checked={draft.enabled}
          onChange={(e) => onFieldChange("enabled", e.target.checked)}
          className="h-4 w-4 rounded border-[#d2cee6]"
        />
        <label htmlFor="sso-enabled" className="text-sm text-[#2a2640]">
          {t("form.enableSso")}
        </label>
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {t("form.metadataInput")}
        </p>
        <div className="mb-3 flex gap-3 text-sm">
          <label className="flex cursor-pointer items-center gap-1.5">
            <input
              type="radio"
              disabled={!isOwner || isBusy}
              checked={draft.input_mode === "url"}
              onChange={() => onFieldChange("input_mode", "url")}
            />
            {t("form.metadataUrl")}
          </label>
          <label className="flex cursor-pointer items-center gap-1.5">
            <input
              type="radio"
              disabled={!isOwner || isBusy}
              checked={draft.input_mode === "xml"}
              onChange={() => onFieldChange("input_mode", "xml")}
            />
            {t("form.pasteXml")}
          </label>
        </div>

        {draft.input_mode === "url" ? (
          <FormField
            label={t("fields.idpMetadataUrl")}
            hint={t("hints.metadataUrl")}
          >
            <input
              type="url"
              disabled={!isOwner || isBusy}
              value={draft.idp_metadata_url}
              onChange={(e) =>
                onFieldChange("idp_metadata_url", e.target.value)
              }
              placeholder="https://idp.company.com/metadata"
              className="h-9 w-full rounded-lg border border-[#d2cee6] px-3 font-mono text-sm disabled:opacity-50"
            />
          </FormField>
        ) : (
          <FormField
            label={t("fields.idpMetadataXml")}
            hint={t("hints.metadataXml")}
          >
            <textarea
              disabled={!isOwner || isBusy}
              value={draft.idp_metadata_xml}
              onChange={(e) =>
                onFieldChange("idp_metadata_xml", e.target.value)
              }
              rows={6}
              placeholder={'<?xml version="1.0"?>\n<EntityDescriptor ...>'}
              className="w-full resize-y rounded-lg border border-[#d2cee6] px-3 py-2 font-mono text-xs disabled:opacity-50"
            />
          </FormField>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField
          label={t("fields.idpSsoUrlOptional")}
          hint={t("hints.overrideMetadata")}
        >
          <input
            type="url"
            disabled={!isOwner || isBusy}
            value={draft.idp_sso_url}
            onChange={(e) => onFieldChange("idp_sso_url", e.target.value)}
            placeholder="https://idp.company.com/sso"
            className="h-9 w-full rounded-lg border border-[#d2cee6] px-3 font-mono text-sm disabled:opacity-50"
          />
        </FormField>

        <FormField
          label={t("fields.idpEntityIdOptional")}
          hint={t("hints.overrideMetadata")}
        >
          <input
            type="text"
            disabled={!isOwner || isBusy}
            value={draft.idp_entity_id}
            onChange={(e) => onFieldChange("idp_entity_id", e.target.value)}
            placeholder="https://idp.company.com"
            className="h-9 w-full rounded-lg border border-[#d2cee6] px-3 font-mono text-sm disabled:opacity-50"
          />
        </FormField>
      </div>

      <FormField label={t("fields.changeNoteOptional")}>
        <input
          type="text"
          disabled={!isOwner || isBusy}
          value={draft.change_note}
          onChange={(e) => onFieldChange("change_note", e.target.value)}
          placeholder={t("form.changeNotePlaceholder")}
          className="h-9 w-full rounded-lg border border-[#d2cee6] px-3 text-sm disabled:opacity-50"
        />
      </FormField>

      {testResult ? (
        <div
          className={`rounded-lg border px-3 py-2 text-sm ${
            testResult.success
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-700"
          }`}
        >
          <span className="font-semibold">
            {testResult.success
              ? t("connection.succeeded")
              : t("connection.failed")}
            :
          </span>{" "}
          {testResult.detail}
        </div>
      ) : null}

      {submitError ? (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {submitError}
        </p>
      ) : null}

      {isOwner ? (
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <button
            type="button"
            onClick={onTest}
            disabled={isBusy}
            className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#5d58a8] transition hover:bg-[#f5f3ff] disabled:opacity-60"
          >
            {isBusy ? t("actions.testing") : t("actions.testConnection")}
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={isBusy || !draft.domain.trim()}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-60"
          >
            {isBusy ? t("actions.saving") : t("actions.saveConfiguration")}
          </button>
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              disabled={isBusy}
              className="text-sm text-[#68647b] underline decoration-[#bdb7e5] disabled:opacity-60"
            >
              {t("actions.cancel")}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function FormField({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
        {required ? <span className="ms-1 text-rose-500">*</span> : null}
      </label>
      {children}
      {hint ? <p className="mt-0.5 text-xs text-[#a09cb8]">{hint}</p> : null}
    </div>
  );
}

function DeleteConfirmModal({
  isBusy,
  onConfirm,
  onCancel,
}: {
  isBusy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const t = useTranslations("adminSso");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-sm rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-xl">
        <h2 className="mb-2 text-lg font-bold text-[#2a2640]">
          {t("delete.title")}
        </h2>
        <p className="mb-5 text-sm text-[#68647b]">{t("delete.description")}</p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onConfirm}
            disabled={isBusy}
            className="flex-1 rounded-lg bg-rose-600 py-2 text-sm font-semibold text-white transition hover:bg-rose-700 disabled:opacity-60"
          >
            {isBusy ? t("delete.removing") : t("delete.confirm")}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={isBusy}
            className="flex-1 rounded-lg border border-[#d2cee6] py-2 text-sm font-semibold text-[#5d58a8] transition hover:bg-[#f5f3ff] disabled:opacity-60"
          >
            {t("actions.cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}
