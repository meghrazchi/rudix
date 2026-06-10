"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { PublicActionLink } from "@/components/public/PublicActionLink";
import type { PublicSiteLinks } from "@/lib/public-site/links";

type PublicFooterProps = {
  links: PublicSiteLinks;
};

export function PublicFooter({ links }: PublicFooterProps) {
  const t = useTranslations("public.footer");
  const groups = [
    {
      heading: t("groups.product"),
      items: [
        { label: t("links.productOverview"), href: links.product },
        { label: t("links.pipelineExplorer"), href: links.app },
        { label: t("links.documentation"), href: links.docs },
      ],
    },
    {
      heading: t("groups.solutions"),
      items: [
        { label: t("links.useCases"), href: links.solutions },
        { label: t("links.security"), href: links.security },
        { label: t("links.pricing"), href: links.pricing },
      ],
    },
    {
      heading: t("groups.company"),
      items: [
        { label: t("links.contact"), href: links.contact },
        { label: t("links.status"), href: links.status },
        { label: t("links.login"), href: links.login },
      ],
    },
  ];

  return (
    <footer
      className="border-t border-[#d8dbe5] bg-[#f2f3f6]"
      aria-label="Footer"
    >
      <div className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-10 lg:grid-cols-[1.3fr_1fr_1fr_1fr] lg:px-8">
        <div>
          <div className="flex items-center gap-2">
            <Image
              src="/brand/rudix-mark.svg"
              alt="Rudix logo"
              width={24}
              height={24}
              className="h-6 w-6"
            />
            <span className="text-sm font-bold text-[#11131a]">Rudix</span>
          </div>
          <p className="mt-3 max-w-xs text-xs leading-6 text-[#626778]">
            {t("tagline")}
          </p>
          <div className="mt-4 flex items-center gap-3">
            <LanguageSwitcher variant="select" />
          </div>
          <p className="mt-3 text-xs text-[#7c8194]">{t("copyright")}</p>
        </div>

        {groups.map((group) => (
          <div key={group.heading}>
            <p className="text-xs font-bold tracking-wide text-[#4f5467] uppercase">
              {group.heading}
            </p>
            <ul className="mt-3 space-y-2 text-sm text-[#4b4f60]">
              {group.items.map((item) => (
                <li key={item.label}>
                  <PublicActionLink
                    href={item.href}
                    className="transition hover:text-[#25283a]"
                  >
                    {item.label}
                  </PublicActionLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </footer>
  );
}
