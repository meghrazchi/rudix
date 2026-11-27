"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  deactivateServiceAccount,
  listServiceAccounts,
  reactivateServiceAccount,
  type ServiceAccount,
  type ServiceAccountTokenCreated,
} from "@/lib/api/service-accounts";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { usePermissions } from "@/lib/use-permissions";
import { type PanelState } from "@/components/admin/service-accounts/svcShared";
import { CreatedTokenBanner } from "@/components/admin/service-accounts/CreatedTokenBanner";
import { AccountFormPanel } from "@/components/admin/service-accounts/AccountFormPanel";
import { TokenFormPanel } from "@/components/admin/service-accounts/TokenFormPanel";
import { TokensPanel } from "@/components/admin/service-accounts/TokensPanel";
import { ServiceAccountCard } from "@/components/admin/service-accounts/AccountCards";
import { queryKeys } from "@/lib/api/query";

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
    queryKey: queryKeys.adminServiceAccounts.list,
    queryFn: listServiceAccounts,
    enabled: canList,
  });

  const deactivateMutation = useMutation({
    mutationFn: (accountId: string) => deactivateServiceAccount(accountId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminServiceAccounts.list,
      });
      setDeactivateTarget(null);
      setDeactivateError(null);
    },
    onError: (err) => setDeactivateError(getApiErrorMessage(err)),
  });

  const reactivateMutation = useMutation({
    mutationFn: (accountId: string) => reactivateServiceAccount(accountId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminServiceAccounts.list,
      });
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
