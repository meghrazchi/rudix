import { PublicActionLink } from "@/components/public/PublicActionLink";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import {
  getPublicChangelogEntries,
  type PublicChangelogEntry,
} from "@/lib/public-site/changelog";

function ReleaseBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-[#d8dbe5] bg-white px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-[#5a6072] uppercase">
      {label}
    </span>
  );
}

function MetadataItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] font-bold tracking-[0.12em] text-[#787e90] uppercase">
        {label}
      </dt>
      <dd className="mt-1 text-sm font-semibold text-[#11131a]">{value}</dd>
    </div>
  );
}

function ReleaseEntryCard({
  entry,
  latest = false,
}: {
  entry: PublicChangelogEntry;
  latest?: boolean;
}) {
  return (
    <article
      className={`rounded-2xl border bg-white p-6 shadow-sm transition ${
        latest ? "border-[#c9c2ff]" : "border-[#dfe2ea]"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-2xl font-black text-[#10131c]">
              {entry.version}
            </h3>
            {entry.isCurrent ? <ReleaseBadge label="Current release" /> : null}
          </div>
          <p className="mt-2 text-sm font-semibold text-[#4a5162]">
            {entry.milestone}
          </p>
        </div>
        <dl className="grid gap-4 sm:grid-cols-2">
          <MetadataItem label="Date" value={entry.date} />
          <MetadataItem label="Tag" value={entry.sourceTag} />
        </dl>
      </div>

      <p className="mt-5 max-w-3xl text-sm leading-7 text-[#4b5062]">
        {entry.summary}
      </p>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        {entry.categories.map((category) => (
          <section
            key={`${entry.version}-${category.title}`}
            className="rounded-xl border border-[#e4e7ee] bg-[#fafbfe] p-4"
            aria-label={`${entry.version} ${category.title}`}
          >
            <h4 className="text-sm font-bold text-[#10131c]">
              {category.title}
            </h4>
            <ul className="mt-3 space-y-2 text-sm leading-6 text-[#53596b]">
              {category.items.map((item) => (
                <li key={item} className="flex gap-2">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#3525cd]" />
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
              className="rounded-full border border-[#d8dbe5] bg-[#f8f9fc] px-4 py-2 text-sm font-semibold text-[#1f2433] transition hover:bg-white"
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
  const links = resolvePublicSiteLinks();
  const entries = getPublicChangelogEntries();
  const latest = entries[0] ?? null;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-16 lg:px-8 lg:py-20">
      <section
        aria-labelledby="changelog-hero-title"
        className="grid gap-10 lg:grid-cols-[1.2fr_0.8fr] lg:items-center"
      >
        <div>
          <ReleaseBadge label="Public changelog" />
          <h1
            id="changelog-hero-title"
            className="mt-5 text-4xl leading-tight font-black text-[#10131c] lg:text-6xl"
          >
            Release notes for product improvements, fixes, and breaking changes
          </h1>
          <p className="mt-5 max-w-2xl text-sm leading-7 text-[#4d5264] lg:text-base">
            Public entries are curated from release tags and milestone
            summaries. Internal-only issue details and sensitive security
            information are omitted before publication.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <PublicActionLink
              href={links.contact}
              className="rounded-lg bg-[#3525cd] px-5 py-3 text-sm font-semibold text-white shadow-[0_16px_32px_rgba(53,37,205,0.28)] transition hover:bg-[#2b1fc1]"
            >
              Contact the team
            </PublicActionLink>
            <PublicActionLink
              href={links.securityDisclosure}
              className="rounded-lg border border-[#d7dbe8] bg-white px-5 py-3 text-sm font-semibold text-[#1f2433] transition hover:bg-[#f5f7fc]"
            >
              Review security disclosure
            </PublicActionLink>
          </div>
        </div>

        {latest ? (
          <aside className="rounded-2xl border border-[#d9ddef] bg-[#f7f8fd] p-6 shadow-[0_24px_56px_rgba(16,24,40,0.08)]">
            <ReleaseBadge label="Latest release" />
            <h2 className="mt-4 text-3xl font-black text-[#10131c]">
              {latest.version}
            </h2>
            <p className="mt-2 text-sm font-semibold text-[#4a5162]">
              {latest.date}
            </p>
            <p className="mt-4 text-sm leading-7 text-[#4d5264]">
              {latest.summary}
            </p>
            <dl className="mt-6 grid gap-4 sm:grid-cols-2">
              <MetadataItem label="Milestone" value={latest.milestone} />
              <MetadataItem label="Source tag" value={latest.sourceTag} />
            </dl>
          </aside>
        ) : null}
      </section>

      <section aria-labelledby="release-history-title" className="mt-16">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-[11px] font-bold tracking-[0.16em] text-[#6f7486] uppercase">
              Release history
            </p>
            <h2
              id="release-history-title"
              className="mt-2 text-3xl font-black text-[#10131c]"
            >
              Current and historical release notes
            </h2>
          </div>
          <p className="max-w-2xl text-sm leading-7 text-[#5b6173]">
            Each entry is written so it can ship publicly without exposing
            private issue details, tenant data, or pre-disclosure security
            context.
          </p>
        </div>

        <div className="mt-8 space-y-6">
          {entries.map((entry, index) => (
            <ReleaseEntryCard
              key={entry.version}
              entry={entry}
              latest={index === 0}
            />
          ))}
        </div>
      </section>

      <section
        aria-labelledby="release-process-title"
        className="mt-16 grid gap-6 lg:grid-cols-3"
      >
        <article className="rounded-2xl border border-[#dfe2ea] bg-white p-6">
          <p className="text-[11px] font-bold tracking-[0.16em] text-[#6f7486] uppercase">
            Release note source
          </p>
          <h2
            id="release-process-title"
            className="mt-2 text-xl font-black text-[#10131c]"
          >
            Manual and structured updates
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#4d5264]">
            Keep public release notes in the typed data file. That keeps updates
            lightweight and avoids code-heavy page edits.
          </p>
        </article>

        <article className="rounded-2xl border border-[#dfe2ea] bg-white p-6">
          <p className="text-[11px] font-bold tracking-[0.16em] text-[#6f7486] uppercase">
            Publishing convention
          </p>
          <h2 className="mt-2 text-xl font-black text-[#10131c]">
            Git tag plus milestone
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#4d5264]">
            Start from the release tag and milestone, then publish only
            public-safe summaries, categories, and safe outbound links.
          </p>
        </article>

        <article className="rounded-2xl border border-[#dfe2ea] bg-white p-6">
          <p className="text-[11px] font-bold tracking-[0.16em] text-[#6f7486] uppercase">
            Disclosure guardrail
          </p>
          <h2 className="mt-2 text-xl font-black text-[#10131c]">
            Omit private details
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#4d5264]">
            Do not publish raw issue text, customer data, secrets, or unreleased
            security details. Use the security disclosure route when something
            must stay private.
          </p>
        </article>
      </section>
    </div>
  );
}
