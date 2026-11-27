import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import {
  getPublicChangelogEntries,
  type PublicChangelogCategory,
  type PublicChangelogEntry,
} from "@/lib/public-site/changelog";

type ChangelogLabels = {
  publicChangelog: string;
  heroTitle: string;
  heroDescription: string;
  contactTeam: string;
  reviewSecurityDisclosure: string;
  latestRelease: string;
  currentRelease: string;
  date: string;
  tag: string;
  milestone: string;
  sourceTag: string;
  releaseHistory: string;
  historyTitle: string;
  historyDescription: string;
  sourceEyebrow: string;
  sourceTitle: string;
  sourceDescription: string;
  publishingEyebrow: string;
  publishingTitle: string;
  publishingDescription: string;
  disclosureEyebrow: string;
  disclosureTitle: string;
  disclosureDescription: string;
  categories: Record<PublicChangelogCategory["title"], string>;
};

function ReleaseBadge({ label }: { label: string }) {
  return (
    <span className="border-site-border bg-site-surface text-site-ink-muted inline-flex items-center rounded-full border px-3 py-1 text-xs font-bold tracking-[0.12em] uppercase">
      {label}
    </span>
  );
}

function MetadataItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-site-ink-subtle text-xs font-bold tracking-[0.12em] uppercase">
        {label}
      </dt>
      <dd className="text-site-ink mt-1 text-sm font-semibold">{value}</dd>
    </div>
  );
}

function ReleaseEntryCard({
  entry,
  latest = false,
  labels,
}: {
  entry: PublicChangelogEntry;
  latest?: boolean;
  labels: ChangelogLabels;
}) {
  return (
    <article
      className={`bg-site-surface rounded-2xl border p-6 shadow-sm transition ${
        latest ? "border-site-border" : "border-site-border"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-site-ink text-2xl font-semibold">
              {entry.version}
            </h3>
            {entry.isCurrent ? (
              <ReleaseBadge label={labels.currentRelease} />
            ) : null}
          </div>
          <p className="text-site-ink-muted mt-2 text-sm font-semibold">
            {entry.milestone}
          </p>
        </div>
        <dl className="grid gap-4 sm:grid-cols-2">
          <MetadataItem label={labels.date} value={entry.date} />
          <MetadataItem label={labels.tag} value={entry.sourceTag} />
        </dl>
      </div>

      <p className="text-site-ink-muted mt-5 max-w-3xl text-sm leading-7">
        {entry.summary}
      </p>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
        {entry.categories.map((category) => (
          <section
            key={`${entry.version}-${category.title}`}
            className="border-site-border bg-site-surface rounded-xl border p-4"
            aria-label={`${entry.version} ${labels.categories[category.title]}`}
          >
            <h4 className="text-site-ink text-sm font-bold">
              {labels.categories[category.title]}
            </h4>
            <ul className="text-site-ink-muted mt-3 space-y-2 text-sm leading-6">
              {category.items.map((item) => (
                <li key={item} className="flex gap-2">
                  <span className="bg-site-accent mt-2 h-1.5 w-1.5 shrink-0 rounded-full" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      {entry.links.length > 0 ? (
        <div className="mt-6 flex flex-wrap gap-3">
          {entry.links.map((link) => (
            <PublicActionLink
              key={link.label}
              href={link.href}
              className="border-site-border bg-site-surface text-site-ink hover:bg-site-surface rounded-full border px-4 py-2 text-sm font-semibold transition"
            >
              {link.label}
            </PublicActionLink>
          ))}
        </div>
      ) : null}
    </article>
  );
}

export function ChangelogPage() {
  const t = useTranslations("public.changelog");
  const labels: ChangelogLabels = {
    publicChangelog: t("publicChangelog"),
    heroTitle: t("heroTitle"),
    heroDescription: t("heroDescription"),
    contactTeam: t("contactTeam"),
    reviewSecurityDisclosure: t("reviewSecurityDisclosure"),
    latestRelease: t("latestRelease"),
    currentRelease: t("currentRelease"),
    date: t("date"),
    tag: t("tag"),
    milestone: t("milestone"),
    sourceTag: t("sourceTag"),
    releaseHistory: t("releaseHistory"),
    historyTitle: t("historyTitle"),
    historyDescription: t("historyDescription"),
    sourceEyebrow: t("sourceEyebrow"),
    sourceTitle: t("sourceTitle"),
    sourceDescription: t("sourceDescription"),
    publishingEyebrow: t("publishingEyebrow"),
    publishingTitle: t("publishingTitle"),
    publishingDescription: t("publishingDescription"),
    disclosureEyebrow: t("disclosureEyebrow"),
    disclosureTitle: t("disclosureTitle"),
    disclosureDescription: t("disclosureDescription"),
    categories: {
      Added: t("categories.added"),
      Improved: t("categories.improved"),
      Fixed: t("categories.fixed"),
      "Breaking changes": t("categories.breakingChanges"),
    },
  };
  const links = resolvePublicSiteLinks();
  const translatedEntries = t.raw("releases") as unknown;
  const entries =
    Array.isArray(translatedEntries) && translatedEntries.length > 0
      ? (translatedEntries as PublicChangelogEntry[])
      : getPublicChangelogEntries();
  const latest = entries[0] ?? null;

  return (
    <div className="bg-site-canvas text-site-ink">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 lg:px-8 lg:py-20">
        <section
          aria-labelledby="changelog-hero-title"
          className="grid grid-cols-1 gap-10 lg:grid-cols-[1.2fr_0.8fr] lg:items-center"
        >
          <div>
            <ReleaseBadge label={labels.publicChangelog} />
            <h1
              id="changelog-hero-title"
              className="text-site-ink mt-5 text-4xl leading-tight font-semibold tracking-[-0.03em] break-words hyphens-auto lg:text-6xl lg:hyphens-manual"
            >
              {labels.heroTitle}
            </h1>
            <p className="text-site-ink-muted mt-5 max-w-2xl text-sm leading-7 lg:text-base">
              {labels.heroDescription}
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <PublicActionLink
                href={links.contact}
                className="bg-site-accent text-site-on-accent hover:bg-site-accent-hover inline-flex h-11 items-center justify-center rounded-full px-6 text-sm font-medium transition-colors"
              >
                {labels.contactTeam}
              </PublicActionLink>
              <PublicActionLink
                href={links.securityDisclosure}
                className="border-site-border bg-site-surface text-site-ink hover:bg-site-canvas inline-flex h-11 items-center justify-center rounded-full border px-6 text-sm font-medium transition"
              >
                {labels.reviewSecurityDisclosure}
              </PublicActionLink>
            </div>
          </div>

          {latest ? (
            <aside className="border-site-border bg-site-surface rounded-2xl border p-6">
              <ReleaseBadge label={labels.latestRelease} />
              <h2 className="text-site-ink mt-4 text-3xl font-semibold">
                {latest.version}
              </h2>
              <p className="text-site-ink-muted mt-2 text-sm font-semibold">
                {latest.date}
              </p>
              <p className="text-site-ink-muted mt-4 text-sm leading-7">
                {latest.summary}
              </p>
              <dl className="mt-6 grid gap-4 sm:grid-cols-2">
                <MetadataItem
                  label={labels.milestone}
                  value={latest.milestone}
                />
                <MetadataItem
                  label={labels.sourceTag}
                  value={latest.sourceTag}
                />
              </dl>
            </aside>
          ) : null}
        </section>

        <section aria-labelledby="release-history-title" className="mt-16">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-site-ink-subtle text-xs font-bold tracking-[0.16em] uppercase">
                {labels.releaseHistory}
              </p>
              <h2
                id="release-history-title"
                className="text-site-ink mt-2 text-3xl font-semibold"
              >
                {labels.historyTitle}
              </h2>
            </div>
            <p className="text-site-ink-muted max-w-2xl text-sm leading-7">
              {labels.historyDescription}
            </p>
          </div>

          <div className="mt-8 space-y-6">
            {entries.map((entry, index) => (
              <ReleaseEntryCard
                key={entry.version}
                entry={entry}
                latest={index === 0}
                labels={labels}
              />
            ))}
          </div>
        </section>

        <section
          aria-labelledby="release-process-title"
          className="mt-16 grid grid-cols-1 gap-6 lg:grid-cols-3"
        >
          <article className="border-site-border bg-site-surface rounded-2xl border p-6">
            <p className="text-site-ink-subtle text-xs font-bold tracking-[0.16em] uppercase">
              {labels.sourceEyebrow}
            </p>
            <h2
              id="release-process-title"
              className="text-site-ink mt-2 text-xl font-semibold"
            >
              {labels.sourceTitle}
            </h2>
            <p className="text-site-ink-muted mt-3 text-sm leading-7">
              {labels.sourceDescription}
            </p>
          </article>

          <article className="border-site-border bg-site-surface rounded-2xl border p-6">
            <p className="text-site-ink-subtle text-xs font-bold tracking-[0.16em] uppercase">
              {labels.publishingEyebrow}
            </p>
            <h2 className="text-site-ink mt-2 text-xl font-semibold">
              {labels.publishingTitle}
            </h2>
            <p className="text-site-ink-muted mt-3 text-sm leading-7">
              {labels.publishingDescription}
            </p>
          </article>

          <article className="border-site-border bg-site-surface rounded-2xl border p-6">
            <p className="text-site-ink-subtle text-xs font-bold tracking-[0.16em] uppercase">
              {labels.disclosureEyebrow}
            </p>
            <h2 className="text-site-ink mt-2 text-xl font-semibold">
              {labels.disclosureTitle}
            </h2>
            <p className="text-site-ink-muted mt-3 text-sm leading-7">
              {labels.disclosureDescription}
            </p>
          </article>
        </section>
      </div>
    </div>
  );
}
