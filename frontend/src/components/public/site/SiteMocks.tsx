import type { ReactNode } from "react";

import { SiteIcon } from "@/components/public/site/primitives";

/**
 * Illustrative UI mocks for marketing pages. They are decorative, so the
 * wrapper is hidden from assistive tech unless a label is provided.
 */
export function MockFrame({
  label,
  title,
  children,
}: {
  label?: string;
  title?: string;
  children: ReactNode;
}) {
  return (
    <figure
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className="border-site-border bg-site-surface w-full rounded-2xl border p-2 text-start shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)]"
    >
      <div className="border-site-border flex items-center gap-2 border-b px-4 py-3">
        <span className="bg-site-border h-2.5 w-2.5 rounded-full" />
        <span className="bg-site-border h-2.5 w-2.5 rounded-full" />
        <span className="bg-site-border h-2.5 w-2.5 rounded-full" />
        {title ? (
          <span className="text-site-ink-subtle ms-2 truncate text-xs font-medium">
            {title}
          </span>
        ) : null}
      </div>
      <div className="space-y-4 p-4 md:p-5">{children}</div>
    </figure>
  );
}

export function MockQuestion({ children }: { children: ReactNode }) {
  return (
    <div className="flex justify-end">
      <p className="bg-site-muted text-site-ink max-w-sm rounded-2xl rounded-se-sm px-4 py-3 text-sm font-medium">
        {children}
      </p>
    </div>
  );
}

export function MockAnswer({
  label,
  children,
  sources,
}: {
  label?: string;
  children: ReactNode;
  sources?: string[];
}) {
  return (
    <div className="border-site-border rounded-2xl border p-4">
      {label ? (
        <div className="mb-2 flex items-center gap-2">
          <span className="bg-site-accent text-site-on-accent flex h-5 w-5 items-center justify-center rounded-md">
            <SiteIcon name="auto_awesome" className="text-xs" filled />
          </span>
          <span className="text-site-ink text-xs font-semibold">{label}</span>
        </div>
      ) : null}
      <div className="text-site-ink text-sm leading-6">{children}</div>
      {sources && sources.length > 0 ? (
        <ul className="border-site-border mt-3 space-y-1.5 border-t pt-3">
          {sources.map((source, index) => (
            <li
              key={source}
              className="bg-site-canvas flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs"
            >
              <span className="bg-site-accent-soft text-site-accent-ink rounded px-1.5 font-mono font-semibold">
                {index + 1}
              </span>
              <SiteIcon
                name="description"
                className="text-site-ink-subtle text-sm"
              />
              <span className="text-site-ink-muted min-w-0 truncate">
                {source}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function MockCitation({ n }: { n: number }) {
  return (
    <sup className="bg-site-accent-soft text-site-accent-ink mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 align-middle font-mono text-[10px] font-semibold">
      {n}
    </sup>
  );
}

/** Highlighted source excerpt used in "verify the source" mocks. */
export function MockSnippet({ label, body }: { label: string; body: string }) {
  return (
    <div className="border-site-accent/30 bg-site-accent-soft/60 rounded-xl border-s-2 px-4 py-3">
      <p className="text-site-accent-ink text-xs font-semibold">{label}</p>
      <p className="text-site-ink mt-1 text-sm leading-6 italic">“{body}”</p>
    </div>
  );
}
