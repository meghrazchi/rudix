"use client";

import Link from "next/link";

type OnboardingCtaBannerProps = {
  title: string;
  description: string;
  actionLabel: string;
  actionHref?: string;
  onAction?: () => void;
  secondaryLabel?: string;
  secondaryHref?: string;
};

/**
 * Lightweight contextual nudge shown in empty states to guide new users.
 * Links to the relevant onboarding step or opens the Getting Started checklist.
 */
export function OnboardingCtaBanner({
  title,
  description,
  actionLabel,
  actionHref,
  onAction,
  secondaryLabel,
  secondaryHref,
}: OnboardingCtaBannerProps) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-[#d9d4f0] bg-[#f5f3ff] px-4 py-3">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#ece9ff]">
        <svg
          className="h-3.5 w-3.5 text-[#3525cd]"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.2}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M9 11l3 3L22 4" />
          <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
        </svg>
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-[#2a2640]">{title}</p>
        <p className="mt-0.5 text-xs text-[#68647b]">{description}</p>
        <div className="mt-2 flex flex-wrap gap-3">
          {actionHref ? (
            <Link
              href={actionHref}
              className="text-xs font-semibold text-[#3525cd] hover:underline"
            >
              {actionLabel} →
            </Link>
          ) : onAction ? (
            <button
              type="button"
              onClick={onAction}
              className="text-xs font-semibold text-[#3525cd] hover:underline"
            >
              {actionLabel} →
            </button>
          ) : null}
          {secondaryLabel && secondaryHref ? (
            <Link
              href={secondaryHref}
              className="text-xs text-[#68647b] hover:underline"
            >
              {secondaryLabel}
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}
