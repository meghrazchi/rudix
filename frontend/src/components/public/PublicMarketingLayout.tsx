import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicHeader } from "@/components/public/PublicHeader";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

type PublicMarketingLayoutProps = {
  children: React.ReactNode;
  pageLabel?: string;
};

export function PublicMarketingLayout({
  children,
  pageLabel = "Public marketing content",
}: PublicMarketingLayoutProps) {
  const links = resolvePublicSiteLinks();

  return (
    <div className="min-h-screen bg-[#f2f3f6] text-[#13141a]">
      <a
        href="#main-content"
        className="sr-only z-50 m-2 rounded-md bg-white px-3 py-2 text-sm font-semibold text-[#11131a] shadow focus:not-sr-only focus:absolute"
      >
        Skip to main content
      </a>
      <PublicHeader links={links} />
      <main id="main-content" aria-label={pageLabel}>
        {children}
      </main>
      <PublicFooter links={links} />
    </div>
  );
}
