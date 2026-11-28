"use client";

import { Moon, Monitor, Sun } from "lucide-react";
import { z } from "zod";
import { LOCALE_COOKIE_NAME, type SupportedLocale } from "@/i18n/routing";
import { getLocaleDirection } from "@/i18n/direction";
import { getHtmlLang } from "@/lib/i18n-format";

export function getInitials(name: string | null, email: string | null): string {
  const source = name ?? email ?? "";
  if (!source) return "?";
  const parts = source
    .split(/[\s._@-]+/)
    .filter(Boolean)
    .slice(0, 2);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return (parts[0]?.slice(0, 2) ?? "?").toUpperCase();
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function deriveDisplayName(email: string | null): string {
  if (!email) return "";
  const local = email.split("@")[0] ?? "";
  return local
    .split(/[._-]/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

export const THEME_ICONS = {
  light: Sun,
  dark: Moon,
  system: Monitor,
} as const;

export const VALID_ROLES = ["owner", "admin", "member", "viewer"] as const;

export function applyDisplayLanguage(locale: SupportedLocale): void {
  document.cookie = `${LOCALE_COOKIE_NAME}=${locale}; path=/; samesite=lax; max-age=${60 * 60 * 24 * 365}`;
  document.documentElement.lang = getHtmlLang(locale);
  document.documentElement.dir = getLocaleDirection(locale);
}
export type ValidRole = (typeof VALID_ROLES)[number];

export const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, "Current password is required."),
    newPassword: z
      .string()
      .min(8, "New password must be at least 8 characters.")
      .max(128, "New password must not exceed 128 characters."),
    confirmNewPassword: z.string().min(1, "Please confirm your new password."),
  })
  .refine((d) => d.newPassword === d.confirmNewPassword, {
    message: "Passwords do not match.",
    path: ["confirmNewPassword"],
  });

export type ChangePasswordValues = z.infer<typeof changePasswordSchema>;

// ── Subcomponents ─────────────────────────────────────────────────────────────

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  isPending,
  danger,
  children,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
  danger?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl">
        <h2 className="mb-2 text-base font-bold text-[#1b1b24]">{title}</h2>
        <p className="mb-4 text-sm text-[#464555]">{body}</p>
        {children}
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isPending}
            className="rounded-xl px-4 py-2 text-sm font-semibold text-[#464555] transition-colors hover:bg-[#eae6f4] disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className={[
              "rounded-xl px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60",
              danger
                ? "border border-rose-300 text-rose-700 hover:bg-rose-100"
                : "bg-[#3525cd] text-white hover:bg-[#2a1db0]",
            ].join(" ")}
          >
            {isPending ? "Please wait…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
