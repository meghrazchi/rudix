import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SiteIcon,
  StatusPill,
} from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

const LIBRARY = [
  {
    file: "compliance-handbook.pdf",
    icon: "picture_as_pdf",
    pages: 128,
    state: "indexed",
  },
  {
    file: "vendor-agreements.docx",
    icon: "article",
    pages: 42,
    state: "indexed",
  },
  {
    file: "release-notes.txt",
    icon: "description",
    pages: 6,
    state: "processing",
  },
  {
    file: "security-overview.pdf",
    icon: "picture_as_pdf",
    pages: 36,
    state: "indexed",
  },
] as const;

function HeroTitle({ title, highlight }: { title: string; highlight: string }) {
  const index = highlight ? title.indexOf(highlight) : -1;
  if (index < 0) {
    return <>{title}</>;
  }
  return (
    <>
      {title.slice(0, index)}
      <span className="text-site-accent">{highlight}</span>
      {title.slice(index + highlight.length)}
    </>
  );
}

function DocumentLibraryMock() {
  const t = useTranslations("public.product");

  return (
    <figure aria-label={t("hero.imageAlt")} className="w-full">
      <div className="border-site-border bg-site-surface rounded-2xl border p-5 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)]">
        <div className="border-site-border bg-site-canvas text-site-ink-subtle flex items-center gap-2 rounded-xl border px-3 py-2 text-sm">
          <SiteIcon name="search" className="text-lg" />
          {t("mock.searchPlaceholder")}
        </div>
        <ul className="divide-site-border mt-3 divide-y">
          {LIBRARY.map((doc) => (
            <li key={doc.file} className="py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="bg-site-accent-soft text-site-accent-ink flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                    <SiteIcon name={doc.icon} className="text-lg" />
                  </span>
                  <div className="min-w-0">
                    <bdi className="text-site-ink block truncate text-sm font-medium">
                      {doc.file}
                    </bdi>
                    <span className="text-site-ink-subtle text-xs">
                      {t("mock.pages", { count: doc.pages })}
                    </span>
                  </div>
                </div>
                {doc.state === "indexed" ? (
                  <StatusPill tone="success">
                    <SiteIcon name="check" className="text-sm" />
                    {t("mock.indexed")}
                  </StatusPill>
                ) : (
                  <StatusPill tone="accent">
                    <span className="bg-site-accent h-1.5 w-1.5 animate-pulse rounded-full motion-reduce:animate-none" />
                    {t("mock.processing")}
                  </StatusPill>
                )}
              </div>
              {doc.state === "processing" ? (
                <div className="bg-site-muted mt-2.5 h-1 overflow-hidden rounded-full">
                  <div className="bg-site-accent h-full w-2/3 rounded-full" />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
      <figcaption className="text-site-ink-subtle mt-3 text-center text-xs lg:text-start">
        {t("hero.imageCaption")}
      </figcaption>
    </figure>
  );
}

export function ProductHero({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.product.hero");

  return (
    <section
      aria-labelledby="product-hero-title"
      className="relative overflow-hidden px-4 pt-16 pb-20 lg:px-8 lg:pt-24 lg:pb-28"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[480px] bg-[radial-gradient(50%_60%_at_25%_0%,var(--site-accent-soft),transparent)]"
      />
      <div className="relative mx-auto grid w-full max-w-6xl items-center gap-14 lg:grid-cols-2">
        <div className="rudix-site-rise min-w-0">
          <p className="border-site-border bg-site-surface text-site-ink-muted inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-medium">
            <span className="bg-site-accent h-1.5 w-1.5 rounded-full" />
            {t("badge")}
          </p>
          <h1
            id="product-hero-title"
            className="text-site-ink mt-6 text-4xl font-semibold tracking-[-0.03em] text-balance break-words hyphens-auto sm:text-5xl"
          >
            <HeroTitle title={t("title")} highlight={t("titleHighlight")} />
          </h1>
          <p className="text-site-ink-muted mt-6 max-w-xl text-base leading-7 md:text-lg md:leading-8">
            {t("description")}
          </p>
          <div className="mt-9 flex flex-col gap-3 sm:flex-row">
            <PublicActionLink
              href={links.requestDemo}
              className={PRIMARY_BUTTON_CLASS}
            >
              {t("primaryCta")}
              <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
            </PublicActionLink>
            <PublicActionLink
              href={links.app}
              className={SECONDARY_BUTTON_CLASS}
            >
              {t("secondaryCta")}
            </PublicActionLink>
          </div>
        </div>
        <div className="rudix-site-rise min-w-0">
          <DocumentLibraryMock />
        </div>
      </div>
    </section>
  );
}
