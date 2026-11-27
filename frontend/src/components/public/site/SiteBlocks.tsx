import type { ReactNode } from "react";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SiteIcon,
} from "@/components/public/site/primitives";

export type SiteLink = { label: string; href: string };

/** Thin breadcrumb row shown above sub-page heroes. */
export function SiteBreadcrumb({
  items,
}: {
  items: { label: string; href?: string }[];
}) {
  return (
    <nav aria-label="Breadcrumb" className="px-4 pt-6 lg:px-8">
      <ol className="text-site-ink-subtle mx-auto flex w-full max-w-6xl flex-wrap items-center gap-2 text-xs">
        {items.map((item, index) => (
          <li key={item.label} className="flex items-center gap-2">
            {index > 0 ? (
              <SiteIcon name="chevron_right" className="rtl-mirror text-sm" />
            ) : null}
            {item.href ? (
              <PublicActionLink
                href={item.href}
                className="hover:text-site-ink rounded-sm transition-colors"
              >
                {item.label}
              </PublicActionLink>
            ) : (
              <span aria-current="page" className="text-site-ink font-medium">
                {item.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/**
 * Split hero for sub-pages: copy on the start side, optional illustrative
 * mock (`aside`) on the end side. Without an aside the copy is centered.
 */
export function SiteSplitHero({
  id,
  badge,
  title,
  description,
  actions,
  aside,
}: {
  id: string;
  badge: string;
  title: ReactNode;
  description: string;
  actions?: ReactNode;
  aside?: ReactNode;
}) {
  const centered = !aside;
  return (
    <section
      aria-labelledby={id}
      className="relative overflow-hidden px-4 pt-12 pb-20 lg:px-8 lg:pt-16 lg:pb-28"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[480px] bg-[radial-gradient(50%_60%_at_25%_0%,var(--site-accent-soft),transparent)]"
      />
      <div
        className={`relative mx-auto grid w-full max-w-6xl grid-cols-1 items-center gap-14 ${
          centered ? "" : "lg:grid-cols-2"
        }`}
      >
        <div
          className={`rudix-site-rise min-w-0 ${
            centered ? "mx-auto max-w-3xl text-center" : ""
          }`}
        >
          <p className="border-site-border bg-site-surface text-site-ink-muted inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-medium">
            <span className="bg-site-accent h-1.5 w-1.5 rounded-full" />
            {badge}
          </p>
          <h1
            id={id}
            className="text-site-ink mt-6 text-4xl font-semibold tracking-[-0.03em] text-balance break-words hyphens-auto sm:text-5xl lg:hyphens-manual"
          >
            {title}
          </h1>
          <p
            className={`text-site-ink-muted mt-6 max-w-xl text-base leading-7 md:text-lg md:leading-8 ${
              centered ? "mx-auto" : ""
            }`}
          >
            {description}
          </p>
          {actions ? (
            <div
              className={`mt-9 flex flex-col gap-3 sm:flex-row ${
                centered ? "items-center justify-center" : ""
              }`}
            >
              {actions}
            </div>
          ) : null}
        </div>
        {aside ? <div className="rudix-site-rise min-w-0">{aside}</div> : null}
      </div>
    </section>
  );
}

export function PrimaryLink({ href, label }: SiteLink) {
  return (
    <PublicActionLink href={href} className={PRIMARY_BUTTON_CLASS}>
      {label}
      <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
    </PublicActionLink>
  );
}

export function SecondaryLink({ href, label }: SiteLink) {
  return (
    <PublicActionLink href={href} className={SECONDARY_BUTTON_CLASS}>
      {label}
    </PublicActionLink>
  );
}

/** Card with an icon tile, heading (h3) and body text. Renders as <li>. */
export function IconCard({
  icon,
  title,
  body,
  footer,
}: {
  icon: string;
  title: string;
  body: string;
  footer?: ReactNode;
}) {
  return (
    <li className="border-site-border bg-site-surface hover:border-site-accent/40 flex flex-col rounded-2xl border p-6 transition-colors">
      <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 items-center justify-center rounded-xl">
        <SiteIcon name={icon} className="text-xl" />
      </span>
      <h3 className="text-site-ink mt-5 text-base font-semibold">{title}</h3>
      <p className="text-site-ink-muted mt-2 text-sm leading-6">{body}</p>
      {footer ? <div className="mt-auto pt-5">{footer}</div> : null}
    </li>
  );
}

/** Wrapping list of pill chips (e.g. supported document sources). */
export function SourceChips({
  items,
}: {
  items: { icon: string; label: string }[];
}) {
  return (
    <ul className="flex flex-wrap gap-2.5">
      {items.map((item) => (
        <li
          key={item.label}
          className="border-site-border bg-site-surface text-site-ink inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm"
        >
          <SiteIcon name={item.icon} className="text-site-accent text-base" />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/** Example questions rendered as query rows. */
export function QueryList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li
          key={item}
          className="border-site-border bg-site-surface flex items-center gap-4 rounded-2xl border px-5 py-4"
        >
          <SiteIcon name="search" className="text-site-accent text-xl" />
          <span className="text-site-ink min-w-0 flex-1 text-sm font-medium md:text-base">
            {item}
          </span>
          <SiteIcon
            name="arrow_forward"
            className="rtl-mirror text-site-ink-subtle text-lg"
          />
        </li>
      ))}
    </ul>
  );
}

/** Numbered steps in a responsive grid. Step titles are h3. */
export function StepGrid({
  steps,
  columns = 4,
}: {
  steps: { title: string; description: string; label?: string }[];
  columns?: 3 | 4;
}) {
  const cols = columns === 3 ? "lg:grid-cols-3" : "lg:grid-cols-4";
  return (
    <ol className={`grid gap-4 sm:grid-cols-2 ${cols}`}>
      {steps.map((step, index) => (
        <li
          key={step.title}
          className="border-site-border bg-site-surface rounded-2xl border p-6"
        >
          <span className="bg-site-accent-soft text-site-accent-ink rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold">
            {step.label ?? String(index + 1).padStart(2, "0")}
          </span>
          <h3 className="text-site-ink mt-5 text-base font-semibold">
            {step.title}
          </h3>
          <p className="text-site-ink-muted mt-2 text-sm leading-6">
            {step.description}
          </p>
        </li>
      ))}
    </ol>
  );
}

/** Rounded tinted closing panel with up to two actions (h2 heading). */
export function SiteCtaPanel({
  id,
  title,
  description,
  primary,
  secondary,
}: {
  id: string;
  title: string;
  description?: string;
  primary: SiteLink;
  secondary?: SiteLink;
}) {
  return (
    <section aria-labelledby={id} className="px-4 pb-24 lg:px-8 lg:pb-32">
      <div className="border-site-border bg-site-muted/60 mx-auto max-w-5xl rounded-3xl border px-6 py-14 text-center md:px-12 md:py-20">
        <h2
          id={id}
          className="text-site-ink text-3xl font-semibold tracking-tight text-balance break-words hyphens-auto md:text-4xl lg:hyphens-manual"
        >
          {title}
        </h2>
        {description ? (
          <p className="text-site-ink-muted mx-auto mt-4 max-w-xl text-base leading-7 md:text-lg">
            {description}
          </p>
        ) : null}
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <PublicActionLink
            href={primary.href}
            className={`${PRIMARY_BUTTON_CLASS} w-full sm:w-auto`}
          >
            {primary.label}
            <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
          </PublicActionLink>
          {secondary ? (
            <PublicActionLink
              href={secondary.href}
              className={`${SECONDARY_BUTTON_CLASS} w-full sm:w-auto`}
            >
              {secondary.label}
            </PublicActionLink>
          ) : null}
        </div>
      </div>
    </section>
  );
}
