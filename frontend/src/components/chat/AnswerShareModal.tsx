"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createAnswerShare,
  listAnswerShares,
  revokeAnswerShare,
  type AnswerShareAccessMode,
  type AnswerShareResponse,
} from "@/lib/api/answer-shares";
import { getApiErrorMessage } from "@/lib/api/errors";

type Props = {
  messageId: string;
  onClose: () => void;
};

type ExpiryOption = "never" | "24h" | "7d" | "30d";

const EXPIRY_OPTIONS: {
  label: string;
  value: ExpiryOption;
  hours: number | null;
}[] = [
  { label: "Never", value: "never", hours: null },
  { label: "24 hours", value: "24h", hours: 24 },
  { label: "7 days", value: "7d", hours: 168 },
  { label: "30 days", value: "30d", hours: 720 },
];

function buildAnswerShareUrl(token: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/chat/answer-shared/${encodeURIComponent(token)}`;
}

function formatExpiry(expiresAt: string | null): string {
  if (!expiresAt) return "Never";
  try {
    return new Date(expiresAt).toLocaleString();
  } catch {
    return expiresAt;
  }
}

function accessModeLabel(mode: AnswerShareAccessMode): string {
  if (mode === "specific_users") return "Specific users";
  return "Organization";
}

export function AnswerShareModal({ messageId, onClose }: Props) {
  const queryClient = useQueryClient();
  const overlayRef = useRef<HTMLDivElement>(null);

  const [selectedExpiry, setSelectedExpiry] = useState<ExpiryOption>("never");
  const [accessMode, setAccessMode] = useState<AnswerShareAccessMode>("org_only");
  const [allowedUsersInput, setAllowedUsersInput] = useState("");
  const [passwordInput, setPasswordInput] = useState("");
  const [usePassword, setUsePassword] = useState(false);
  const [copiedShareId, setCopiedShareId] = useState<string | null>(null);

  const sharesQuery = useQuery({
    queryKey: ["chat", "answer-shares", messageId],
    queryFn: () => listAnswerShares(messageId),
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const option = EXPIRY_OPTIONS.find((o) => o.value === selectedExpiry);
      const allowedIds =
        accessMode === "specific_users"
          ? allowedUsersInput
              .split(/[\s,]+/)
              .map((s) => s.trim())
              .filter(Boolean)
          : [];
      return createAnswerShare(messageId, {
        access_mode: accessMode,
        allowed_user_ids: allowedIds,
        password: usePassword && passwordInput ? passwordInput : null,
        expires_in_hours: option?.hours ?? undefined,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["chat", "answer-shares", messageId],
      });
      setPasswordInput("");
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (shareId: string) => revokeAnswerShare(messageId, shareId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["chat", "answer-shares", messageId],
      });
    },
  });

  const handleCopy = useCallback(async (share: AnswerShareResponse) => {
    try {
      await navigator.clipboard.writeText(buildAnswerShareUrl(share.token));
      setCopiedShareId(share.share_id);
      setTimeout(() => setCopiedShareId(null), 2000);
    } catch {
      // clipboard unavailable
    }
  }, []);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const shares = sharesQuery.data?.items ?? [];

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label="Share answer"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div className="w-full max-w-lg rounded-2xl border border-[#d7d4e8] bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#e2dff1] px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-[#2a2640]">
              Share answer
            </h2>
            <p className="mt-0.5 text-xs text-[#6a6780]">
              Create a permission-controlled link to this Q&amp;A turn.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-[#6a6780] hover:bg-[#f5f2ff] hover:text-[#2f2a46]"
          >
            <span
              className="material-symbols-outlined text-[20px]"
              aria-hidden="true"
            >
              close
            </span>
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 px-5 py-4">
          <div className="rounded-lg border border-[#f5c842]/60 bg-[#fffbe6] px-3 py-2 text-xs text-[#7a6000]">
            <span
              className="material-symbols-outlined mr-1 align-middle text-[14px]"
              aria-hidden="true"
            >
              lock
            </span>
            Viewers must be signed-in members of your organization. Citations
            show excerpt text only — underlying document IDs are not exposed.
          </div>

          {/* Access mode */}
          <div className="space-y-1.5">
            <p className="text-xs font-semibold tracking-wide text-[#464555] uppercase">
              Access
            </p>
            <div className="flex gap-2">
              {(["org_only", "specific_users"] as AnswerShareAccessMode[]).map(
                (mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setAccessMode(mode)}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
                      accessMode === mode
                        ? "border-[#3525cd] bg-[#3525cd] text-white"
                        : "border-[#d2cee6] bg-white text-[#3e376f] hover:bg-[#f5f3ff]"
                    }`}
                  >
                    {accessModeLabel(mode)}
                  </button>
                ),
              )}
            </div>
            {accessMode === "specific_users" && (
              <div>
                <label
                  htmlFor="answer-share-users"
                  className="mb-1 block text-[11px] text-[#6a6780]"
                >
                  User IDs (comma or space separated)
                </label>
                <textarea
                  id="answer-share-users"
                  value={allowedUsersInput}
                  onChange={(e) => setAllowedUsersInput(e.target.value)}
                  placeholder="uuid-1, uuid-2, ..."
                  rows={2}
                  className="w-full rounded border border-[#d2cee6] px-2 py-1.5 font-mono text-xs text-[#2f2a46] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                />
              </div>
            )}
          </div>

          {/* Optional password */}
          <div className="space-y-1.5">
            <label className="flex cursor-pointer items-center gap-2 text-xs text-[#464555]">
              <input
                type="checkbox"
                checked={usePassword}
                onChange={(e) => setUsePassword(e.target.checked)}
                className="h-3.5 w-3.5 accent-[#3525cd]"
              />
              <span className="font-semibold">Require password</span>
            </label>
            {usePassword && (
              <input
                type="password"
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                placeholder="Enter link password (min 4 characters)"
                className="w-full rounded border border-[#d2cee6] px-2 py-1.5 text-xs text-[#2f2a46] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                minLength={4}
                maxLength={128}
              />
            )}
          </div>

          {/* Expiry + generate */}
          <div className="space-y-2">
            <p className="text-xs font-semibold tracking-wide text-[#464555] uppercase">
              Create link
            </p>
            <div className="flex items-center gap-2">
              <label
                htmlFor="answer-share-expiry"
                className="shrink-0 text-xs text-[#6a6780]"
              >
                Expires:
              </label>
              <select
                id="answer-share-expiry"
                value={selectedExpiry}
                onChange={(e) =>
                  setSelectedExpiry(e.target.value as ExpiryOption)
                }
                className="rounded border border-[#d2cee6] bg-white px-2 py-1 text-xs text-[#2f2a46] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              >
                {EXPIRY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={
                  createMutation.isPending ||
                  (usePassword && passwordInput.length < 4) ||
                  (accessMode === "specific_users" &&
                    !allowedUsersInput.trim())
                }
                onClick={() => createMutation.mutate()}
                className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {createMutation.isPending ? "Creating..." : "Generate link"}
              </button>
            </div>
            {createMutation.isError ? (
              <p className="text-xs text-rose-700">
                {getApiErrorMessage(createMutation.error)}
              </p>
            ) : null}
          </div>

          {/* Active shares */}
          {sharesQuery.isLoading ? (
            <p className="text-xs text-[#6a6780]">Loading share links...</p>
          ) : sharesQuery.isError ? (
            <p className="text-xs text-rose-700">
              {getApiErrorMessage(sharesQuery.error)}
            </p>
          ) : shares.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs font-semibold tracking-wide text-[#464555] uppercase">
                Active links
              </p>
              <ul className="space-y-2">
                {shares.map((share) => (
                  <li
                    key={share.share_id}
                    className="flex items-center gap-2 rounded-lg border border-[#e2dff1] bg-[#faf9ff] px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono text-[11px] text-[#3525cd]">
                        {buildAnswerShareUrl(share.token)}
                      </p>
                      <p className="mt-0.5 text-[10px] text-[#6a6780]">
                        {accessModeLabel(share.access_mode)} ·{" "}
                        {share.has_password ? "Password protected · " : ""}
                        Expires: {formatExpiry(share.expires_at)}
                      </p>
                    </div>
                    <button
                      type="button"
                      aria-label="Copy link"
                      onClick={() => void handleCopy(share)}
                      className="shrink-0 rounded p-1 text-[#6a6780] hover:bg-[#e9e6f8] hover:text-[#3525cd]"
                    >
                      <span
                        className="material-symbols-outlined text-[16px]"
                        aria-hidden="true"
                      >
                        {copiedShareId === share.share_id
                          ? "check"
                          : "content_copy"}
                      </span>
                    </button>
                    <button
                      type="button"
                      aria-label="Revoke link"
                      disabled={revokeMutation.isPending}
                      onClick={() => revokeMutation.mutate(share.share_id)}
                      className="shrink-0 rounded p-1 text-[#6a6780] hover:bg-rose-100 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <span
                        className="material-symbols-outlined text-[16px]"
                        aria-hidden="true"
                      >
                        link_off
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-xs text-[#6a6780]">
              No active share links for this answer.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
