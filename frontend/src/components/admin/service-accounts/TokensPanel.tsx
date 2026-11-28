"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listTokens,
  revokeToken,
  rotateToken,
  type ServiceAccount,
  type ServiceAccountToken,
  type ServiceAccountTokenCreated,
} from "@/lib/api/service-accounts";
import { getApiErrorMessage } from "@/lib/api/errors";
import { ENV_LABELS } from "@/components/admin/service-accounts/svcShared";
import { TokenCard } from "@/components/admin/service-accounts/AccountCards";
import { queryKeys } from "@/lib/api/query";

export function TokensPanel({
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
    queryKey: queryKeys.adminServiceAccounts.tokens(account.id),
    queryFn: () => listTokens(account.id),
  });

  const revokeMutation = useMutation({
    mutationFn: (tokenId: string) => revokeToken(account.id, tokenId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminServiceAccounts.tokens(account.id),
      });
      setRevokeTarget(null);
      setRevokeError(null);
    },
    onError: (err) => setRevokeError(getApiErrorMessage(err)),
  });

  const rotateMutation = useMutation({
    mutationFn: (tokenId: string) => rotateToken(account.id, tokenId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminServiceAccounts.tokens(account.id),
      });
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
