import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SiteIcon,
  TEXT_LINK_CLASS,
} from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

export function ProductCta({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.product.cta");

  return (
    <section
      aria-labelledby="product-cta-title"
      className="bg-site-surface border-site-border border-t px-4 py-24 lg:px-8 lg:py-32"
    >
      <div className="mx-auto max-w-3xl text-center">
        <h2
          id="product-cta-title"
          className="text-site-ink text-3xl font-semibold tracking-tight text-balance break-words hyphens-auto md:text-5xl lg:hyphens-manual"
        >
          {t("heading")}
        </h2>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <PublicActionLink
            href={links.requestDemo}
            className={`${PRIMARY_BUTTON_CLASS} w-full sm:w-auto`}
          >
            {t("primaryCta")}
            <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
          </PublicActionLink>
          <PublicActionLink
            href={links.docs}
            className={`${SECONDARY_BUTTON_CLASS} w-full sm:w-auto`}
          >
            {t("secondaryCta")}
          </PublicActionLink>
          <PublicActionLink
            href={links.security}
            className={`${TEXT_LINK_CLASS} px-3 py-2`}
          >
            {t("tertiaryCta")}
            <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}
