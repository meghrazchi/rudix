"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { CookiePreferencesModal } from "@/components/consent/CookiePreferencesModal";
import { useConsentContext } from "@/components/consent/ConsentProvider";

export function CookieConsentBanner() {
  const t = useTranslations("cookieConsent");
  const {
    isLoaded,
    hasResponded,
    preferencesOpen,
    acceptAll,
    rejectNonEssential,
    openPreferences,
    closePreferences,
    decisions,
    updateDecisions,
  } = useConsentContext();

  if (!isLoaded || hasResponded) return null;

  return (
    <>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("bannerLabel")}
        aria-live="polite"
        className="fixed inset-x-0 bottom-0 z-50 border-t border-[#dad8ef] bg-white px-4 py-4 shadow-lg sm:px-6"
      >
        <div className="mx-auto flex max-w-7xl flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex-1">
            <p className="text-sm font-semibold text-[#29263f]">{t("title")}</p>
            <p className="mt-1 text-sm text-[#5f5b76]">
              {t("description")}{" "}
              <Link
                href="/legal/cookies"
                className="font-medium text-[#5d58a8] underline underline-offset-2 hover:text-[#3f3b8a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]"
              >
                {t("cookiePolicyLink")}
              </Link>
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <button
              type="button"
              onClick={openPreferences}
              className="rounded-lg border border-[#c7c4e0] bg-white px-3.5 py-2 text-sm font-medium text-[#29263f] hover:bg-[#f5f4ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]"
            >
              {t("customize")}
            </button>
            <button
              type="button"
              onClick={rejectNonEssential}
              className="rounded-lg border border-[#c7c4e0] bg-white px-3.5 py-2 text-sm font-medium text-[#29263f] hover:bg-[#f5f4ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]"
            >
              {t("rejectNonEssential")}
            </button>
            <button
              type="button"
              onClick={acceptAll}
              className="rounded-lg bg-[#5d58a8] px-3.5 py-2 text-sm font-medium text-white hover:bg-[#4a469a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5d58a8]"
            >
              {t("acceptAll")}
            </button>
          </div>
        </div>
      </div>

      <CookiePreferencesModal
        isOpen={preferencesOpen}
        decisions={decisions}
        onClose={closePreferences}
        onAcceptAll={acceptAll}
        onRejectNonEssential={rejectNonEssential}
        onSave={updateDecisions}
      />
    </>
  );
}
