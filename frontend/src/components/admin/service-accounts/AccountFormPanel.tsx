"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  createServiceAccount,
  updateServiceAccount,
  VALID_ENVIRONMENTS,
  VALID_SCOPES,
  type ServiceAccount,
} from "@/lib/api/service-accounts";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  SCOPE_LABELS,
  ENV_LABELS,
} from "@/components/admin/service-accounts/svcShared";
import { queryKeys } from "@/lib/api/query";

export function AccountFormPanel({
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
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminServiceAccounts.list,
      });
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
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminServiceAccounts.list,
      });
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
