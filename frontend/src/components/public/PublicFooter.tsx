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
        { label: t("links.changelog"), href: links.changelog },
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

  const legalLinks = [
    { label: t("links.privacy"), href: links.privacy },
    { label: t("links.terms"), href: links.terms },
    { label: t("links.cookies"), href: links.cookies },
    { label: t("links.acceptableUse"), href: links.acceptableUse },
    { label: t("links.securityDisclosure"), href: links.securityDisclosure },
  ];

  return (
    <footer
      className="border-site-border bg-site-canvas border-t"
      aria-label="Footer"
    >
      <div className="mx-auto grid w-full max-w-7xl gap-10 px-4 py-14 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr] lg:px-8">
        <div className="sm:col-span-2 lg:col-span-1">
          <div className="flex items-center gap-2">
            <Image
              src="/brand/rudix-mark.svg"
              alt="Rudix logo"
              width={24}
              height={24}
              className="h-6 w-6"
            />
            <span className="text-site-ink text-[15px] font-semibold tracking-tight">
              Rudix
            </span>
          </div>
          <p className="text-site-ink-muted mt-3 max-w-xs text-sm leading-6">
            {t("tagline")}
          </p>
        </div>

        {groups.map((group) => (
          <div key={group.heading}>
            <p className="text-site-ink text-sm font-medium">{group.heading}</p>
            <ul className="mt-4 space-y-2.5 text-sm">
              {group.items.map((item) => (
                <li key={item.label}>
                  <PublicActionLink
                    href={item.href}
                    className="text-site-ink-muted hover:text-site-ink rounded-sm transition-colors"
                  >
                    {item.label}
                  </PublicActionLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="border-site-border border-t">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6 md:flex-row md:items-center md:justify-between lg:px-8">
          <p className="text-site-ink-subtle text-xs">{t("copyright")}</p>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            {legalLinks.map((item) => (
              <PublicActionLink
                key={item.label}
                href={item.href}
                className="text-site-ink-subtle hover:text-site-ink rounded-sm text-xs transition-colors"
              >
                {item.label}
              </PublicActionLink>
            ))}
            <LanguageSwitcher
              variant="select"
              selectId="public-footer-language"
              selectClassName="rounded-full border border-site-border bg-site-surface px-2.5 py-1 text-xs font-medium text-site-ink-muted transition hover:text-site-ink focus:border-site-accent focus:ring-2 focus:ring-site-accent/25 focus:outline-none"
            />
          </div>
        </div>
      </div>
    </footer>
  );
}
