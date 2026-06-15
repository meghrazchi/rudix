"use client";

import type { RefObject } from "react";
import { LogOut, Settings, Shield, User } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import type { AuthenticatedSession } from "@/lib/auth-session";
import { isAdminLikeRole } from "@/lib/top-bar";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function profileDisplayName(session: AuthenticatedSession): string {
  if (session.email && session.email.includes("@")) {
    return session.email.split("@")[0] ?? "User";
  }
  return session.email ?? session.userId;
}

function profileInitials(displayName: string): string {
  const parts = displayName
    .split(/[\s._-]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);

  if (parts.length === 0) return "U";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

function useRoleLabel() {
  const t = useTranslations("appShell.roles");
  return function roleLabel(role: AuthenticatedSession["role"]): string {
    if (role === "owner") return t("owner");
    if (role === "admin") return t("admin");
    if (role === "member") return t("member");
    return t("viewer");
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type ProfileMenuProps = {
  session: AuthenticatedSession;
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
  onSignOut: () => void;
  menuRef: RefObject<HTMLDivElement | null>;
};

export function ProfileMenu({
  session,
  isOpen,
  onToggle,
  onClose,
  onSignOut,
  menuRef,
}: ProfileMenuProps) {
  const t = useTranslations("appShell");
  const tNav = useTranslations("navigation");
  const tSettingsTabs = useTranslations("settings.tabs");
  const tAuth = useTranslations("auth");
  const getRoleLabel = useRoleLabel();

  const displayName = profileDisplayName(session);
  const initials = profileInitials(displayName);

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={onToggle}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label={t("profileMenu")}
        className="inline-flex h-10 w-10 cursor-pointer items-center justify-center rounded-full border border-[#ded9ef] bg-white text-[#4a4662] shadow-sm transition hover:border-[#c9c2e3] hover:bg-[#f7f5ff] focus-visible:ring-2 focus-visible:ring-[#3525cd]/40 focus-visible:outline-none"
      >
        <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#f4f2ff] text-xs font-bold text-[#3525cd]">
          {initials}
        </span>
      </button>

      {isOpen ? (
        <div
          role="menu"
          aria-label={t("profileMenuPanel")}
          className="absolute right-0 z-50 mt-3 w-[340px] overflow-hidden rounded-[24px] border border-[#ded9ef] bg-white shadow-[0_24px_60px_rgba(40,23,90,0.16)]"
        >
          {/* Identity header */}
          <div className="bg-[#f7f5ff] px-4 py-4">
            <div className="flex items-start gap-3">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-white text-lg font-bold text-[#3525cd] shadow-sm ring-1 ring-[#e0daf0]">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-base font-semibold text-[#2f2a46]">
                    {displayName}
                  </p>
                  <span className="inline-flex items-center rounded-full bg-[#ebe8ff] px-2 py-0.5 text-[11px] font-semibold text-[#4c3fd1]">
                    {getRoleLabel(session.role)}
                  </span>
                </div>
                <p className="mt-1 truncate text-sm text-[#68647b]">
                  {session.email ?? session.userId}
                </p>
                <p className="mt-1 text-sm text-[#68647b]">
                  {t("organization")}:{" "}
                  {session.organizationName ??
                    session.organizationId ??
                    t("unassigned")}
                </p>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="p-2">
            <Link
              href="/user/profile"
              role="menuitem"
              data-menu-autofocus="true"
              onClick={onClose}
              className="flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-semibold text-[#3f3b58] transition hover:bg-[#f5f3ff]"
            >
              <User
                className="h-4 w-4 shrink-0 text-[#7b76a0]"
                strokeWidth={1.9}
                aria-hidden
              />
              {tSettingsTabs("profile")}
            </Link>

            <Link
              href="/settings"
              role="menuitem"
              onClick={onClose}
              className="flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-semibold text-[#3f3b58] transition hover:bg-[#f5f3ff]"
            >
              <Settings
                className="h-4 w-4 shrink-0 text-[#7b76a0]"
                strokeWidth={1.9}
                aria-hidden
              />
              {tNav("settings")}
            </Link>

            {isAdminLikeRole(session.role) ? (
              <Link
                href="/admin"
                role="menuitem"
                onClick={onClose}
                className="flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-semibold text-[#3f3b58] transition hover:bg-[#f5f3ff]"
              >
                <Shield
                  className="h-4 w-4 shrink-0 text-[#7b76a0]"
                  strokeWidth={1.9}
                  aria-hidden
                />
                {tNav("adminUsage")}
              </Link>
            ) : null}

            <button
              type="button"
              role="menuitem"
              onClick={() => {
                onClose();
                onSignOut();
              }}
              className="mt-1 flex w-full items-center gap-2.5 rounded-xl border border-[#f5c6cb] bg-[#fff7f7] px-3 py-2.5 text-left text-sm font-semibold text-[#c62828] transition hover:bg-[#ffecec]"
            >
              <LogOut className="h-4 w-4 shrink-0" strokeWidth={1.9} aria-hidden />
              {tAuth("signOut")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
