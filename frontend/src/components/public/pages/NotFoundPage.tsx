"use client";

import { useTranslations } from "next-intl";

import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import {
  PrimaryLink,
  SecondaryLink,
  SiteSplitHero,
} from "@/components/public/site/SiteBlocks";
import { PUBLIC_ROUTE_PATHS } from "@/lib/public-site/links";

export function NotFoundPage() {
  const t = useTranslations("errors");

  return (
    <PublicMarketingLayout pageLabel={t("pageNotFound")} theme="system">
      <SiteSplitHero
        id="not-found-title"
        badge={t("notFoundBadge")}
        title={t("pageNotFound")}
        description={t("pageNotFoundDescription")}
        actions={
          <>
            <PrimaryLink
              href={PUBLIC_ROUTE_PATHS.home}
              label={t("notFoundHome")}
            />
            <SecondaryLink
              href={PUBLIC_ROUTE_PATHS.contact}
              label={t("notFoundContact")}
            />
          </>
        }
      />
    </PublicMarketingLayout>
  );
}
