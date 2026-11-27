"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicHeader } from "@/components/public/PublicHeader";
import { trackPageView } from "@/lib/analytics";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

/**
 * `light` keeps the classic light surface; `system` follows the OS color scheme.
 * Pages opt into `system` once their own content uses the `site-*` tokens.
 */
export type PublicTheme = "light" | "system";

type PublicMarketingLayoutProps = {
  children: React.ReactNode;
  pageLabel?: string;
  theme?: PublicTheme;
};

export function PublicMarketingLayout({
  children,
  pageLabel = "Public marketing content",
  theme = "light",
}: PublicMarketingLayoutProps) {
  const links = resolvePublicSiteLinks();
  const pathname = usePathname();
  const a11y = useTranslations("public.a11y");

  useEffect(() => {
    void trackPageView({
      pageKey: pathname ?? pageLabel,
      route: pathname ?? "/",
      surface: "public",
      featureArea: "public",
    });
  }, [pageLabel, pathname]);

  return (
    <div
      className="rudix-public bg-site-canvas text-site-ink min-h-screen"
      data-public-theme={theme}
    >
      <a
        href="#main-content"
        className="bg-site-surface text-site-ink sr-only z-50 m-2 rounded-md px-3 py-2 text-sm font-semibold shadow focus:not-sr-only focus:absolute"
      >
        {a11y("skipToContent")}
      </a>
      <PublicHeader links={links} />
      <main id="main-content" aria-label={pageLabel}>
        {children}
      </main>
      <PublicFooter links={links} />
    </div>
  );
}
