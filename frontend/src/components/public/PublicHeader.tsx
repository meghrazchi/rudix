"use client";

import Image from "next/image";
import { useEffect, useId, useRef, useState } from "react";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import type { PublicSiteLinks } from "@/lib/public-site/links";
import { buildPrimaryNavItems } from "@/lib/public-site/links";

type PublicHeaderProps = {
  links: PublicSiteLinks;
};

export function PublicHeader({ links }: PublicHeaderProps) {
  const navItems = buildPrimaryNavItems(links);
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

  return (
    <header className="sticky top-0 z-30 border-b border-[#dbdde4] bg-[#f2f3f6]/95 backdrop-blur-sm">
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 py-4 lg:px-8">
        <div className="flex items-center gap-8">
          <PublicActionLink
            href={links.home}
            className="flex items-center gap-2"
            ariaLabel="Rudix home"
          >
            <Image
              src="/brand/rudix-mark.svg"
              alt="Rudix logo"
              width={24}
              height={24}
              className="h-6 w-6"
            />
            <span className="text-sm font-bold text-[#11131a]">Rudix</span>
          </PublicActionLink>
          <nav
            aria-label="Primary navigation"
            className="hidden items-center gap-6 md:flex"
          >
            {navItems.map((item) => (
              <PublicActionLink
                key={item.label}
                href={item.href}
                className="text-xs font-medium text-[#4e5160] transition hover:text-[#25283a]"
              >
                {item.label}
              </PublicActionLink>
            ))}
          </nav>
        </div>

        <div className="hidden items-center gap-3 md:flex">
          <PublicActionLink
            href={links.login}
            className="text-xs font-semibold text-[#2e3141] transition hover:text-black"
          >
            Login
          </PublicActionLink>
          <PublicActionLink
            href={links.requestDemo}
            className="rounded-md bg-[#3a35e8] px-3 py-2 text-xs font-semibold text-white transition hover:bg-[#2d2ad1]"
          >
            Request Demo
          </PublicActionLink>
        </div>

        <button
          ref={menuButtonRef}
          type="button"
          aria-expanded={isMobileMenuOpen}
          aria-controls={mobileMenuId}
          aria-label={
            isMobileMenuOpen ? "Close navigation menu" : "Open navigation menu"
          }
          className="rounded-md border border-[#cfd3de] bg-white p-2 text-[#2e3346] md:hidden"
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
            aria-label="Mobile navigation"
            className="border-t border-[#dde0ea] bg-white px-4 py-4"
          >
            <ul className="space-y-3">
              {navItems.map((item, index) => (
                <li key={item.label}>
                  <PublicActionLink
                    href={item.href}
                    className="block rounded-md px-2 py-2 text-sm font-medium text-[#2f3346] hover:bg-[#f2f3f7]"
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

            <div className="mt-4 flex flex-col gap-2 border-t border-[#e6e8ef] pt-4">
              <PublicActionLink
                href={links.login}
                className="rounded-md px-2 py-2 text-sm font-semibold text-[#2e3141] hover:bg-[#f2f3f7]"
                onClick={() => {
                  setIsMobileMenuOpen(false);
                }}
              >
                Login
              </PublicActionLink>
              <PublicActionLink
                href={links.requestDemo}
                className="rounded-md bg-[#3a35e8] px-4 py-2 text-center text-sm font-semibold text-white hover:bg-[#2d2ad1]"
                onClick={() => {
                  setIsMobileMenuOpen(false);
                }}
              >
                Request Demo
              </PublicActionLink>
            </div>
          </nav>
        </div>
      ) : null}
    </header>
  );
}
