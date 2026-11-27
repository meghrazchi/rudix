import { useLocale, useTranslations } from "next-intl";

type LegalSection = {
  heading: string;
  body: React.ReactNode;
};

type LegalPageLayoutProps = {
  title: string;
  version: string;
  effectiveDate: string;
  sections: LegalSection[];
};

function sectionId(heading: string, index: number): string {
  const slug = heading
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `legal-${index + 1}${slug ? `-${slug}` : ""}`;
}

/**
 * Shared layout for /legal/* pages (minimal modern redesign): header,
 * sticky table of contents on large screens, and readable sections.
 */
export function LegalPageLayout({
  title,
  version,
  effectiveDate,
  sections,
}: LegalPageLayoutProps) {
  const t = useTranslations("public.legalLayout");
  const locale = useLocale();
  const items = sections.map((section, index) => ({
    ...section,
    id: sectionId(section.heading, index),
  }));

  return (
    <div className="bg-site-canvas text-site-ink">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 lg:px-8 lg:py-20">
        <div className="max-w-3xl">
          <p className="border-site-border bg-site-surface text-site-ink-muted inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-medium">
            <span className="bg-site-accent h-1.5 w-1.5 rounded-full" />
            {t("badge")}
          </p>
          <h1 className="text-site-ink mt-6 text-4xl font-semibold tracking-[-0.03em] text-balance break-words hyphens-auto sm:text-5xl lg:hyphens-manual">
            {title}
          </h1>
          <p className="text-site-ink-subtle mt-4 text-sm">
            {t("versionLine", { version, date: effectiveDate })}
          </p>
          <div
            role="note"
            aria-label={t("noticeLabel")}
            className="mt-8 rounded-2xl border border-amber-300 bg-amber-50 px-5 py-4 text-sm leading-6 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200"
          >
            <strong>{t("noticeTitle")}</strong> {t("noticeBody")}
          </div>
          {locale !== "en" ? (
            <p className="text-site-ink-muted mt-4 text-sm">
              {t("englishOnly")}
            </p>
          ) : null}
        </div>

        <div className="mt-14 grid grid-cols-1 gap-12 lg:grid-cols-[220px_1fr]">
          <nav aria-label={t("onThisPage")} className="hidden lg:block">
            <div className="sticky top-24">
              <p className="text-site-ink-subtle text-xs font-medium tracking-wide uppercase">
                {t("onThisPage")}
              </p>
              <ol className="border-site-border mt-4 space-y-2.5 border-s ps-4 text-sm">
                {items.map((item) => (
                  <li key={item.id}>
                    <a
                      href={`#${item.id}`}
                      className="text-site-ink-muted hover:text-site-ink focus-visible:ring-site-accent block rounded-sm leading-5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                    >
                      {item.heading}
                    </a>
                  </li>
                ))}
              </ol>
            </div>
          </nav>

          <div className="border-site-border bg-site-surface max-w-3xl min-w-0 rounded-3xl border p-6 md:p-10">
            <div className="divide-site-border divide-y">
              {items.map((item) => (
                <section
                  key={item.id}
                  id={item.id}
                  aria-label={item.heading}
                  className="scroll-mt-24 py-10 first:pt-0 last:pb-0"
                >
                  <h2 className="text-site-ink text-lg font-semibold">
                    {item.heading}
                  </h2>
                  <div className="text-site-ink-muted [&_a]:text-site-accent-ink mt-3 space-y-3 text-sm leading-7 break-words [&_a]:underline">
                    {item.body}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
