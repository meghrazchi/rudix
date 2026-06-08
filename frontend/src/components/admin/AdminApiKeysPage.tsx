"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  createApiKey,
  listApiKeys,
  revokeApiKey,
  rotateApiKey,
  updateApiKey,
  VALID_SCOPES,
  type ApiKey,
  type ApiKeyCreated,
} from "@/lib/api/api-keys";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { usePermissions } from "@/lib/use-permissions";

const QUERY_API_KEYS = ["admin", "api_keys", "list"] as const;

const SCOPE_LABELS: Record<string, string> = {
  "documents:read": "Documents — read",
  "documents:write": "Documents — write",
  "chat:write": "Chat — write",
  "evaluations:run": "Evaluations — run",
  "webhooks:manage": "Webhooks — manage",
  "connectors:manage": "Connectors — manage",
};

type PanelState =
  | { kind: "idle" }
  | { kind: "create" }
  | { kind: "edit"; key: ApiKey }
  | { kind: "created"; result: ApiKeyCreated };

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
      {copied ? "Copied!" : "Copy key"}
    </button>
  );
}

function CreatedKeyBanner({
  result,
  onClose,
}: {
  result: ApiKeyCreated;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="created-key-title"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
        <h3
          id="created-key-title"
          className="mb-1 text-base font-semibold text-[#2a2640]"
        >
          API key created — copy it now
        </h3>
        <p className="mb-4 text-sm text-[#68647b]">
          This is the only time the full key is shown. Store it somewhere safe.
        </p>
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-[#d7d4e8] bg-[#f9f8ff] px-3 py-2">
          <code className="flex-1 font-mono text-sm break-all text-[#2a2640]">
            {result.raw_key}
          </code>
          <CopyButton value={result.raw_key} />
        </div>
        <div className="mb-4 text-sm text-[#68647b]">
          <span className="font-medium text-[#2a2640]">Prefix:</span>{" "}
          <code className="font-mono">{result.key_prefix}</code>
          {result.scopes.length > 0 && (
            <>
              <span className="ml-4 font-medium text-[#2a2640]">Scopes:</span>{" "}
              {result.scopes.join(", ")}
            </>
          )}
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

function ApiKeyFormPanel({
  mode,
  existingKey,
  onClose,
  onSaved,
}: {
  mode: "create" | "edit";
  existingKey?: ApiKey;
  onClose: () => void;
  onSaved: (result?: ApiKeyCreated) => void;
}) {
  const [name, setName] = useState(existingKey?.name ?? "");
  const [description, setDescription] = useState(
    existingKey?.description ?? "",
  );
  const [selectedScopes, setSelectedScopes] = useState<Set<string>>(
    new Set(existingKey?.scopes ?? []),
  );
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const createMutation = useMutation({
    mutationFn: () =>
      createApiKey({
        name: name.trim(),
        description: description.trim() || null,
        scopes: Array.from(selectedScopes),
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: QUERY_API_KEYS });
      onSaved(result);
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      updateApiKey(existingKey!.id, {
        name: name.trim(),
        description: description.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_API_KEYS });
      onSaved();
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
          {mode === "create" ? "Create API Key" : "Edit API Key"}
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
              placeholder="e.g. CI integration key"
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
                Scopes cannot be changed after creation. Rotate the key to
                change scopes.
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
                ? "Create key"
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

function ApiKeyCard({
  apiKey,
  canManage,
  onEdit,
  onRevoke,
  onRotate,
}: {
  apiKey: ApiKey;
  canManage: boolean;
  onEdit: (key: ApiKey) => void;
  onRevoke: (key: ApiKey) => void;
  onRotate: (key: ApiKey) => void;
}) {
  const isRevoked = apiKey.status === "revoked";

  return (
    <div
      className={`rounded-xl border p-5 shadow-sm ${
        isRevoked
          ? "border-[#e8e6f0] bg-[#fafafa] opacity-60"
          : "border-[#d7d4e8] bg-white"
      }`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[#2a2640]">{apiKey.name}</span>
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
          {apiKey.description && (
            <p className="mt-0.5 text-sm text-[#68647b]">
              {apiKey.description}
            </p>
          )}
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-[#68647b]">
        <span>
          Prefix:{" "}
          <code className="font-mono text-[#2a2640]">{apiKey.key_prefix}…</code>
        </span>
        {apiKey.last_used_at ? (
          <span>
            Last used:{" "}
            {new Date(apiKey.last_used_at).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
              year: "numeric",
            })}
          </span>
        ) : (
          <span>Never used</span>
        )}
        {apiKey.expires_at && (
          <span>
            Expires:{" "}
            {new Date(apiKey.expires_at).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
              year: "numeric",
            })}
          </span>
        )}
      </div>

      {apiKey.scopes.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {apiKey.scopes.map((s) => (
            <span
              key={s}
              className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#4d4880]"
            >
              {s}
            </span>
          ))}
        </div>
      )}

      {canManage && !isRevoked && (
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => onEdit(apiKey)}
            className="text-sm font-medium text-[#3525cd] hover:underline"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => onRotate(apiKey)}
            className="text-sm font-medium text-[#3525cd] hover:underline"
          >
            Rotate
          </button>
          <button
            type="button"
            onClick={() => onRevoke(apiKey)}
            className="text-sm font-medium text-red-600 hover:underline"
          >
            Revoke
          </button>
        </div>
      )}
    </div>
  );
}

export function AdminApiKeysPage() {
  const { hasPermission } = usePermissions();
  const canList = hasPermission("api_keys:list");
  const canManage =
    hasPermission("api_keys:create") && hasPermission("api_keys:revoke");

  const [panel, setPanel] = useState<PanelState>({ kind: "idle" });
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [rotateResult, setRotateResult] = useState<ApiKeyCreated | null>(null);

  const queryClient = useQueryClient();

  const keysQuery = useQuery({
    queryKey: QUERY_API_KEYS,
    queryFn: listApiKeys,
    enabled: canList,
  });

  const revokeMutation = useMutation({
    mutationFn: (keyId: string) => revokeApiKey(keyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_API_KEYS });
      setRevokeTarget(null);
      setRevokeError(null);
    },
    onError: (err) => setRevokeError(getApiErrorMessage(err)),
  });

  const rotateMutation = useMutation({
    mutationFn: (keyId: string) => rotateApiKey(keyId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: QUERY_API_KEYS });
      setRotateResult(result);
    },
    onError: (err) => setRevokeError(getApiErrorMessage(err)),
  });

  if (!canList) {
    return (
      <ForbiddenState
        title="API Keys"
        description="You need the api_keys:list permission to access this page."
        backHref="/dashboard"
      />
    );
  }

  if (keysQuery.isLoading) return <LoadingState />;

  if (keysQuery.isError) {
    if (isForbiddenError(keysQuery.error)) {
      return (
        <ForbiddenState
          title="API Keys"
          description="You do not have access to API key management."
          requestId={extractRequestIdFromError(keysQuery.error)}
          backHref="/dashboard"
        />
      );
    }
    return <ErrorState message={getApiErrorMessage(keysQuery.error)} />;
  }

  const keys = keysQuery.data?.items ?? [];
  const activeKeys = keys.filter((k) => k.status === "active");
  const revokedKeys = keys.filter((k) => k.status === "revoked");

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-4 py-8">
      <div className="flex items-start justify-between">
        <div>
          <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            Admin
          </p>
          <h1 className="text-2xl font-extrabold text-[#2a2640]">API Keys</h1>
          <p className="mt-1 text-sm text-[#68647b]">
            Manage scoped API keys for programmatic access to Rudix.
          </p>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={() => setPanel({ kind: "create" })}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            + Create key
          </button>
        )}
      </div>

      <section>
        <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
          Active keys
          <span className="ml-2 text-sm font-normal text-[#68647b]">
            ({activeKeys.length})
          </span>
        </h2>
        {activeKeys.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[#d7d4e8] p-8 text-center text-sm text-[#68647b]">
            No active API keys.
            {canManage && (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => setPanel({ kind: "create" })}
                  className="font-medium text-[#3525cd] hover:underline"
                >
                  Create one
                </button>{" "}
                to enable programmatic access.
              </>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {activeKeys.map((key) => (
              <ApiKeyCard
                key={key.id}
                apiKey={key}
                canManage={canManage}
                onEdit={(k) => setPanel({ kind: "edit", key: k })}
                onRevoke={(k) => {
                  setRevokeTarget(k);
                  setRevokeError(null);
                }}
                onRotate={(k) => rotateMutation.mutate(k.id)}
              />
            ))}
          </div>
        )}
      </section>

      {revokedKeys.length > 0 && (
        <section>
          <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
            Revoked keys
            <span className="ml-2 text-sm font-normal text-[#68647b]">
              ({revokedKeys.length})
            </span>
          </h2>
          <div className="space-y-3">
            {revokedKeys.map((key) => (
              <ApiKeyCard
                key={key.id}
                apiKey={key}
                canManage={canManage}
                onEdit={() => {}}
                onRevoke={() => {}}
                onRotate={() => {}}
              />
            ))}
          </div>
        </section>
      )}

      {/* Revoke confirmation dialog */}
      {revokeTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="revoke-dialog-title"
        >
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h3
              id="revoke-dialog-title"
              className="mb-2 text-base font-semibold text-[#2a2640]"
            >
              Revoke &ldquo;{revokeTarget.name}&rdquo;?
            </h3>
            <p className="mb-4 text-sm text-[#68647b]">
              The key will stop working immediately. This cannot be undone.
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
                {revokeMutation.isPending ? "Revoking…" : "Revoke key"}
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

      {/* Create / edit slide-over */}
      {panel.kind === "create" && (
        <ApiKeyFormPanel
          mode="create"
          onClose={() => setPanel({ kind: "idle" })}
          onSaved={(result) => {
            setPanel({ kind: "idle" });
            if (result) setRotateResult(result);
          }}
        />
      )}

      {panel.kind === "edit" && (
        <ApiKeyFormPanel
          mode="edit"
          existingKey={panel.key}
          onClose={() => setPanel({ kind: "idle" })}
          onSaved={() => setPanel({ kind: "idle" })}
        />
      )}

      {/* Rotate result banner (reuses same CreatedKeyBanner) */}
      {rotateResult && (
        <CreatedKeyBanner
          result={rotateResult}
          onClose={() => setRotateResult(null)}
        />
      )}
    </div>
  );
}
