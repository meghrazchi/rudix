"use client";

import { useTranslations } from "next-intl";

export function SkipLink() {
  const t = useTranslations("appShell");
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-[200] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-[#3525cd] focus:shadow-lg focus:ring-2 focus:ring-[#3525cd] focus:outline-none"
    >
      {t("skipToMainContent")}
    </a>
  );
}
