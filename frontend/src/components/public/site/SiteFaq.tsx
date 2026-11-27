import { SiteIcon } from "@/components/public/site/primitives";

type SiteFaqProps = {
  title: string;
  items: { question: string; answer: string }[];
};

/**
 * Minimal FAQ accordion built on native <details>, so answers stay in the
 * HTML for crawlers and work without JavaScript.
 */
export function SiteFaq({ title, items }: SiteFaqProps) {
  return (
    <section
      aria-labelledby="faq-title"
      className="px-4 py-20 lg:px-8 lg:py-28"
    >
      <div className="mx-auto w-full max-w-3xl">
        <h2
          id="faq-title"
          className="text-site-ink text-center text-3xl font-semibold tracking-tight md:text-4xl"
        >
          {title}
        </h2>
        <div className="divide-site-border border-site-border mt-10 divide-y border-y">
          {items.map((item) => (
            <details key={item.question} className="group py-1">
              <summary className="text-site-ink hover:text-site-accent-ink flex cursor-pointer list-none items-center justify-between gap-4 rounded-md py-4 text-base font-medium transition-colors [&::-webkit-details-marker]:hidden">
                {item.question}
                <SiteIcon
                  name="add"
                  className="text-site-ink-subtle text-xl transition-transform duration-200 group-open:rotate-45"
                />
              </summary>
              <p className="text-site-ink-muted pe-8 pb-5 text-sm leading-7">
                {item.answer}
              </p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
