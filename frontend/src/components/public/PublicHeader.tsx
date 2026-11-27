"use client";

import Image from "next/image";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import {
  PUBLIC_FOCUS_RING_CLASS,
  PublicActionLink,
} from "@/components/public/PublicActionLink";
import type { PublicSiteLinks } from "@/lib/public-site/links";

type PublicHeaderProps = {
  links: PublicSiteLinks;
};

export function PublicHeader({ links }: PublicHeaderProps) {
  const t = useTranslations("public.nav");
  const navItems = [
    { label: t("items.product"), href: links.product },
    { label: t("items.solutions"), href: links.solutions },
    { label: t("items.security"), href: links.security },
    { label: t("items.pricing"), href: links.pricing },
  ];
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const firstMobileLinkRef = useRef<HTMLAnchorElement | null>(null);
  const mobileMenuId = useId();

  useEffect(() => {
    if (!isMobileMenuOpen) {
      return;
    }

    firstMobileLinkRef.current?.focus();
  }, [isMobileMenuOpen]);

  useEffect(() => {
    if (!isMobileMenuOpen) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      setIsMobileMenuOpen(false);
      requestAnimationFrame(() => {
        menuButtonRef.current?.focus();
      });
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isMobileMenuOpen]);

  const switcherClassName =
    "rounded-full border border-site-border bg-site-surface px-2.5 py-1 text-xs font-medium text-site-ink-muted transition hover:text-site-ink focus:border-site-accent focus:ring-2 focus:ring-site-accent/25 focus:outline-none";

  return (
    <header className="border-site-border bg-site-canvas/80 sticky top-0 z-30 border-b backdrop-blur-md">
      <div className="mx-auto grid h-16 w-full max-w-7xl grid-cols-[1fr_auto] items-center px-4 md:grid-cols-[1fr_auto_1fr] lg:px-8">
        <PublicActionLink
          href={links.home}
          className="flex items-center gap-2 justify-self-start rounded-md"
          ariaLabel="Rudix home"
        >
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
        </PublicActionLink>

        <nav
          aria-label={t("primaryNav")}
          className="hidden items-center gap-1 md:flex"
        >
          {navItems.map((item) => (
            <PublicActionLink
              key={item.label}
              href={item.href}
              className="text-site-ink-muted hover:bg-site-muted hover:text-site-ink rounded-full px-3 py-1.5 text-sm transition-colors"
            >
              {item.label}
            </PublicActionLink>
          ))}
        </nav>

        <div className="hidden items-center gap-3 justify-self-end md:flex">
          <LanguageSwitcher
            variant="select"
            selectId="public-header-language"
            selectClassName={switcherClassName}
          />
          <PublicActionLink
            href={links.login}
            className="text-site-ink-muted hover:text-site-ink rounded-md px-1 text-sm transition-colors"
          >
            {t("login")}
          </PublicActionLink>
          <PublicActionLink
            href={links.requestDemo}
            className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover inline-flex h-9 items-center rounded-full px-4 text-sm font-medium transition-colors"
          >
            {t("requestDemo")}
          </PublicActionLink>
        </div>

        <button
          ref={menuButtonRef}
          type="button"
          aria-expanded={isMobileMenuOpen}
          aria-controls={mobileMenuId}
          aria-label={isMobileMenuOpen ? t("closeMenu") : t("openMenu")}
          className={`border-site-border bg-site-surface text-site-ink justify-self-end rounded-full border p-2 md:hidden ${PUBLIC_FOCUS_RING_CLASS}`}
          onClick={() => {
            setIsMobileMenuOpen((previous) => !previous);
          }}
        >
          {isMobileMenuOpen ? (
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4">
              <path
                d="M6 6 18 18M18 6 6 18"
                stroke="currentColor"
                strokeWidth="1.8"
              />
            </svg>
          ) : (
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4">
              <path
                d="M4 7h16M4 12h16M4 17h16"
                stroke="currentColor"
                strokeWidth="1.8"
              />
            </svg>
          )}
        </button>
      </div>

      {isMobileMenuOpen ? (
        <div id={mobileMenuId} className="block md:hidden">
          <nav
            aria-label={t("mobileNav")}
            className="border-site-border bg-site-canvas border-t px-4 py-4"
          >
            <ul className="space-y-1">
              {navItems.map((item, index) => (
                <li key={item.label}>
                  <PublicActionLink
                    href={item.href}
                    className="text-site-ink hover:bg-site-muted block rounded-xl px-3 py-2.5 text-base font-medium"
                    onClick={() => {
                      setIsMobileMenuOpen(false);
                    }}
                    ref={index === 0 ? firstMobileLinkRef : undefined}
                  >
                    {item.label}
                  </PublicActionLink>
                </li>
              ))}
            </ul>

            <div className="border-site-border mt-4 flex flex-col gap-2 border-t pt-4">
              <LanguageSwitcher
                variant="buttons"
                className="flex flex-wrap gap-2 px-2 py-1"
              />
              <PublicActionLink
                href={links.login}
                className="border-site-border text-site-ink hover:bg-site-muted rounded-full border px-4 py-2.5 text-center text-sm font-medium"
                onClick={() => {
                  setIsMobileMenuOpen(false);
                }}
              >
                {t("login")}
              </PublicActionLink>
              <PublicActionLink
                href={links.requestDemo}
                className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover rounded-full px-4 py-2.5 text-center text-sm font-medium"
                onClick={() => {
                  setIsMobileMenuOpen(false);
                }}
              >
                {t("requestDemo")}
              </PublicActionLink>
            </div>
          </nav>
        </div>
      ) : null}
    </header>
  );
}
