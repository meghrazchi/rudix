"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
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

const EXPIRY_OPTIONS: {
  value: ExpiryOption;
  hours: number | null;
}[] = [
  { value: "never", hours: null },
  { value: "24h", hours: 24 },
  { value: "7d", hours: 168 },
  { value: "30d", hours: 720 },
];

function buildShareUrl(token: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/chat/shared/${encodeURIComponent(token)}`;
}

function formatExpiry(expiresAt: string | null, never: string): string {
  if (!expiresAt) return never;
  try {
    return new Date(expiresAt).toLocaleString();
  } catch {
    return expiresAt;
  }
}

export function ShareModal({ sessionId, sessionTitle, onClose }: Props) {
  const t = useTranslations("chat.share");
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
      void queryClient.invalidateQueries({
        queryKey: ["chat", "shares", sessionId],
      });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (shareId: string) => revokeChatShare(sessionId, shareId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["chat", "shares", sessionId],
      });
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
  const displayTitle = sessionTitle?.trim() || t("sessionModal.untitled");

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label={t("sessionModal.title")}
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
              {t("sessionModal.title")}
            </h2>
            <p className="mt-0.5 truncate text-xs text-[#6a6780]">
              {displayTitle}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("close")}
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
            {t("sessionModal.notice")}
          </div>

          {/* Create new share */}
          <div className="space-y-2">
            <p className="text-xs font-semibold tracking-wide text-[#464555] uppercase">
              {t("createLink")}
            </p>
            <div className="flex items-center gap-2">
              <label
                htmlFor="share-expiry"
                className="shrink-0 text-xs text-[#6a6780]"
              >
                {t("expiresLabel")}
              </label>
              <select
                id="share-expiry"
                value={selectedExpiry}
                onChange={(e) =>
                  setSelectedExpiry(e.target.value as ExpiryOption)
                }
                className="rounded border border-[#d2cee6] bg-white px-2 py-1 text-xs text-[#2f2a46] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              >
                {EXPIRY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {t(`expiry.${opt.value}`)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={createMutation.isPending}
                onClick={() => createMutation.mutate()}
                className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {createMutation.isPending ? t("creating") : t("generate")}
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
            <p className="text-xs text-[#6a6780]">{t("loadingLinks")}</p>
          ) : sharesQuery.isError ? (
            <p className="text-xs text-rose-700">
              {getApiErrorMessage(sharesQuery.error)}
            </p>
          ) : shares.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs font-semibold tracking-wide text-[#464555] uppercase">
                {t("activeLinks")}
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
                        {t("expiresValue", {
                          value: formatExpiry(
                            share.expires_at,
                            t("expiry.never"),
                          ),
                        })}
                      </p>
                    </div>
                    <button
                      type="button"
                      aria-label={t("copyLink")}
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
                      aria-label={t("revokeLink")}
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
              {t("sessionModal.noActive")}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
