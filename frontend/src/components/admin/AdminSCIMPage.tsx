"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  checkDomainVerification,
  deleteDomainVerification,
  disableSCIM,
  enableSCIM,
  getSCIMConfig,
  initiateDomainVerification,
  listDomainVerifications,
  rotateSCIMToken,
  type DomainCheckResult,
  type DomainVerification,
  type SCIMConfig,
  type SCIMEnableResponse,
} from "@/lib/api/scim";
import { getApiErrorMessage } from "@/lib/api/errors";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

const SCIM_KEY = ["scim-config"] as const;
const DOMAINS_KEY = ["scim-domain-verifications"] as const;

export function AdminSCIMPage() {
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const role = state.session?.role;
  const isAdmin = canViewAdminUsage(role);
  const isOwner = role === "owner";

  const [actionError, setActionError] = useState<string | null>(null);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [showDisableConfirm, setShowDisableConfirm] = useState(false);
  const [showRotateConfirm, setShowRotateConfirm] = useState(false);
  const [newDomain, setNewDomain] = useState("");
  const [domainError, setDomainError] = useState<string | null>(null);

  const configQuery = useQuery({
    queryKey: SCIM_KEY,
    queryFn: getSCIMConfig,
    enabled: isAdmin,
    retry: (count, err) => !isForbiddenError(err) && count < 2,
  });

  const domainsQuery = useQuery({
    queryKey: DOMAINS_KEY,
    queryFn: listDomainVerifications,
    enabled: isAdmin,
    retry: (count, err) => !isForbiddenError(err) && count < 2,
  });

  const enableMutation = useMutation({
    mutationFn: enableSCIM,
    onSuccess: (data: SCIMEnableResponse) => {
      queryClient.setQueryData(SCIM_KEY, data.config);
      setNewToken(data.bearer_token);
      setActionError(null);
    },
    onError: (err) => {
      setActionError(getApiErrorMessage(err, "Failed to enable SCIM."));
    },
  });

  const rotateMutation = useMutation({
    mutationFn: rotateSCIMToken,
    onSuccess: (data: SCIMEnableResponse) => {
      queryClient.setQueryData(SCIM_KEY, data.config);
      setNewToken(data.bearer_token);
      setShowRotateConfirm(false);
      setActionError(null);
    },
    onError: (err) => {
      setActionError(getApiErrorMessage(err, "Failed to rotate token."));
      setShowRotateConfirm(false);
    },
  });

  const disableMutation = useMutation({
    mutationFn: disableSCIM,
    onSuccess: () => {
      queryClient.setQueryData(SCIM_KEY, null);
      setShowDisableConfirm(false);
      setNewToken(null);
      setActionError(null);
    },
    onError: (err) => {
      setActionError(getApiErrorMessage(err, "Failed to disable SCIM."));
      setShowDisableConfirm(false);
    },
  });

  const initiateMutation = useMutation({
    mutationFn: (domain: string) => initiateDomainVerification({ domain }),
    onSuccess: (record) => {
      queryClient.setQueryData(DOMAINS_KEY, (prev: DomainVerification[] | undefined) => {
        const existing = prev ?? [];
        const idx = existing.findIndex((d) => d.id === record.id);
        if (idx >= 0) {
          const next = [...existing];
          next[idx] = record;
          return next;
        }
        return [record, ...existing];
      });
      setNewDomain("");
      setDomainError(null);
    },
    onError: (err) => {
      setDomainError(getApiErrorMessage(err, "Failed to initiate domain verification."));
    },
  });

  const checkMutation = useMutation({
    mutationFn: checkDomainVerification,
    onSuccess: (result: DomainCheckResult) => {
      queryClient.setQueryData(DOMAINS_KEY, (prev: DomainVerification[] | undefined) => {
        return (prev ?? []).map((d) =>
          d.id === result.id ? { ...d, ...result } : d,
        );
      });
    },
    onError: (err) => {
      setActionError(getApiErrorMessage(err, "Failed to check domain."));
    },
  });

  const deleteDomainMutation = useMutation({
    mutationFn: deleteDomainVerification,
    onSuccess: (_: void, deletedId: string) => {
      queryClient.setQueryData(DOMAINS_KEY, (prev: DomainVerification[] | undefined) =>
        (prev ?? []).filter((d) => d.id !== deletedId),
      );
    },
    onError: (err) => {
      setActionError(getApiErrorMessage(err, "Failed to remove domain."));
    },
  });

  if (!isAdmin) return <ForbiddenState />;
  if (configQuery.isLoading || domainsQuery.isLoading) return <LoadingState />;
  if (
    (configQuery.isError && isForbiddenError(configQuery.error)) ||
    (domainsQuery.isError && isForbiddenError(domainsQuery.error))
  )
    return <ForbiddenState />;
  if (configQuery.isError)
    return (
      <ErrorState
        message={getApiErrorMessage(
          configQuery.error,
          "Failed to load SCIM configuration.",
        )}
      />
    );

  const config = configQuery.data ?? null;
  const domains = domainsQuery.data ?? [];
  const isBusy =
    enableMutation.isPending ||
    rotateMutation.isPending ||
    disableMutation.isPending;

  return (
    <div className="space-y-8 p-6">
      <div>
        <h1 className="text-2xl font-bold text-[#2a2640]">
          SCIM Provisioning &amp; Domain Verification
        </h1>
        <p className="mt-1 text-sm text-[#68647b]">
          Automate user lifecycle via SCIM 2.0 and verify organization-owned
          domains.
        </p>
      </div>

      {actionError ? (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {actionError}
        </p>
      ) : null}

      {/* ── SCIM configuration panel ── */}
      <section className="rounded-xl border border-[#d7d4e8] bg-white p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-[#2a2640]">
              SCIM 2.0 Provisioning
            </h2>
            <p className="mt-0.5 text-xs text-[#68647b]">
              Connect your identity provider (Okta, Azure AD, etc.) to
              automatically provision and deprovision users.
            </p>
          </div>
          {config ? (
            <span className="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
              Active
            </span>
          ) : (
            <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-600">
              Not configured
            </span>
          )}
        </div>

        {config ? (
          <div className="space-y-4">
            <ReadField label="SCIM Base URL" value={config.scim_base_url} mono />
            <ReadField
              label="Token (last 4 chars)"
              value={`…${config.token_hint}`}
              mono
            />

            <div className="grid grid-cols-2 gap-4 text-sm">
              <StatCard
                label="Provisioned"
                value={config.provisioned_count}
                color="emerald"
              />
              <StatCard
                label="Deprovisioned"
                value={config.deprovisioned_count}
                color="amber"
              />
            </div>

            {config.last_sync_at ? (
              <p className="text-xs text-[#68647b]">
                Last sync:{" "}
                <span className="font-medium">
                  {new Date(config.last_sync_at).toLocaleString()}
                </span>
                {config.last_sync_error ? (
                  <span className="ml-2 text-rose-600">
                    Error: {config.last_sync_error}
                  </span>
                ) : null}
              </p>
            ) : null}

            {isOwner ? (
              <div className="flex flex-wrap gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShowRotateConfirm(true)}
                  disabled={isBusy}
                  className="rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#5d58a8] hover:bg-[#f5f3ff] disabled:opacity-60 transition"
                >
                  Rotate Token
                </button>
                <button
                  type="button"
                  onClick={() => setShowDisableConfirm(true)}
                  disabled={isBusy}
                  className="rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-semibold text-rose-600 hover:bg-rose-50 disabled:opacity-60 transition"
                >
                  Disable SCIM
                </button>
              </div>
            ) : null}
          </div>
        ) : isOwner ? (
          <button
            type="button"
            onClick={() => enableMutation.mutate()}
            disabled={isBusy}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:opacity-60 transition"
          >
            {enableMutation.isPending ? "Enabling…" : "Enable SCIM"}
          </button>
        ) : (
          <p className="text-sm text-[#68647b]">
            Only owners can configure SCIM provisioning.
          </p>
        )}
      </section>

      {/* ── New token reveal ── */}
      {newToken ? (
        <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 space-y-3">
          <p className="text-sm font-semibold text-emerald-800">
            Save your SCIM bearer token — it will not be shown again.
          </p>
          <CopyField value={newToken} />
          <p className="text-xs text-emerald-700">
            Paste this token into your identity provider&apos;s SCIM
            configuration as the Bearer Token.
          </p>
          <button
            type="button"
            onClick={() => setNewToken(null)}
            className="text-xs font-semibold text-emerald-700 underline"
          >
            I&apos;ve saved it, dismiss
          </button>
        </section>
      ) : null}

      {/* ── Domain verification panel ── */}
      <section className="rounded-xl border border-[#d7d4e8] bg-white p-6 space-y-5">
        <div>
          <h2 className="text-base font-semibold text-[#2a2640]">
            Domain Verification
          </h2>
          <p className="mt-0.5 text-xs text-[#68647b]">
            Verify your organization owns a domain before enforcing
            domain-based access controls.
          </p>
        </div>

        {isOwner ? (
          <div className="flex gap-2">
            <input
              type="text"
              value={newDomain}
              onChange={(e) => setNewDomain(e.target.value)}
              placeholder="company.com"
              className="h-9 flex-1 rounded-lg border border-[#d2cee6] px-3 text-sm"
            />
            <button
              type="button"
              onClick={() => {
                setDomainError(null);
                initiateMutation.mutate(newDomain);
              }}
              disabled={!newDomain.trim() || initiateMutation.isPending}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:opacity-60 transition"
            >
              {initiateMutation.isPending ? "Adding…" : "Add Domain"}
            </button>
          </div>
        ) : null}

        {domainError ? (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {domainError}
          </p>
        ) : null}

        {domains.length === 0 ? (
          <p className="text-sm text-[#a09cb8]">
            No domains added yet. Add a domain above to start verification.
          </p>
        ) : (
          <div className="space-y-3">
            {domains.map((d) => (
              <DomainVerificationCard
                key={d.id}
                record={d}
                isOwner={isOwner}
                isChecking={
                  checkMutation.isPending &&
                  checkMutation.variables === d.id
                }
                isDeleting={
                  deleteDomainMutation.isPending &&
                  deleteDomainMutation.variables === d.id
                }
                onCheck={() => checkMutation.mutate(d.id)}
                onDelete={() => deleteDomainMutation.mutate(d.id)}
              />
            ))}
          </div>
        )}
      </section>

      {showDisableConfirm ? (
        <ConfirmModal
          title="Disable SCIM?"
          body="This will remove your SCIM configuration and bearer token. Provisioned users will not be removed but future sync events will fail."
          confirmLabel={disableMutation.isPending ? "Disabling…" : "Disable SCIM"}
          confirmVariant="danger"
          isBusy={disableMutation.isPending}
          onConfirm={() => disableMutation.mutate()}
          onCancel={() => setShowDisableConfirm(false)}
        />
      ) : null}

      {showRotateConfirm ? (
        <ConfirmModal
          title="Rotate SCIM token?"
          body="The current bearer token will be invalidated immediately. You must update your identity provider configuration with the new token before the next sync."
          confirmLabel={rotateMutation.isPending ? "Rotating…" : "Rotate Token"}
          confirmVariant="warning"
          isBusy={rotateMutation.isPending}
          onConfirm={() => rotateMutation.mutate()}
          onCancel={() => setShowRotateConfirm(false)}
        />
      ) : null}
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ReadField({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
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
          className={`flex-1 break-all rounded border border-[#e4e1f2] bg-[#f9f8ff] px-3 py-1.5 text-sm text-[#2a2640] ${
            mono ? "font-mono text-xs" : ""
          }`}
        >
          {value}
        </p>
        <button
          type="button"
          onClick={handleCopy}
          className="shrink-0 rounded border border-[#d2cee6] px-2 py-1 text-xs text-[#5d58a8] hover:bg-[#f5f3ff] transition"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="flex items-center gap-2">
      <code className="flex-1 break-all rounded border border-emerald-200 bg-white px-3 py-2 text-xs font-mono text-emerald-900">
        {value}
      </code>
      <button
        type="button"
        onClick={handleCopy}
        className="shrink-0 rounded border border-emerald-300 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 transition"
      >
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: "emerald" | "amber";
}) {
  const colorClasses =
    color === "emerald"
      ? "bg-emerald-50 border-emerald-100 text-emerald-800"
      : "bg-amber-50 border-amber-100 text-amber-800";

  return (
    <div className={`rounded-lg border px-4 py-3 ${colorClasses}`}>
      <p className="text-xs font-semibold uppercase tracking-wide opacity-70">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

function DomainVerificationCard({
  record,
  isOwner,
  isChecking,
  isDeleting,
  onCheck,
  onDelete,
}: {
  record: DomainVerification;
  isOwner: boolean;
  isChecking: boolean;
  isDeleting: boolean;
  onCheck: () => void;
  onDelete: () => void;
}) {
  const [showInstructions, setShowInstructions] = useState(false);

  const statusColors = {
    pending: "bg-amber-100 text-amber-800",
    verified: "bg-emerald-100 text-emerald-800",
    failed: "bg-rose-100 text-rose-700",
  };

  return (
    <div className="rounded-lg border border-[#e4e1f2] bg-[#fafaff] p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${
              statusColors[record.status]
            }`}
          >
            {record.status}
          </span>
          <span className="text-sm font-medium text-[#2a2640]">
            {record.domain}
          </span>
        </div>
        {isOwner ? (
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => setShowInstructions((p) => !p)}
              className="rounded border border-[#d2cee6] px-2 py-1 text-xs text-[#5d58a8] hover:bg-[#f5f3ff] transition"
            >
              {showInstructions ? "Hide" : "Instructions"}
            </button>
            {record.status !== "verified" ? (
              <button
                type="button"
                onClick={onCheck}
                disabled={isChecking}
                className="rounded border border-[#d2cee6] px-2 py-1 text-xs text-[#5d58a8] hover:bg-[#f5f3ff] disabled:opacity-60 transition"
              >
                {isChecking ? "Checking…" : "Check DNS"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={onDelete}
              disabled={isDeleting}
              className="rounded border border-rose-200 px-2 py-1 text-xs text-rose-600 hover:bg-rose-50 disabled:opacity-60 transition"
            >
              {isDeleting ? "…" : "Remove"}
            </button>
          </div>
        ) : null}
      </div>

      {record.failure_reason ? (
        <p className="text-xs text-rose-600">{record.failure_reason}</p>
      ) : null}

      {record.last_checked_at ? (
        <p className="text-xs text-[#a09cb8]">
          Last checked: {new Date(record.last_checked_at).toLocaleString()}
        </p>
      ) : null}

      {showInstructions ? (
        <div className="rounded-lg border border-[#d7d4e8] bg-white p-3 space-y-2 text-xs">
          <p className="font-semibold text-[#2a2640]">
            Add the following DNS TXT record to verify ownership:
          </p>
          <div className="space-y-1">
            <div className="flex gap-2">
              <span className="w-20 shrink-0 font-semibold text-[#6a6780] uppercase">
                Name
              </span>
              <code className="break-all text-[#2a2640]">
                {record.txt_record_name}
              </code>
            </div>
            <div className="flex gap-2">
              <span className="w-20 shrink-0 font-semibold text-[#6a6780] uppercase">
                Value
              </span>
              <code className="break-all text-[#2a2640]">
                {record.txt_record_value}
              </code>
            </div>
          </div>
          <p className="text-[#a09cb8]">
            After adding the record, click &quot;Check DNS&quot; to verify.
            DNS propagation can take up to 48 hours.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function ConfirmModal({
  title,
  body,
  confirmLabel,
  confirmVariant,
  isBusy,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  confirmVariant: "danger" | "warning";
  isBusy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const btnColor =
    confirmVariant === "danger"
      ? "bg-rose-600 hover:bg-rose-700"
      : "bg-amber-500 hover:bg-amber-600";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-sm rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-xl">
        <h2 className="mb-2 text-lg font-bold text-[#2a2640]">{title}</h2>
        <p className="mb-5 text-sm text-[#68647b]">{body}</p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onConfirm}
            disabled={isBusy}
            className={`flex-1 rounded-lg py-2 text-sm font-semibold text-white disabled:opacity-60 transition ${btnColor}`}
          >
            {confirmLabel}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={isBusy}
            className="flex-1 rounded-lg border border-[#d2cee6] py-2 text-sm font-semibold text-[#5d58a8] hover:bg-[#f5f3ff] disabled:opacity-60 transition"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
