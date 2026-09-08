"use client";

import { useTranslations } from "next-intl";

import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";

export function NotFoundPage() {
  const t = useTranslations("errors");

  return (
    <PublicMarketingLayout pageLabel={t("pageNotFound")}>
      <div className="mx-auto max-w-2xl px-6 py-24 text-center">
        <h1 className="text-3xl font-bold text-[#29263f]">
          {t("pageNotFound")}
        </h1>
        <p className="mt-3 text-sm text-[#5f5b76]">
          {t("pageNotFoundDescription")}
        </p>
      </div>
    </PublicMarketingLayout>
  );
}
