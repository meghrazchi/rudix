"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createChatShare,
  listChatShares,
  revokeChatShare,
  type ChatShareResponse,
} from "@/lib/api/shares";
import { getApiErrorMessage } from "@/lib/api/errors";

type Props = {
  sessionId: string;
  sessionTitle: string | null | undefined;
  onClose: () => void;
};

type ExpiryOption = "never" | "24h" | "7d" | "30d";

const EXPIRY_OPTIONS: { label: string; value: ExpiryOption; hours: number | null }[] = [
  { label: "Never", value: "never", hours: null },
  { label: "24 hours", value: "24h", hours: 24 },
  { label: "7 days", value: "7d", hours: 168 },
  { label: "30 days", value: "30d", hours: 720 },
];

function buildShareUrl(token: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/chat/shared/${encodeURIComponent(token)}`;
}

function formatExpiry(expiresAt: string | null): string {
  if (!expiresAt) return "Never";
  try {
    return new Date(expiresAt).toLocaleString();
  } catch {
    return expiresAt;
  }
}

export function ShareModal({ sessionId, sessionTitle, onClose }: Props) {
  const queryClient = useQueryClient();
  const overlayRef = useRef<HTMLDivElement>(null);
  const [selectedExpiry, setSelectedExpiry] = useState<ExpiryOption>("never");
  const [copiedShareId, setCopiedShareId] = useState<string | null>(null);

  const sharesQuery = useQuery({
    queryKey: ["chat", "shares", sessionId],
    queryFn: () => listChatShares(sessionId),
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const option = EXPIRY_OPTIONS.find((o) => o.value === selectedExpiry);
      return createChatShare(sessionId, {
        expires_in_hours: option?.hours ?? undefined,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["chat", "shares", sessionId] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (shareId: string) => revokeChatShare(sessionId, shareId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["chat", "shares", sessionId] });
    },
  });

  const handleCopy = useCallback(async (share: ChatShareResponse) => {
    try {
      await navigator.clipboard.writeText(buildShareUrl(share.token));
      setCopiedShareId(share.share_id);
      setTimeout(() => setCopiedShareId(null), 2000);
    } catch {
      // clipboard unavailable — ignore
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
  const displayTitle = sessionTitle?.trim() || "Untitled session";

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label="Share session"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div className="w-full max-w-lg rounded-2xl border border-[#d7d4e8] bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#e2dff1] px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-[#2a2640]">Share session</h2>
            <p className="mt-0.5 truncate text-xs text-[#6a6780]">{displayTitle}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-[#6a6780] hover:bg-[#f5f2ff] hover:text-[#2f2a46]"
          >
            <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
              close
            </span>
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 px-5 py-4">
          <div className="rounded-lg border border-[#f5c842]/60 bg-[#fffbe6] px-3 py-2 text-xs text-[#7a6000]">
            <span className="material-symbols-outlined mr-1 align-middle text-[14px]" aria-hidden="true">
              lock
            </span>
            Share links are only accessible to signed-in members of your organization.
          </div>

          {/* Create new share */}
          <div className="space-y-2">
            <p className="text-xs font-semibold text-[#464555] uppercase tracking-wide">
              Create link
            </p>
            <div className="flex items-center gap-2">
              <label htmlFor="share-expiry" className="text-xs text-[#6a6780] shrink-0">
                Expires:
              </label>
              <select
                id="share-expiry"
                value={selectedExpiry}
                onChange={(e) => setSelectedExpiry(e.target.value as ExpiryOption)}
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
                disabled={createMutation.isPending}
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
              <p className="text-xs font-semibold text-[#464555] uppercase tracking-wide">
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
                        {buildShareUrl(share.token)}
                      </p>
                      <p className="mt-0.5 text-[10px] text-[#6a6780]">
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
                        {copiedShareId === share.share_id ? "check" : "content_copy"}
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
            <p className="text-xs text-[#6a6780]">No active share links for this session.</p>
          )}
        </div>
      </div>
    </div>
  );
}
