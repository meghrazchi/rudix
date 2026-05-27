import { PublicActionLink } from "@/components/public/PublicActionLink";
import { ContactDemoFormCard } from "@/components/public/pages/contact/ContactDemoFormCard";
import {
  CONTACT_CARDS,
  CONTACT_FIT_HIGHLIGHTS,
} from "@/components/public/pages/contact/contactData";
import type { PublicSiteLinks } from "@/lib/public-site/links";
import type { ContactSubmissionConfig } from "@/lib/public-site/contact";

type ContactDemoSectionsProps = {
  links: PublicSiteLinks;
  submissionConfig: ContactSubmissionConfig;
};

function cardHref(
  cardTitle: (typeof CONTACT_CARDS)[number]["title"],
  links: PublicSiteLinks,
): string {
  if (cardTitle === "Sales") {
    return links.contact;
  }

  if (cardTitle === "Support") {
    return links.contact;
  }

  if (cardTitle === "Security review") {
    return links.securityContact;
  }

  return links.docs;
}

export function ContactHeroSection() {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 pt-14 pb-12 lg:px-8 lg:pt-20 lg:pb-16">
      <span className="text-xs font-bold tracking-[0.13em] text-[#3f37cd] uppercase">
        Connect with the Rudix team
      </span>
      <h1 className="mt-3 max-w-4xl text-4xl leading-tight font-black text-[#10131c] lg:text-6xl">
        Speak with us about your document workflow
      </h1>
      <p className="mt-4 max-w-3xl text-sm leading-8 text-[#5c6278] lg:text-lg">
        Book a demo or contact Rudix to discuss secure ingestion, retrieval,
        evaluation, and governance requirements for your team.
      </p>
    </section>
  );
}

export function ContactMainSection({
  links,
  submissionConfig,
}: ContactDemoSectionsProps) {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 pb-16 lg:px-8 lg:pb-20">
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <ContactDemoFormCard
            submissionConfig={submissionConfig}
            supportHref={links.contact}
            schedulerHref={submissionConfig.schedulerUrl}
          />
        </div>

        <div className="space-y-6 lg:col-span-5">
          <article className="rounded-xl bg-[#3525cd] p-7 text-white shadow-sm md:p-9">
            <h2 className="text-2xl font-black">
              Good fit for teams that need
            </h2>
            <ul className="mt-5 space-y-3">
              {CONTACT_FIT_HIGHLIGHTS.map((highlight) => (
                <li key={highlight} className="flex items-start gap-2">
                  <span
                    className="material-symbols-outlined mt-0.5 text-[#8af1a8]"
                    aria-hidden="true"
                  >
                    check_circle
                  </span>
                  <span className="text-sm leading-7 text-white/90">
                    {highlight}
                  </span>
                </li>
              ))}
            </ul>
          </article>

          <article className="rounded-xl border border-[#2e3140] bg-[#1f1f24] p-6 text-white shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-semibold tracking-[0.08em] text-[#c5cae0] uppercase">
                <span className="h-2 w-2 rounded-full bg-[#108548]" />
                System health
              </div>
              <span className="text-xs text-[#9ca2bd]">Operational</span>
            </div>
            <ul className="space-y-1.5 text-sm text-[#d6dbf0]">
              <li>&gt; Ingestion queue: healthy</li>
              <li>&gt; Retrieval latency: within target</li>
              <li>&gt; Evaluation jobs: available</li>
              <li>&gt; Audit pipeline: active</li>
            </ul>
          </article>

          <div className="grid gap-4 sm:grid-cols-2">
            {CONTACT_CARDS.map((card) => (
              <article
                key={card.title}
                className="rounded-xl border border-[#d8dce8] bg-white p-5 shadow-sm"
              >
                <h3 className="text-lg font-bold text-[#1a1f30]">
                  {card.title}
                </h3>
                <p className="mt-2 text-sm leading-7 text-[#5b6278]">
                  {card.description}
                </p>
                <PublicActionLink
                  href={cardHref(card.title, links)}
                  className="mt-4 inline-block text-sm font-semibold text-[#3128ad] underline decoration-[#b8bde9]"
                >
                  {card.actionLabel}
                </PublicActionLink>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function ContactMapSection() {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 pb-16 lg:px-8 lg:pb-24">
      
    </section>
    // <section className="mx-auto w-full max-w-7xl px-4 pb-16 lg:px-8 lg:pb-24">
    //   <div className="overflow-hidden rounded-xl border border-[#d8dce8] shadow-sm">
    //     <div className="relative h-56 bg-[radial-gradient(circle_at_top,#e4e7f4,#cfd4e7)] md:h-64">
    //       <div className="absolute inset-0 bg-gradient-to-t from-[#10131f]/50 via-transparent to-transparent" />
    //       <div className="absolute right-5 bottom-5 rounded-lg bg-white/90 px-4 py-3 text-sm text-[#1f2437] backdrop-blur">
    //         <p className="font-bold">Munich HQ</p>
    //         <p>Berg Am Laim St, Suite 3.15A, Munich 81673</p>
    //       </div>
    //     </div>
    //   </div>
    // </section>
  );
}
