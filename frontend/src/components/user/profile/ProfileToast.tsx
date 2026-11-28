"use client";

import { useUserProfileController } from "@/components/user/profile/useUserProfileController";

export function ProfileToast({
  ctl,
}: {
  ctl: ReturnType<typeof useUserProfileController>;
}) {
  const { showToast, toastMessage } = ctl;

  return (
    <>
      <div
        aria-live="polite"
        aria-atomic="true"
        className={[
          "fixed right-8 bottom-8 z-50 flex items-center gap-3 rounded-2xl px-6 py-4 shadow-2xl transition-all duration-500",
          "bg-[#302f39] text-white",
          showToast
            ? "translate-y-0 opacity-100"
            : "pointer-events-none translate-y-20 opacity-0",
        ].join(" ")}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="shrink-0 text-[#c3c0ff]"
          aria-hidden="true"
        >
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
        <span className="text-sm font-semibold">{toastMessage}</span>
      </div>
    </>
  );
}
