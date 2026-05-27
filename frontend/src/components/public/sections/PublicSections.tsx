import Image from "next/image";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { PublicCta } from "@/components/public/PublicCtas";

type HeroAction = {
  label: string;
  href: string;
  variant?: "primary" | "secondary";
};

type HeroSectionProps = {
  badge?: string;
  title: React.ReactNode;
  description: string;
  actions: HeroAction[];
  imageSrc?: string;
  imageAlt?: string;
  imageCaption?: string;
};

export type PublicFeatureItem = {
  icon:
    | "pipeline"
    | "ingestion"
    | "evaluation"
    | "security"
    | "governance"
    | "speed";
  title: string;
  description: string;
};

type FeatureGridSectionProps = {
  title: string;
  description: string;
  items: PublicFeatureItem[];
  sectionId?: string;
};

type WorkflowStep = {
  title: string;
  description: string;
};

type WorkflowStripSectionProps = {
  title: string;
  description: string;
  steps: WorkflowStep[];
};

type MetricsTrustStripProps = {
  heading: string;
  labels: string[];
};

type TestimonialPlaceholderSectionProps = {
  quote: string;
  source: string;
};

type FaqItem = {
  question: string;
  answer: string;
};

type FaqSectionProps = {
  title: string;
  items: FaqItem[];
};

type FinalCtaBandProps = {
  title: string;
  description: string;
  primaryLabel: string;
  primaryHref: string;
  secondaryLabel: string;
  secondaryHref: string;
};

function CapabilityIcon({ icon }: { icon: PublicFeatureItem["icon"] }) {
  if (icon === "pipeline") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
      >
        <rect
          x="4"
          y="5"
          width="16"
          height="14"
          rx="2.5"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="M4 9h16M8 14h3M13 14h3M10.5 16h3"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "ingestion") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
      >
        <path
          d="M12 3.8 6.5 6.3v4.4c0 3.9 2.2 7.5 5.5 9 3.3-1.5 5.5-5.1 5.5-9V6.3L12 3.8Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="m9.8 11.9 1.7 1.8 2.9-3"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "evaluation") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
      >
        <circle cx="12" cy="12" r="7" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 8.6v3.7l2.4 1.6" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    );
  }

  if (icon === "security") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
      >
        <path
          d="M12 4.1 6.7 6.4v4.8c0 3.7 2 7.1 5.3 8.7 3.3-1.6 5.3-5 5.3-8.7V6.4L12 4.1Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path d="M9.8 12.2h4.4" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    );
  }

  if (icon === "governance") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
      >
        <path
          d="M4.5 8.5 12 4l7.5 4.5v7L12 20l-7.5-4.5v-7Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path d="M9.3 11.7h5.4" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <path d="M5 12h14M12 5v14" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="7" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function StatusPill({ label }: { label: string }) {
  return (
    <span className="rounded-full border border-[#e2def7] bg-[#f2f0ff] px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-[#5a53a4] uppercase">
      {label}
    </span>
  );
}

export function HeroSection({
  badge,
  title,
  description,
  actions,
  imageSrc,
  imageAlt,
  imageCaption,
}: HeroSectionProps) {
  return (
    <section
      aria-labelledby="hero-title"
      className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-12 lg:grid-cols-2 lg:items-center lg:gap-12 lg:px-8 lg:py-16"
    >
      <div>
        {badge ? <StatusPill label={badge} /> : null}
        <h1
          id="hero-title"
          className="mt-6 text-4xl leading-tight font-black text-[#101218] lg:text-6xl"
        >
          {title}
        </h1>
        <p className="mt-5 max-w-xl text-sm leading-7 text-[#505465] lg:text-base">
          {description}
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          {actions.map((action) => (
            <PublicCta
              key={action.label}
              href={action.href}
              label={action.label}
              variant={action.variant ?? "primary"}
            />
          ))}
        </div>
      </div>

      {imageSrc ? (
        <figure
          aria-label={imageAlt}
          className="rounded-2xl border border-[#dfe2ea] bg-white p-4 shadow-[0_22px_50px_rgba(10,15,35,0.14)]"
        >
          <div className="overflow-hidden rounded-xl border border-[#e6e7ef] bg-[#fbfbfe]">
            <Image
              src={imageSrc}
              alt={imageAlt ?? "Rudix product preview"}
              width={1600}
              height={900}
              priority
              sizes="(max-width: 1024px) 100vw, 50vw"
              className="h-auto w-full object-cover"
            />
          </div>
          {imageCaption ? (
            <figcaption className="sr-only">{imageCaption}</figcaption>
          ) : null}
        </figure>
      ) : null}
    </section>
  );
}

export function MetricsTrustStrip({ heading, labels }: MetricsTrustStripProps) {
  return (
    <section
      className="border-y border-[#dde0e8] bg-[#eff1f5] py-8"
      aria-label="Trust and adoption"
    >
      <div className="mx-auto w-full max-w-7xl px-4 text-center lg:px-8">
        <p className="text-[10px] font-bold tracking-[0.24em] text-[#666a7d] uppercase">
          {heading}
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-8">
          {labels.map((label) => (
            <p
              key={label}
              className="text-xs font-semibold tracking-[0.08em] text-[#7a7f91] uppercase"
            >
              {label}
            </p>
          ))}
        </div>
      </div>
    </section>
  );
}

export function FeatureGridSection({
  title,
  description,
  items,
  sectionId,
}: FeatureGridSectionProps) {
  return (
    <section
      id={sectionId}
      aria-labelledby={sectionId ? `${sectionId}-title` : "feature-grid-title"}
      className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20"
    >
      <div className="text-center">
        <h2
          id={sectionId ? `${sectionId}-title` : "feature-grid-title"}
          className="text-3xl font-black text-[#12141b] lg:text-5xl"
        >
          {title}
        </h2>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-[#595d6e]">
          {description}
        </p>
      </div>
      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {items.map((item) => (
          <article
            key={item.title}
            className="rounded-2xl border border-[#d8dce7] bg-white p-5 shadow-sm"
          >
            <div className="mb-4 inline-flex h-8 w-8 items-center justify-center rounded-md bg-[#ecebff] text-[#4338ff]">
              <CapabilityIcon icon={item.icon} />
            </div>
            <h3 className="text-2xl font-semibold text-[#171a24]">
              {item.title}
            </h3>
            <p className="mt-3 text-sm leading-7 text-[#5a6071]">
              {item.description}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

export function WorkflowStripSection({
  title,
  description,
  steps,
}: WorkflowStripSectionProps) {
  return (
    <section aria-labelledby="workflow-title" className="bg-[#1e242f]">
      <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
        <div className="max-w-3xl">
          <h2
            id="workflow-title"
            className="text-4xl font-black text-white lg:text-5xl"
          >
            {title}
          </h2>
          <p className="mt-4 text-sm leading-7 text-[#c7cede] lg:text-base">
            {description}
          </p>
        </div>
        <ol className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {steps.map((step, index) => (
            <li
              key={step.title}
              className="rounded-lg border border-[#384154] bg-[#252d3b] px-4 py-4"
            >
              <p className="text-xs font-bold tracking-[0.12em] text-[#9aa5c0] uppercase">
                Step {index + 1}
              </p>
              <h3 className="mt-2 text-base font-semibold text-white">
                {step.title}
              </h3>
              <p className="mt-2 text-sm leading-6 text-[#dce3f2]">
                {step.description}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function TestimonialPlaceholderSection({
  quote,
  source,
}: TestimonialPlaceholderSectionProps) {
  return (
    <section
      aria-label="Customer perspective"
      className="mx-auto w-full max-w-7xl px-4 py-10 lg:px-8"
    >
      <div className="rounded-2xl border border-[#d8dce7] bg-white px-6 py-8 shadow-sm">
        <p className="text-lg leading-8 font-medium text-[#1f2532]">
          “{quote}”
        </p>
        <p className="mt-4 text-sm font-semibold text-[#535a6c]">{source}</p>
      </div>
    </section>
  );
}

export function FaqSection({ title, items }: FaqSectionProps) {
  return (
    <section
      aria-labelledby="faq-title"
      className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8"
    >
      <h2
        id="faq-title"
        className="text-3xl font-black text-[#12141b] lg:text-4xl"
      >
        {title}
      </h2>
      <div className="mt-6 space-y-3">
        {items.map((item) => (
          <details
            key={item.question}
            className="rounded-xl border border-[#d8dce7] bg-white px-4 py-3"
          >
            <summary className="cursor-pointer text-sm font-semibold text-[#1f2532]">
              {item.question}
            </summary>
            <p className="mt-3 text-sm leading-7 text-[#5a6071]">
              {item.answer}
            </p>
          </details>
        ))}
      </div>
    </section>
  );
}

export function FinalCtaBand({
  title,
  description,
  primaryLabel,
  primaryHref,
  secondaryLabel,
  secondaryHref,
}: FinalCtaBandProps) {
  return (
    <section
      aria-labelledby="final-cta-title"
      className="bg-[linear-gradient(135deg,#2a2fe3_0%,#251bc0_52%,#3b1ed0_100%)]"
    >
      <div className="mx-auto w-full max-w-7xl px-4 py-16 text-center lg:px-8 lg:py-24">
        <h2
          id="final-cta-title"
          className="text-4xl font-black text-white lg:text-6xl"
        >
          {title}
        </h2>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-[#d8dcff] lg:text-base">
          {description}
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <PublicActionLink
            href={primaryHref}
            className="rounded-md bg-white px-5 py-3 text-sm font-semibold text-[#262ad6] shadow-[0_10px_24px_rgba(0,0,0,0.3)] transition hover:bg-[#f2f4ff]"
          >
            {primaryLabel}
          </PublicActionLink>
          <PublicActionLink
            href={secondaryHref}
            className="rounded-md border border-white/75 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
          >
            {secondaryLabel}
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}
