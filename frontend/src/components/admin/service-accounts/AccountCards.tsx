"use client";

import {
  type ServiceAccount,
  type ServiceAccountToken,
} from "@/lib/api/service-accounts";
import { ENV_LABELS } from "@/components/admin/service-accounts/svcShared";

export function TokenCard({
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

export function ServiceAccountCard({
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
