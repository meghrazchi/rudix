"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import {
  getOrganizationCapabilities,
  getOrganizationProfile,
} from "@/lib/api/organization";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import type { AuthenticatedSession } from "@/lib/auth-session";
import { isAdminLikeRole } from "@/lib/top-bar";
import {
  buildSwitchWorkspaceUrl,
  orgAvatarColor,
  orgInitials,
  orgPlanLabel,
  roleDisplayLabel,
} from "@/lib/workspace";

type WorkspaceSwitcherCardProps = {
  session: AuthenticatedSession;
};

function isForbiddenOrMissing(error: unknown): boolean {
  if (isApiClientError(error)) {
    return error.status === 403 || error.status === 404 || error.status === 410;
  }
  return false;
}

export function WorkspaceSwitcherCard({ session }: WorkspaceSwitcherCardProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  const isAdmin = isAdminLikeRole(session.role);
  const orgName = session.organizationName ?? session.organizationId ?? null;
  const initials = orgInitials(orgName ?? "");
  const colors = useMemo(() => orgAvatarColor(orgName ?? ""), [orgName]);

  const capabilities = useMemo(() => getOrganizationCapabilities(), []);

  const profileQuery = useQuery({
    queryKey: ["organization", "profile"],
    queryFn: getOrganizationProfile,
    enabled: capabilities.profileEnabled,
    staleTime: 5 * 60_000,
    retry: false,
  });

  const planLabel = orgPlanLabel(profileQuery.data?.plan ?? null);

  const isForbiddenOrg =
    profileQuery.isError && isForbiddenOrMissing(profileQuery.error);

  const switchUrl = useMemo(
    () => buildSwitchWorkspaceUrl(pathname),
    [pathname],
  );

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!session.organizationId) {
    return (
      <div className="mt-8 rounded-xl border border-amber-200 bg-amber-50 p-3">
        <div className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="material-symbols-outlined text-[16px] text-amber-600"
          >
            warning
          </span>
          <p className="text-xs font-bold text-amber-800">No workspace</p>
        </div>
        <p className="mt-1 text-xs text-amber-700">
          Your account is not assigned to a workspace yet.
        </p>
        <Link
          href="/organization-onboarding"
          className="mt-2 block rounded-lg bg-amber-600 px-3 py-1.5 text-center text-xs font-semibold text-white transition hover:bg-amber-700"
        >
          Set up workspace
        </Link>
      </div>
    );
  }

  return (
    <div className="relative mt-8" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Workspace: ${orgName ?? "Unknown"}. Open workspace menu.`}
        className={`w-full rounded-xl border p-3 text-left transition ${
          open
            ? "border-[#3525cd] bg-[#f8f6ff]"
            : "border-[#d8d3f1] bg-white hover:bg-[#f8f6ff]"
        }`}
      >
        <div className="flex items-center gap-2.5">
          <span
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-xs font-bold"
            style={{ backgroundColor: colors.bg, color: colors.text }}
            aria-hidden
          >
            {initials}
          </span>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-slate-800">
              {orgName}
            </p>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-slate-500">
                {roleDisplayLabel(session.role)}
              </span>
              {planLabel ? (
                <>
                  <span
                    className="h-1 w-1 rounded-full bg-slate-300"
                    aria-hidden
                  />
                  <span className="rounded-full bg-[#ece9ff] px-1.5 py-0.5 text-[10px] font-bold text-[#3525cd]">
                    {planLabel}
                  </span>
                </>
              ) : null}
              {isForbiddenOrg ? (
                <span
                  aria-label="Workspace access issue"
                  className="material-symbols-outlined text-[14px] text-amber-500"
                  title="Workspace access issue"
                >
                  warning
                </span>
              ) : null}
            </div>
          </div>

          <ChevronsUpDownSvg
            className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
          />
        </div>
      </button>

      {open ? (
        <div
          role="menu"
          aria-label="Workspace menu"
          className="absolute right-0 bottom-full left-0 z-50 mb-1 overflow-hidden rounded-xl border border-[#d7d4e8] bg-white shadow-xl"
        >
          <div className="border-b border-[#f0eeff] px-3 py-2.5">
            <p className="text-[10px] font-bold tracking-[0.14em] text-[#5d58a8] uppercase">
              Current workspace
            </p>
            <p className="mt-0.5 truncate text-sm font-semibold text-[#2a2640]">
              {orgName}
            </p>
            {session.organizationId ? (
              <p className="truncate font-mono text-[10px] text-[#7a7693]">
                {session.organizationId}
              </p>
            ) : null}
            {isForbiddenOrg ? (
              <p className="mt-1 text-[11px] text-amber-600">
                {getApiErrorMessage(profileQuery.error) ||
                  "Workspace access issue detected."}
              </p>
            ) : null}
          </div>

          <div className="p-1.5">
            {isAdmin ? (
              <>
                <Link
                  href="/settings?tab=organization"
                  role="menuitem"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                >
                  <OrgSettingsSvg className="h-3.5 w-3.5 shrink-0 text-[#5d58a8]" />
                  Organization settings
                </Link>
                <Link
                  href="/settings?tab=security"
                  role="menuitem"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
                >
                  <SecuritySvg className="h-3.5 w-3.5 shrink-0 text-[#5d58a8]" />
                  Security settings
                </Link>
                <div className="my-1 border-t border-[#f0eeff]" />
              </>
            ) : null}

            <Link
              href={switchUrl}
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f5f3ff]"
            >
              <SwitchSvg className="h-3.5 w-3.5 shrink-0 text-[#5d58a8]" />
              Sign in to another workspace
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ChevronsUpDownSvg({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M7 15l5 5 5-5M7 9l5-5 5 5" />
    </svg>
  );
}

function OrgSettingsSvg({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

function SecuritySvg({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 3.6L5.6 6.5v5.2c0 4.1 2.5 7.8 6.4 8.9 3.9-1.1 6.4-4.8 6.4-8.9V6.5Z" />
      <path d="m9.3 12 1.8 1.8 3.6-3.7" />
    </svg>
  );
}

function SwitchSvg({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M17 3l4 4-4 4M3 7h18" />
      <path d="M7 21l-4-4 4-4M21 17H3" />
    </svg>
  );
}
