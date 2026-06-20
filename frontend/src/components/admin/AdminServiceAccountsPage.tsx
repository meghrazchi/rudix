"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  createServiceAccount,
  createToken,
  deactivateServiceAccount,
  listServiceAccounts,
  listTokens,
  reactivateServiceAccount,
  revokeToken,
  rotateToken,
  updateServiceAccount,
  VALID_ENVIRONMENTS,
  VALID_SCOPES,
  type ServiceAccount,
  type ServiceAccountToken,
  type ServiceAccountTokenCreated,
} from "@/lib/api/service-accounts";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { usePermissions } from "@/lib/use-permissions";

const QUERY_ACCOUNTS = ["admin", "service_accounts", "list"] as const;
const queryTokens = (accountId: string) =>
  ["admin", "service_accounts", accountId, "tokens"] as const;

const SCOPE_LABELS: Record<string, string> = {
  "documents:read": "Documents — read",
  "documents:write": "Documents — write",
  "chat:write": "Chat — write",
  "evaluations:run": "Evaluations — run",
  "webhooks:manage": "Webhooks — manage",
  "connectors:manage": "Connectors — manage",
};

const ENV_LABELS: Record<string, string> = {
  production: "Production",
  staging: "Staging",
  ci: "CI",
  development: "Development",
};

type PanelState =
  | { kind: "idle" }
  | { kind: "create_account" }
  | { kind: "edit_account"; account: ServiceAccount }
  | { kind: "view_tokens"; account: ServiceAccount }
  | { kind: "create_token"; account: ServiceAccount };

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="rounded bg-[#3525cd] px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-[#2b1fa8]"
    >
      {copied ? "Copied!" : "Copy token"}
    </button>
  );
}

function CreatedTokenBanner({
  result,
  onClose,
}: {
  result: ServiceAccountTokenCreated;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="created-token-title"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
        <h3
          id="created-token-title"
          className="mb-1 text-base font-semibold text-[#2a2640]"
        >
          Token created — copy it now
        </h3>
        <p className="mb-4 text-sm text-[#68647b]">
          This is the only time the full token is shown. Store it somewhere
          safe.
        </p>
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-[#d7d4e8] bg-[#f9f8ff] px-3 py-2">
          <code className="flex-1 font-mono text-sm break-all text-[#2a2640]">
            {result.raw_token}
          </code>
          <CopyButton value={result.raw_token} />
        </div>
        <div className="mb-4 text-sm text-[#68647b]">
          <span className="font-medium text-[#2a2640]">Prefix:</span>{" "}
          <code className="font-mono">{result.token_prefix}</code>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
        >
          Done
        </button>
      </div>
    </div>
  );
}

function AccountFormPanel({
  mode,
  existing,
  onClose,
  onSaved,
}: {
  mode: "create" | "edit";
  existing?: ServiceAccount;
  onClose: () => void;
  onSaved: (account: ServiceAccount) => void;
}) {
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [environment, setEnvironment] = useState<string>(
    existing?.environment ?? "production",
  );
  const [selectedScopes, setSelectedScopes] = useState<Set<string>>(
    new Set(existing?.scopes ?? []),
  );
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const createMutation = useMutation({
    mutationFn: () =>
      createServiceAccount({
        name: name.trim(),
        description: description.trim() || null,
        environment: environment as ServiceAccount["environment"],
        scopes: Array.from(selectedScopes),
      }),
    onSuccess: (account) => {
      queryClient.invalidateQueries({ queryKey: QUERY_ACCOUNTS });
      onSaved(account);
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      updateServiceAccount(existing!.id, {
        name: name.trim(),
        description: description.trim() || null,
        environment: environment as ServiceAccount["environment"],
      }),
    onSuccess: (account) => {
      queryClient.invalidateQueries({ queryKey: QUERY_ACCOUNTS });
      onSaved(account);
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const isPending = createMutation.isPending || updateMutation.isPending;

  function toggleScope(scope: string, checked: boolean) {
    setSelectedScopes((prev) => {
      const next = new Set(prev);
      if (checked) next.add(scope);
      else next.delete(scope);
      return next;
    });
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (mode === "create") createMutation.mutate();
    else updateMutation.mutate();
  }

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-[#d7d4e8] bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-[#d7d4e8] px-6 py-4">
        <h2 className="text-lg font-semibold text-[#2a2640]">
          {mode === "create"
            ? "Create Service Account"
            : "Edit Service Account"}
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="text-[#68647b] hover:text-[#2a2640]"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-1 flex-col overflow-y-auto"
      >
        <div className="flex-1 space-y-5 px-6 py-5">
          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={256}
              required
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              placeholder="e.g. CI pipeline, Connector sync"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              maxLength={1024}
              className="w-full resize-none rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              placeholder="Optional description"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Environment
            </label>
            <select
              value={environment}
              onChange={(e) => setEnvironment(e.target.value)}
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
            >
              {VALID_ENVIRONMENTS.map((env) => (
                <option key={env} value={env}>
                  {ENV_LABELS[env] ?? env}
                </option>
              ))}
            </select>
          </div>

          {mode === "create" && (
            <div>
              <p className="mb-2 text-sm font-medium text-[#2a2640]">Scopes</p>
              <div className="space-y-2 rounded-lg bg-[#f9f8ff] p-3">
                {VALID_SCOPES.map((scope) => (
                  <label
                    key={scope}
                    className="flex cursor-pointer items-center gap-2"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-[#3525cd]"
                      checked={selectedScopes.has(scope)}
                      onChange={(e) => toggleScope(scope, e.target.checked)}
                    />
                    <span className="text-sm text-[#2a2640]">
                      {SCOPE_LABELS[scope] ?? scope}
                    </span>
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-[#68647b]">
                Scopes apply to all tokens issued for this service account.
              </p>
            </div>
          )}
        </div>

        {error && (
          <p className="mx-6 mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <div className="flex gap-3 border-t border-[#d7d4e8] px-6 py-4">
          <button
            type="submit"
            disabled={isPending || !name.trim()}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
          >
            {isPending
              ? "Saving…"
              : mode === "create"
                ? "Create account"
                : "Save changes"}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </form>
    </aside>
  );
}

function TokenFormPanel({
  account,
  onClose,
  onCreated,
}: {
  account: ServiceAccount;
  onClose: () => void;
  onCreated: (result: ServiceAccountTokenCreated) => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const createMutation = useMutation({
    mutationFn: () => createToken(account.id, { name: name.trim() }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryTokens(account.id) });
      onCreated(result);
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    createMutation.mutate();
  }

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-[#d7d4e8] bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-[#d7d4e8] px-6 py-4">
        <h2 className="text-lg font-semibold text-[#2a2640]">
          Issue Token
          <span className="ml-2 text-sm font-normal text-[#68647b]">
            for {account.name}
          </span>
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="text-[#68647b] hover:text-[#2a2640]"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-1 flex-col overflow-y-auto"
      >
        <div className="flex-1 space-y-5 px-6 py-5">
          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Token name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={256}
              required
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              placeholder="e.g. Primary, GitHub Actions"
            />
          </div>
          <p className="text-xs text-[#68647b]">
            The token will inherit all scopes of the service account. It will be
            shown once — copy it before closing.
          </p>
        </div>

        {error && (
          <p className="mx-6 mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <div className="flex gap-3 border-t border-[#d7d4e8] px-6 py-4">
          <button
            type="submit"
            disabled={createMutation.isPending || !name.trim()}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
          >
            {createMutation.isPending ? "Issuing…" : "Issue token"}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={createMutation.isPending}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </form>
    </aside>
  );
}

function TokensPanel({
  account,
  canManage,
  onClose,
  onIssue,
  onNewToken,
}: {
  account: ServiceAccount;
  canManage: boolean;
  onClose: () => void;
  onIssue: () => void;
  onNewToken: (result: ServiceAccountTokenCreated) => void;
}) {
  const [revokeTarget, setRevokeTarget] = useState<ServiceAccountToken | null>(
    null,
  );
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const tokensQuery = useQuery({
    queryKey: queryTokens(account.id),
    queryFn: () => listTokens(account.id),
  });

  const revokeMutation = useMutation({
    mutationFn: (tokenId: string) => revokeToken(account.id, tokenId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryTokens(account.id) });
      setRevokeTarget(null);
      setRevokeError(null);
    },
    onError: (err) => setRevokeError(getApiErrorMessage(err)),
  });

  const rotateMutation = useMutation({
    mutationFn: (tokenId: string) => rotateToken(account.id, tokenId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryTokens(account.id) });
      onNewToken(result);
    },
    onError: () => {},
  });

  const tokens = tokensQuery.data?.items ?? [];
  const activeTokens = tokens.filter((t) => t.status === "active");
  const revokedTokens = tokens.filter((t) => t.status === "revoked");

  return (
    <>
      <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-lg flex-col border-l border-[#d7d4e8] bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-[#d7d4e8] px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-[#2a2640]">
              {account.name}
            </h2>
            <span className="text-sm text-[#68647b]">
              {ENV_LABELS[account.environment] ?? account.environment} •{" "}
              {account.is_active ? "Active" : "Inactive"}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-[#68647b] hover:text-[#2a2640]"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {account.scopes.length > 0 && (
            <div className="mb-5 flex flex-wrap gap-1">
              {account.scopes.map((s) => (
                <span
                  key={s}
                  className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#4d4880]"
                >
                  {s}
                </span>
              ))}
            </div>
          )}

          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#2a2640]">
              Tokens
              {activeTokens.length > 0 && (
                <span className="ml-1 font-normal text-[#68647b]">
                  ({activeTokens.length} active)
                </span>
              )}
            </h3>
            {canManage && account.is_active && (
              <button
                type="button"
                onClick={onIssue}
                className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-[#2b1fa8]"
              >
                + Issue token
              </button>
            )}
          </div>

          {tokensQuery.isLoading ? (
            <div className="py-4 text-center text-sm text-[#68647b]">
              Loading tokens…
            </div>
          ) : activeTokens.length === 0 && revokedTokens.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[#d7d4e8] p-6 text-center text-sm text-[#68647b]">
              No tokens yet.
              {canManage && account.is_active && (
                <>
                  {" "}
                  <button
                    type="button"
                    onClick={onIssue}
                    className="font-medium text-[#3525cd] hover:underline"
                  >
                    Issue one
                  </button>{" "}
                  to start making authenticated requests.
                </>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {activeTokens.map((token) => (
                <TokenCard
                  key={token.id}
                  token={token}
                  canManage={canManage}
                  onRevoke={() => {
                    setRevokeTarget(token);
                    setRevokeError(null);
                  }}
                  onRotate={() => rotateMutation.mutate(token.id)}
                />
              ))}
              {revokedTokens.length > 0 && (
                <div className="mt-4">
                  <p className="mb-2 text-xs font-semibold tracking-wide text-[#68647b] uppercase">
                    Revoked ({revokedTokens.length})
                  </p>
                  {revokedTokens.map((token) => (
                    <TokenCard
                      key={token.id}
                      token={token}
                      canManage={false}
                      onRevoke={() => {}}
                      onRotate={() => {}}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </aside>

      {revokeTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="revoke-token-title"
        >
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h3
              id="revoke-token-title"
              className="mb-2 text-base font-semibold text-[#2a2640]"
            >
              Revoke &ldquo;{revokeTarget.name}&rdquo;?
            </h3>
            <p className="mb-4 text-sm text-[#68647b]">
              The token will stop working immediately. This cannot be undone.
            </p>
            {revokeError && (
              <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {revokeError}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => revokeMutation.mutate(revokeTarget.id)}
                disabled={revokeMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {revokeMutation.isPending ? "Revoking…" : "Revoke token"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setRevokeTarget(null);
                  setRevokeError(null);
                }}
                disabled={revokeMutation.isPending}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function TokenCard({
  token,
  canManage,
  onRevoke,
  onRotate,
}: {
  token: ServiceAccountToken;
  canManage: boolean;
  onRevoke: () => void;
  onRotate: () => void;
}) {
  const isRevoked = token.status === "revoked";
  return (
    <div
      className={`rounded-xl border p-4 shadow-sm ${
        isRevoked
          ? "border-[#e8e6f0] bg-[#fafafa] opacity-60"
          : "border-[#d7d4e8] bg-white"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-medium text-[#2a2640]">{token.name}</span>
            {isRevoked ? (
              <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                Revoked
              </span>
            ) : (
              <span className="rounded-full bg-[#e8f5e9] px-2 py-0.5 text-xs font-medium text-[#2e7d32]">
                Active
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-3 text-xs text-[#68647b]">
            <span>
              Prefix:{" "}
              <code className="font-mono text-[#2a2640]">
                {token.token_prefix}…
              </code>
            </span>
            {token.last_used_at ? (
              <span>
                Last used:{" "}
                {new Date(token.last_used_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}
              </span>
            ) : (
              <span>Never used</span>
            )}
          </div>
        </div>
        {canManage && !isRevoked && (
          <div className="flex shrink-0 gap-3">
            <button
              type="button"
              onClick={onRotate}
              className="text-sm font-medium text-[#3525cd] hover:underline"
            >
              Rotate
            </button>
            <button
              type="button"
              onClick={onRevoke}
              className="text-sm font-medium text-red-600 hover:underline"
            >
              Revoke
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function ServiceAccountCard({
  account,
  canManage,
  onEdit,
  onViewTokens,
  onDeactivate,
  onReactivate,
}: {
  account: ServiceAccount;
  canManage: boolean;
  onEdit: (account: ServiceAccount) => void;
  onViewTokens: (account: ServiceAccount) => void;
  onDeactivate: (account: ServiceAccount) => void;
  onReactivate: (account: ServiceAccount) => void;
}) {
  return (
    <div
      className={`rounded-xl border p-5 shadow-sm ${
        !account.is_active
          ? "border-[#e8e6f0] bg-[#fafafa] opacity-60"
          : "border-[#d7d4e8] bg-white"
      }`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[#2a2640]">{account.name}</span>
            {account.is_active ? (
              <span className="rounded-full bg-[#e8f5e9] px-2 py-0.5 text-xs font-medium text-[#2e7d32]">
                Active
              </span>
            ) : (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                Inactive
              </span>
            )}
            <span className="rounded-full border border-[#d7d4e8] px-2 py-0.5 text-xs text-[#68647b]">
              {ENV_LABELS[account.environment] ?? account.environment}
            </span>
          </div>
          {account.description && (
            <p className="mt-0.5 text-sm text-[#68647b]">
              {account.description}
            </p>
          )}
        </div>
      </div>

      {account.scopes.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {account.scopes.map((s) => (
            <span
              key={s}
              className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#4d4880]"
            >
              {s}
            </span>
          ))}
        </div>
      )}

      <div className="mb-3 flex flex-wrap gap-3 text-xs text-[#68647b]">
        {account.last_used_at ? (
          <span>
            Last used:{" "}
            {new Date(account.last_used_at).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
              year: "numeric",
            })}
          </span>
        ) : (
          <span>Never used</span>
        )}
      </div>

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => onViewTokens(account)}
          className="text-sm font-medium text-[#3525cd] hover:underline"
        >
          Tokens
        </button>
        {canManage && account.is_active && (
          <>
            <button
              type="button"
              onClick={() => onEdit(account)}
              className="text-sm font-medium text-[#3525cd] hover:underline"
            >
              Edit
            </button>
            <button
              type="button"
              onClick={() => onDeactivate(account)}
              className="text-sm font-medium text-red-600 hover:underline"
            >
              Deactivate
            </button>
          </>
        )}
        {canManage && !account.is_active && (
          <button
            type="button"
            onClick={() => onReactivate(account)}
            className="text-sm font-medium text-[#3525cd] hover:underline"
          >
            Reactivate
          </button>
        )}
      </div>
    </div>
  );
}

export function AdminServiceAccountsPage() {
  const { hasPermission } = usePermissions();
  const canList = hasPermission("service_accounts:list");
  const canCreate = hasPermission("service_accounts:create");
  const canManage =
    hasPermission("service_accounts:manage") &&
    hasPermission("service_accounts:revoke");

  const [panel, setPanel] = useState<PanelState>({ kind: "idle" });
  const [deactivateTarget, setDeactivateTarget] =
    useState<ServiceAccount | null>(null);
  const [deactivateError, setDeactivateError] = useState<string | null>(null);
  const [newToken, setNewToken] = useState<ServiceAccountTokenCreated | null>(
    null,
  );

  const queryClient = useQueryClient();

  const accountsQuery = useQuery({
    queryKey: QUERY_ACCOUNTS,
    queryFn: listServiceAccounts,
    enabled: canList,
  });

  const deactivateMutation = useMutation({
    mutationFn: (accountId: string) => deactivateServiceAccount(accountId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_ACCOUNTS });
      setDeactivateTarget(null);
      setDeactivateError(null);
    },
    onError: (err) => setDeactivateError(getApiErrorMessage(err)),
  });

  const reactivateMutation = useMutation({
    mutationFn: (accountId: string) => reactivateServiceAccount(accountId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_ACCOUNTS });
    },
    onError: () => {},
  });

  if (!canList) {
    return (
      <ForbiddenState
        title="Service Accounts"
        description="You need the service_accounts:list permission to access this page."
        backHref="/dashboard"
      />
    );
  }

  if (accountsQuery.isLoading) return <LoadingState />;

  if (accountsQuery.isError) {
    if (isForbiddenError(accountsQuery.error)) {
      return (
        <ForbiddenState
          title="Service Accounts"
          description="You do not have access to service account management."
          requestId={extractRequestIdFromError(accountsQuery.error)}
          backHref="/dashboard"
        />
      );
    }
    return <ErrorState description={getApiErrorMessage(accountsQuery.error)} />;
  }

  const accounts = accountsQuery.data?.items ?? [];
  const activeAccounts = accounts.filter((a) => a.is_active);
  const inactiveAccounts = accounts.filter((a) => !a.is_active);

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-4 py-8">
      <div className="flex items-start justify-between">
        <div>
          <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            Admin
          </p>
          <h1 className="text-2xl font-extrabold text-[#2a2640]">
            Service Accounts
          </h1>
          <p className="mt-1 text-sm text-[#68647b]">
            Machine identities for CI pipelines, connectors, and automation.
            Tokens are scoped, shown once, and stored hashed.
          </p>
        </div>
        {canCreate && (
          <button
            type="button"
            onClick={() => setPanel({ kind: "create_account" })}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            + Create service account
          </button>
        )}
      </div>

      <section>
        <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
          Active accounts
          <span className="ml-2 text-sm font-normal text-[#68647b]">
            ({activeAccounts.length})
          </span>
        </h2>
        {activeAccounts.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[#d7d4e8] p-8 text-center text-sm text-[#68647b]">
            No active service accounts.
            {canCreate && (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => setPanel({ kind: "create_account" })}
                  className="font-medium text-[#3525cd] hover:underline"
                >
                  Create one
                </button>{" "}
                to enable non-human API access.
              </>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {activeAccounts.map((account) => (
              <ServiceAccountCard
                key={account.id}
                account={account}
                canManage={canManage}
                onEdit={(a) => setPanel({ kind: "edit_account", account: a })}
                onViewTokens={(a) =>
                  setPanel({ kind: "view_tokens", account: a })
                }
                onDeactivate={(a) => {
                  setDeactivateTarget(a);
                  setDeactivateError(null);
                }}
                onReactivate={(a) => reactivateMutation.mutate(a.id)}
              />
            ))}
          </div>
        )}
      </section>

      {inactiveAccounts.length > 0 && (
        <section>
          <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
            Inactive accounts
            <span className="ml-2 text-sm font-normal text-[#68647b]">
              ({inactiveAccounts.length})
            </span>
          </h2>
          <div className="space-y-3">
            {inactiveAccounts.map((account) => (
              <ServiceAccountCard
                key={account.id}
                account={account}
                canManage={canManage}
                onEdit={() => {}}
                onViewTokens={(a) =>
                  setPanel({ kind: "view_tokens", account: a })
                }
                onDeactivate={() => {}}
                onReactivate={(a) => reactivateMutation.mutate(a.id)}
              />
            ))}
          </div>
        </section>
      )}

      {/* Deactivate confirmation dialog */}
      {deactivateTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="deactivate-dialog-title"
        >
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h3
              id="deactivate-dialog-title"
              className="mb-2 text-base font-semibold text-[#2a2640]"
            >
              Deactivate &ldquo;{deactivateTarget.name}&rdquo;?
            </h3>
            <p className="mb-4 text-sm text-[#68647b]">
              All tokens for this service account will stop working immediately.
              You can reactivate later.
            </p>
            {deactivateError && (
              <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {deactivateError}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => deactivateMutation.mutate(deactivateTarget.id)}
                disabled={deactivateMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {deactivateMutation.isPending ? "Deactivating…" : "Deactivate"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setDeactivateTarget(null);
                  setDeactivateError(null);
                }}
                disabled={deactivateMutation.isPending}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create account panel */}
      {panel.kind === "create_account" && (
        <AccountFormPanel
          mode="create"
          onClose={() => setPanel({ kind: "idle" })}
          onSaved={() => setPanel({ kind: "idle" })}
        />
      )}

      {/* Edit account panel */}
      {panel.kind === "edit_account" && (
        <AccountFormPanel
          mode="edit"
          existing={panel.account}
          onClose={() => setPanel({ kind: "idle" })}
          onSaved={() => setPanel({ kind: "idle" })}
        />
      )}

      {/* Tokens panel */}
      {panel.kind === "view_tokens" && (
        <TokensPanel
          account={panel.account}
          canManage={canCreate && canManage}
          onClose={() => setPanel({ kind: "idle" })}
          onIssue={() =>
            setPanel({ kind: "create_token", account: panel.account })
          }
          onNewToken={(result) => {
            setNewToken(result);
          }}
        />
      )}

      {/* Issue token panel */}
      {panel.kind === "create_token" && (
        <TokenFormPanel
          account={panel.account}
          onClose={() =>
            setPanel({ kind: "view_tokens", account: panel.account })
          }
          onCreated={(result) => {
            setPanel({ kind: "view_tokens", account: panel.account });
            setNewToken(result);
          }}
        />
      )}

      {/* Raw token shown once */}
      {newToken && (
        <CreatedTokenBanner
          result={newToken}
          onClose={() => setNewToken(null)}
        />
      )}
    </div>
  );
}
