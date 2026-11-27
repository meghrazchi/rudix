import type { ReactNode } from "react";

type IconProps = {
  name: string;
  className?: string;
  filled?: boolean;
};

/** Decorative Material Symbols glyph; always hidden from assistive tech. */
export function SiteIcon({ name, className = "", filled = false }: IconProps) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined leading-none select-none ${className}`}
      style={filled ? { fontVariationSettings: "'FILL' 1" } : undefined}
    >
      {name}
    </span>
  );
}

type SectionHeadingProps = {
  id?: string;
  eyebrow: string;
  title: string;
  description?: string;
  align?: "start" | "center";
};

export function SectionHeading({
  id,
  eyebrow,
  title,
  description,
  align = "start",
}: SectionHeadingProps) {
  const alignment = align === "center" ? "mx-auto text-center" : "";
  return (
    <div className={`max-w-2xl ${alignment}`}>
      <p className="text-site-accent-ink text-xs font-semibold tracking-[0.08em] uppercase">
        {eyebrow}
      </p>
      <h2
        id={id}
        className="text-site-ink mt-3 text-3xl font-semibold tracking-tight text-balance md:text-4xl"
      >
        {title}
      </h2>
      {description ? (
        <p className="text-site-ink-muted mt-4 text-base leading-7 md:text-lg">
          {description}
        </p>
      ) : null}
    </div>
  );
}

export function SiteSection({
  children,
  className = "",
  labelledBy,
  id,
}: {
  children: ReactNode;
  className?: string;
  labelledBy: string;
  id?: string;
}) {
  return (
    <section
      id={id}
      aria-labelledby={labelledBy}
      className={`px-4 py-20 lg:px-8 lg:py-28 ${className}`}
    >
      <div className="mx-auto w-full max-w-6xl">{children}</div>
    </section>
  );
}

export const PRIMARY_BUTTON_CLASS =
  "inline-flex h-11 items-center justify-center gap-2 rounded-full bg-site-accent px-6 text-sm font-medium text-site-on-accent transition-colors hover:bg-site-accent-hover";

export const SECONDARY_BUTTON_CLASS =
  "inline-flex h-11 items-center justify-center gap-2 rounded-full border border-site-border bg-site-surface px-6 text-sm font-medium text-site-ink transition-colors hover:bg-site-muted";
